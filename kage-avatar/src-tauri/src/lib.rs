// Kage System Tray - Native Tauri Implementation
use std::env;
use std::io::{BufRead, BufReader};
use std::net::{SocketAddr, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Mutex, OnceLock,
};
use std::thread;
use std::time::Duration;
use tauri::{
    image::Image,
    menu::{CheckMenuItem, Menu, MenuItem, PredefinedMenuItem, Submenu},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    AppHandle, Emitter, Manager, Url,
};

// Store the backend process handle
static BACKEND_PROCESS: Mutex<Option<Child>> = Mutex::new(None);
static VOICE_ENABLED: AtomicBool = AtomicBool::new(true);
static LOG_BUFFER: OnceLock<Mutex<Vec<String>>> = OnceLock::new();

fn log_buffer() -> &'static Mutex<Vec<String>> {
    LOG_BUFFER.get_or_init(|| Mutex::new(Vec::new()))
}

fn push_log(line: String) {
    let mut guard = log_buffer().lock().unwrap();
    guard.push(line);
    let cap = 2000;
    if guard.len() > cap {
        let drain = guard.len() - cap;
        guard.drain(0..drain);
    }
}

fn env_truthy(name: &str) -> bool {
    match env::var(name) {
        Ok(v) => {
            let v = v.trim().to_lowercase();
            matches!(v.as_str(), "1" | "true" | "yes" | "y" | "on")
        }
        Err(_) => false,
    }
}

fn is_backend_running() -> bool {
    if let Ok(mut guard) = BACKEND_PROCESS.lock() {
        if let Some(child) = guard.as_mut() {
            match child.try_wait() {
                Ok(Some(_)) => {
                    *guard = None;
                    false
                }
                Ok(None) => true,
                Err(_) => false,
            }
        } else {
            false
        }
    } else {
        false
    }
}

fn port_in_use(port: u16) -> bool {
    let addr: SocketAddr = format!("127.0.0.1:{}", port)
        .parse()
        .unwrap_or_else(|_| SocketAddr::from(([127, 0, 0, 1], port)));
    TcpStream::connect_timeout(&addr, Duration::from_millis(150)).is_ok()
}

fn parse_pids(text: &str) -> Vec<u32> {
    text.lines()
        .filter_map(|l| l.trim().parse::<u32>().ok())
        .collect()
}

fn pid_command(pid: u32) -> Option<String> {
    let out = Command::new("ps")
        .arg("-o")
        .arg("command=")
        .arg("-p")
        .arg(pid.to_string())
        .output()
        .ok()?;
    if !out.status.success() {
        return None;
    }
    Some(String::from_utf8_lossy(&out.stdout).trim().to_string())
}

fn kill_pid(pid: u32) {
    let _ = Command::new("kill")
        .arg("-TERM")
        .arg(pid.to_string())
        .spawn();
    thread::sleep(Duration::from_millis(200));
    let _ = Command::new("kill")
        .arg("-KILL")
        .arg(pid.to_string())
        .spawn();
}

fn cleanup_backend_port_12345() -> (usize, Vec<u32>) {
    // DEV convenience: prevent leaked backends from blocking the next run.
    // Only kills processes that look like Kage backend (main.py / kage-server).
    let out = Command::new("lsof").arg("-ti").arg("tcp:12345").output();

    let out = match out {
        Ok(o) if o.status.success() => o,
        _ => return (0, vec![]),
    };

    let pids = parse_pids(&String::from_utf8_lossy(&out.stdout));
    let mut killed = vec![];
    for pid in pids {
        if let Some(cmd) = pid_command(pid) {
            let cmd_l = cmd.to_lowercase();
            let looks_like_kage = cmd_l.contains("/kage/main.py")
                || (cmd_l.contains("python")
                    && cmd_l.contains("main.py")
                    && cmd_l.contains("/kage/"))
                || cmd_l.contains("kage-server");
            if looks_like_kage {
                println!("🧹 Killing leaked backend pid {}: {}", pid, cmd);
                kill_pid(pid);
                killed.push(pid);
            }
        }
    }
    (killed.len(), killed)
}

fn set_backend(child: Child) {
    if let Ok(mut guard) = BACKEND_PROCESS.lock() {
        *guard = Some(child);
    }
}

fn attach_log_forwarders(app: AppHandle, child: &mut Child) {
    if let Some(stdout) = child.stdout.take() {
        let app_clone = app.clone();
        thread::spawn(move || {
            let reader = BufReader::new(stdout);
            for line in reader.lines() {
                if let Ok(line) = line {
                    push_log(format!("[stdout] {}", line));
                    let _ = app_clone.emit(
                        "backend-log",
                        serde_json::json!({"stream": "stdout", "line": line}),
                    );
                }
            }
        });
    }

    if let Some(stderr) = child.stderr.take() {
        let app_clone = app.clone();
        thread::spawn(move || {
            let reader = BufReader::new(stderr);
            for line in reader.lines() {
                if let Ok(line) = line {
                    push_log(format!("[stderr] {}", line));
                    let _ = app_clone.emit(
                        "backend-log",
                        serde_json::json!({"stream": "stderr", "line": line}),
                    );
                }
            }
        });
    }
}

fn expand_tilde(path: &str) -> PathBuf {
    if let Some(stripped) = path.strip_prefix("~/") {
        if let Some(home) = dirs::home_dir() {
            return home.join(stripped);
        }
    }
    PathBuf::from(path)
}

fn get_backend_path(app: &AppHandle) -> Option<std::path::PathBuf> {
    let resource_path = app
        .path()
        .resource_dir()
        .expect("Failed to get resource dir");

    // Try multiple possible paths for the backend
    let possible_paths = [
        // Standard Tauri resource path
        resource_path
            .join("dist")
            .join("kage-server")
            .join("kage-server"),
        // Old structure with _up_ folders
        resource_path
            .join("_up_")
            .join("_up_")
            .join("dist")
            .join("kage-server")
            .join("kage-server"),
        // Alternative structure
        resource_path
            .join("..")
            .join("..")
            .join("dist")
            .join("kage-server")
            .join("kage-server"),
        // Development fallback
        std::path::PathBuf::from("dist")
            .join("kage-server")
            .join("kage-server"),
    ];

    for path in &possible_paths {
        println!("🔍 Checking backend at: {:?}", path);
        if path.exists() {
            println!("✅ Found backend at: {:?}", path);
            return Some(path.clone());
        }
    }

    println!("⚠️ Backend not found in any expected location");
    println!("   Resource dir: {:?}", resource_path);
    None
}

fn start_bundled_backend(app: &AppHandle) -> Result<Child, String> {
    let backend_path = match get_backend_path(app) {
        Some(path) => path,
        None => {
            eprintln!("❌ Backend executable not found in any expected location");
            show_notification(app, "Kage Error", "后端程序未找到");
            return Err("backend missing".into());
        }
    };

    let work_dir = backend_path
        .parent()
        .expect("Backend path must have a parent directory");

    println!("🚀 Starting backend: {:?}", backend_path);
    println!("📂 Working directory: {:?}", work_dir);

    // Check _internal directory exists
    let internal_dir = work_dir.join("_internal");
    if !internal_dir.exists() {
        println!("⚠️ _internal directory not found at {:?}", internal_dir);
        show_notification(app, "Kage Error", "后端依赖目录未找到");
    }

    Command::new(&backend_path)
        .current_dir(work_dir)
        .env("PYTHONHOME", "") // Clear to prevent conflicts
        .env("PYTHONPATH", "") // Clear to prevent conflicts
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| {
            eprintln!("❌ Failed to start backend: {}", e);
            show_notification(app, "Kage Error", &format!("后端启动失败: {}", e));
            format!("failed to start bundled backend: {}", e)
        })
}

fn start_dev_backend(_app: &AppHandle) -> Result<Child, String> {
    // Workdir: repo root (two levels up from src-tauri)
    // CARGO_MANIFEST_DIR points to: <repo>/kage-avatar/src-tauri
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let work_dir = manifest_dir.join("..");
    let work_dir = work_dir.join("..");
    let work_dir = work_dir
        .canonicalize()
        .map_err(|e| format!("failed to resolve repo root: {}", e))?;

    let main_py = work_dir.join("main.py");
    if !main_py.exists() {
        return Err(format!("main.py not found at {:?}", main_py));
    }

    // Prefer direct python binary to preserve stdout/stderr piping.
    // `conda run` may not forward child output through pipes reliably.
    let python_candidates = [
        "~/miniconda3/envs/Kage/bin/python",
        "~/anaconda3/envs/Kage/bin/python",
    ];
    for candidate in python_candidates {
        let python = expand_tilde(candidate);
        if python.exists() {
            println!("🐍 Starting dev backend via python: {:?}", python);
            return Command::new(python)
                .arg("-u")
                .arg(main_py)
                .current_dir(work_dir)
                .env("KAGE_NO_TRAY", "1")
                .env("KAGE_MODE", "control")
                .env("PYTHONUNBUFFERED", "1")
                .stdout(Stdio::piped())
                .stderr(Stdio::piped())
                .spawn()
                .map_err(|e| format!("failed to start dev backend via python: {}", e));
        }
    }

    let conda_candidates = ["~/miniconda3/bin/conda", "~/anaconda3/bin/conda", "conda"];
    let mut conda_path: Option<PathBuf> = None;
    for candidate in conda_candidates {
        let path = expand_tilde(candidate);
        if candidate == "conda" {
            conda_path = Some(PathBuf::from(candidate));
            break;
        }
        if path.exists() {
            conda_path = Some(path);
            break;
        }
    }
    let conda =
        conda_path.ok_or_else(|| "conda not found; expected ~/miniconda3/bin/conda".to_string())?;

    println!("🧪 Falling back to conda: {:?}", conda);
    Command::new(conda)
        .arg("run")
        .arg("-n")
        .arg("Kage")
        .arg("python")
        .arg("-u")
        .arg(main_py)
        .current_dir(work_dir)
        .env("KAGE_NO_TRAY", "1")
        .env("KAGE_MODE", "control")
        .env("PYTHONUNBUFFERED", "1")
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("failed to start dev backend via conda: {}", e))
}

fn start_backend(app: &AppHandle) -> Result<(), String> {
    if env_truthy("KAGE_FRONTEND_ONLY") {
        println!("🧪 KAGE_FRONTEND_ONLY=1, skipping backend start");
        let _ = app.emit(
            "backend-status",
            serde_json::json!({"state": "stopped", "reason": "frontend only"}),
        );
        return Ok(());
    }

    if is_backend_running() {
        println!("⚙️ Backend already running");
        return Ok(());
    }

    if cfg!(debug_assertions) {
        if port_in_use(12345) {
            // Likely a leaked dev backend.
            let (count, killed) = cleanup_backend_port_12345();
            if count > 0 {
                let _ = app.emit(
                    "backend-log",
                    serde_json::json!({"stream": "stderr", "line": format!("killed leaked backend processes on :12345: {:?}", killed)}),
                );
            } else {
                println!("⚠️ Port 12345 already in use; assuming backend is already running");
                let _ = app.emit(
                    "backend-status",
                    serde_json::json!({"state": "running", "pid": serde_json::Value::Null, "reason": "port 12345 already in use"}),
                );
                return Ok(());
            }
        }

        println!("🔧 Dev mode: starting Python backend via conda env 'Kage'");
        let mut child = start_dev_backend(app)?;
        attach_log_forwarders(app.clone(), &mut child);
        let pid = child.id();
        set_backend(child);
        let _ = app.emit(
            "backend-status",
            serde_json::json!({"state": "running", "pid": pid}),
        );
        println!("✅ Dev backend started with PID: {}", pid);
    } else {
        println!("🧊 Release mode: starting bundled backend");
        let mut child = start_bundled_backend(app)?;
        attach_log_forwarders(app.clone(), &mut child);
        let pid = child.id();
        set_backend(child);
        let _ = app.emit(
            "backend-status",
            serde_json::json!({"state": "running", "pid": pid}),
        );
        println!("✅ Backend started with PID: {}", pid);
    }

    Ok(())
}

fn stop_backend() {
    if let Ok(mut guard) = BACKEND_PROCESS.lock() {
        if let Some(ref mut child) = *guard {
            println!("🛑 Stopping backend...");
            let _ = child.kill();
            let _ = child.wait();
        }
        *guard = None;
    }

    if cfg!(debug_assertions) {
        let (count, killed) = cleanup_backend_port_12345();
        if count > 0 {
            println!("🧹 Killed leaked backend pids: {:?}", killed);
        }
    }
}

fn show_notification(_app: &AppHandle, title: &str, body: &str) {
    let script = format!(r#"display notification "{}" with title "{}""#, body, title);
    let _ = Command::new("osascript").arg("-e").arg(&script).spawn();
}

#[tauri::command]
fn stop_backend_cmd(app: AppHandle) -> Result<(), String> {
    stop_backend();
    let _ = app.emit("backend-status", serde_json::json!({"state": "stopped"}));
    Ok(())
}

#[tauri::command]
fn start_backend_cmd(app: AppHandle) -> Result<(), String> {
    start_backend(&app)?;
    Ok(())
}

#[tauri::command]
fn get_recent_logs() -> Vec<String> {
    log_buffer().lock().unwrap().clone()
}

// Tauri command to launch Kage from launcher
#[tauri::command]
fn launch_kage(app: AppHandle) -> Result<String, String> {
    println!("🚀 Launch Kage command received");

    if let Err(e) = start_backend(&app) {
        return Err(format!("Failed to start backend: {}", e));
    }

    // Show main window
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.set_focus();
    }

    // Keep the launcher visible as a live console.
    // The user can hide it manually or via the tray menu.

    Ok("Kage launched successfully".to_string())
}

#[tauri::command]
fn show_main_window(app: AppHandle) -> Result<(), String> {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.set_focus();
        return Ok(());
    }
    Err("main window not found".to_string())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            launch_kage,
            get_recent_logs,
            stop_backend_cmd,
            start_backend_cmd,
            show_main_window
        ])
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_http::init())
        .setup(|app| {
            println!("🎯 Kage Launcher ready - auto starting backend");
            let handle = app.app_handle();

            // Dev: force the launcher window to load from Vite dev server so edits to
            // `public/launcher.html` take effect immediately.
            #[cfg(debug_assertions)]
            {
                let handle2 = handle.clone();
                tauri::async_runtime::spawn(async move {
                    // Delay a bit to ensure the window exists.
                    std::thread::sleep(Duration::from_millis(250));
                    if let Some(window) = handle2.get_webview_window("launcher") {
                        let host = env::var("TAURI_DEV_HOST").unwrap_or_else(|_| "localhost".to_string());
                        let url_s = format!("http://{}:1420/launcher.html", host);
                        println!("🧭 Dev navigate launcher -> {}", url_s);
                        if let Ok(url) = Url::parse(&url_s) {
                            let _ = window.navigate(url);
                        }
                    }
                });
            }
            if env_truthy("KAGE_FRONTEND_ONLY") {
                println!("🧪 KAGE_FRONTEND_ONLY=1, backend autostart disabled");
                let _ = handle.emit(
                    "backend-status",
                    serde_json::json!({"state": "stopped", "reason": "frontend only"}),
                );
            } else if let Err(e) = start_backend(&handle) {
                eprintln!("❌ Failed to auto-start backend: {}", e);
                let _ = handle.emit(
                    "backend-status",
                    serde_json::json!({"state": "failed", "reason": e}),
                );
            }

            // Load tray icon (embedded at compile time to avoid path issues)
            let icon_data = include_bytes!("../assets/tray_icon@2x.png");
            let tray_icon = Image::from_bytes(icon_data)
                .unwrap_or_else(|_| app.default_window_icon().unwrap().clone());

            // Clean native macOS style menu (no icons, just text)
            let version_i = MenuItem::with_id(app, "version", "Kage v1.0.0", false, None::<&str>)?;
            let show_i = MenuItem::with_id(app, "show", "显示/隐藏窗口", true, None::<&str>)?;
            let voice_i =
                CheckMenuItem::with_id(app, "voice", "语音识别", true, true, None::<&str>)?;
            let launcher_i = MenuItem::with_id(app, "launcher", "打开启动器", true, None::<&str>)?;
            let about_i = MenuItem::with_id(app, "about", "关于 Kage", true, None::<&str>)?;
            let quit_i = MenuItem::with_id(app, "quit", "退出 Kage", true, None::<&str>)?;

            // Live2D submenu
            let booth_i = MenuItem::with_id(app, "booth", "Booth 模型商店", true, None::<&str>)?;
            let live2d_official_i = MenuItem::with_id(
                app,
                "live2d_official",
                "Live2D 官方示例",
                true,
                None::<&str>,
            )?;
            let import_model_i =
                MenuItem::with_id(app, "import_model", "导入本地模型...", true, None::<&str>)?;
            let live2d_menu = Submenu::with_items(
                app,
                "Live2D 角色",
                true,
                &[
                    &booth_i,
                    &live2d_official_i,
                    &PredefinedMenuItem::separator(app)?,
                    &import_model_i,
                ],
            )?;

            let menu = Menu::with_items(
                app,
                &[
                    &version_i,
                    &PredefinedMenuItem::separator(app)?,
                    &show_i,
                    &voice_i,
                    &launcher_i,
                    &PredefinedMenuItem::separator(app)?,
                    &live2d_menu,
                    &PredefinedMenuItem::separator(app)?,
                    &about_i,
                    &quit_i,
                ],
            )?;

            // Build tray icon
            let _tray = TrayIconBuilder::new()
                .icon(tray_icon)
                .icon_as_template(true)
                .menu(&menu)
                .show_menu_on_left_click(true)
                .on_menu_event(move |app, event| match event.id.as_ref() {
                    "quit" => {
                        stop_backend();
                        app.exit(0);
                    }
                    "show" => {
                        if let Some(window) = app.get_webview_window("main") {
                            if window.is_visible().unwrap_or(false) {
                                let _ = window.hide();
                            } else {
                                let _ = window.show();
                                let _ = window.set_focus();
                            }
                        }
                    }
                    "voice" => {
                        let was_enabled = VOICE_ENABLED.load(Ordering::SeqCst);
                        let now_enabled = !was_enabled;
                        VOICE_ENABLED.store(now_enabled, Ordering::SeqCst);

                        if now_enabled {
                            show_notification(app, "Kage", "语音识别已开启");
                        } else {
                            show_notification(app, "Kage", "语音识别已关闭");
                        }

                        let _ = app.emit("voice-toggle", now_enabled);
                    }
                    "launcher" => {
                        // Show launcher window
                        if let Some(window) = app.get_webview_window("launcher") {
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                    "about" => {
                        show_notification(app, "Kage v1.0.0", "你的 AI 桌面助手");
                    }
                    "booth" => {
                        let _ = opener::open_browser("https://booth.pm/zh-cn/search/Live2D");
                    }
                    "live2d_official" => {
                        let _ =
                            opener::open_browser("https://www.live2d.com/en/download/sample-data/");
                    }
                    "import_model" => {
                        show_notification(app, "Kage", "导入功能开发中");
                    }
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        let app = tray.app_handle();
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                })
                .build(app)?;

            println!("🎯 System tray initialized");
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                let _ = window.hide();
                api.prevent_close();
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");

    stop_backend();
}
