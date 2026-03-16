import './style.css';
import * as PIXI from 'pixi.js';
import { Live2DModel } from 'pixi-live2d-display';
import { getCurrentWindow } from '@tauri-apps/api/window';

const MOTION_COOLDOWN_MS = 4000;
const MOTION_DEMO_LOOP = false;
const MOTION_DEMO_INTERVAL_MS = 3500;
const EXPRESSION_DEMO_LOOP = false;
const EXPRESSION_DEMO_INTERVAL_MS = 2500;
const EXPRESSION_DEMO_LABEL_ID = 'expression-demo-label';
const EXPRESSION_NEUTRAL = 'f05';

// Expose PIXI to window (Required by plugin)
(window as any).PIXI = PIXI;

// Register Ticker
Live2DModel.registerTicker(PIXI.Ticker);

// --- 1. Initialize PIXI v6 Application ---
const app = new PIXI.Application({
  width: 350,
  height: 550,
  transparent: true,
  resolution: window.devicePixelRatio || 1, // Fix Blurring
  autoDensity: true, // Handle CSS scaling
  resizeTo: window,
  autoStart: true
});

// Append to DOM
const canvas = app.view as HTMLCanvasElement;
// CRITICAL: Apply drag region to the canvas itself so clicks on it trigger drag
canvas.setAttribute('data-tauri-drag-region', 'true');
canvas.style.cursor = 'grab';
// Make canvas focusable so it can receive key events reliably.
canvas.tabIndex = 0;
document.getElementById('app')?.appendChild(canvas);

// --- 2. Enable Window Dragging (Manual JS - More Robust) ---
// Click anywhere on the canvas to drag the window
canvas.addEventListener('mousedown', () => {
  getCurrentWindow().startDragging();
});

// Keep focus on the canvas so keyboard shortcuts work.
canvas.addEventListener('pointerdown', () => {
  try {
    canvas.focus();
  } catch {
    // ignore
  }
});

// --- Avatar crop (WebView-level clip, reliable) ---
const CROP_STORAGE_KEY = 'kage.cropBottomPx';
const DEFAULT_CROP_BOTTOM_PX = 190;

function clampInt(v: unknown, min: number, max: number, fallback: number): number {
  const n = typeof v === 'number' ? v : Number(String(v ?? '').trim());
  if (!Number.isFinite(n)) return fallback;
  return Math.max(min, Math.min(max, Math.round(n)));
}

function getCropBottomPx(): number {
  try {
    const raw = localStorage.getItem(CROP_STORAGE_KEY);
    return clampInt(raw, 0, 500, DEFAULT_CROP_BOTTOM_PX);
  } catch {
    return DEFAULT_CROP_BOTTOM_PX;
  }
}

let cropBottomPx = getCropBottomPx();

function applyCrop(px: number) {
  cropBottomPx = clampInt(px, 0, 500, DEFAULT_CROP_BOTTOM_PX);
  // Ensure the canvas covers the whole window so clipping is deterministic.
  canvas.style.position = 'fixed';
  canvas.style.left = '0';
  canvas.style.top = '0';
  canvas.style.width = '100%';
  canvas.style.height = '100%';

  const clip = `inset(0px 0px ${cropBottomPx}px 0px)`;
  canvas.style.clipPath = clip;
  // Safari/WebKit
  (canvas.style as any).webkitClipPath = clip;
}

applyCrop(cropBottomPx);

// Listen for cross-window updates from the launcher
try {
  const bc = new BroadcastChannel('kage-settings');
  bc.addEventListener('message', (ev) => {
    const msg = ev.data || {};
    if (msg && msg.type === 'crop' && msg.value != null) {
      applyCrop(msg.value);
    }
  });
} catch {
  // BroadcastChannel not available
}

window.addEventListener('storage', (e) => {
  if (e.key === CROP_STORAGE_KEY) {
    applyCrop(getCropBottomPx());
  }
});

// --- 3. Load Model ---
// Debug log collector for on-screen display
const debugLogs: string[] = [];
function addLog(msg: string) {
  const timestamp = new Date().toLocaleTimeString();
  const logMsg = `[${timestamp}] ${msg}`;
  console.log(logMsg);
  debugLogs.push(logMsg);
  if (debugLogs.length > 100) {
    debugLogs.shift();
  }
}

function showFatalError(title: string, error: any) {
  console.error(`❌ ${title}:`, error);
  const errorDisplay = document.getElementById('error-display');
  const errorMessage = document.getElementById('error-message');
  if (errorDisplay && errorMessage) {
    let errorText = `${title}\n\n`;
    errorText += `错误详情: ${error?.message || error}\n\n`;
    errorText += `调试日志:\n${debugLogs.slice(-20).join('\n')}\n\n`;
    errorText += `环境信息:\n`;
    errorText += `- URL: ${window.location.href}\n`;
    errorText += `- UserAgent: ${navigator.userAgent}\n`;
    errorText += `- Live2DCubismCore: ${typeof (window as any).Live2DCubismCore !== 'undefined' ? '✅ 已加载' : '❌ 未加载'}\n`;
    errorText += `- PIXI: ${typeof PIXI !== 'undefined' ? '✅ 已加载' : '❌ 未加载'}\n`;
    errorMessage.textContent = errorText;
    errorDisplay.style.display = 'block';
  }
}

async function main() {
  try {
    addLog("🔍 检查 Live2D SDK...");
    const cubismLoaded = typeof (window as any).Live2DCubismCore !== 'undefined';
    const pixiLoaded = typeof PIXI !== 'undefined';
    addLog(`  - Live2DCubismCore: ${cubismLoaded ? '✅' : '❌'}`);
    addLog(`  - PIXI: ${pixiLoaded ? '✅' : '❌'}`);

    if (!cubismLoaded) {
      throw new Error("Live2DCubismCore 未加载! 请检查 live2dcubismcore.min.js 是否正确加载");
    }
    if (!pixiLoaded) {
      throw new Error("PIXI 未加载!");
    }

    // 使用相对路径加载模型
    const modelPath = './models/haru/haru_greeter_t03.model3.json';
    addLog(`📦 加载模型: ${modelPath}`);
    
    let model: Live2DModel;
    try {
      model = await Live2DModel.from(modelPath);
      addLog("✅ Model 对象创建成功");
    } catch (modelError: any) {
      addLog(`❌ 模型加载失败: ${modelError}`);
      try {
        const response = await fetch(modelPath, { method: 'HEAD' });
        addLog(`  - 模型文件检查: ${response.status} ${response.statusText}`);
      } catch (fetchError: any) {
        addLog(`  - 无法访问模型文件: ${fetchError}`);
      }
      throw modelError;
    }

    // Put model into a dedicated container so masking is reliable.
    const avatarContainer = new PIXI.Container();
    app.stage.addChild(avatarContainer);
    avatarContainer.addChild(model);
    addLog("✅ Model added to stage");

    // Scale and Position (known-good framing)
    model.scale.set(0.13);
    model.x = -50;
    model.y = -20;

    // Crop is controlled via launcher and applied at the canvas level.

    addLog("✅ Model Loaded and positioned!");

    // --- 4. WebSocket Connection (Brain) ---
    setupWebSocket(model);

    if (MOTION_DEMO_LOOP) {
      startMotionDemoLoop(model);
    }

    if (EXPRESSION_DEMO_LOOP) {
      startExpressionDemoLoop(model);
    }


    // --- 5. LipSync Animation Loop ---
    let mouthValue = 0;

    // Debug flag to print API structure once
    let hasLoggedApi = false;

    app.ticker.add((delta) => {
      if (!model || !model.internalModel) return;

      // DEBUG: Check what APIs are available
      if (!hasLoggedApi) {
        console.log("Model Type:", model.constructor.name);
        console.log("Internal Model:", model.internalModel);
        // @ts-ignore
        if (model.internalModel.coreModel) {
          const core = model.internalModel.coreModel;
          console.log("Core Model:", core);
          // @ts-ignore
          if (core._parameterIds) console.log("Core Indices:", core._parameterIds);
          // @ts-ignore
          if (core.parameters) console.log("Core Parameters:", core.parameters);
        }
        // @ts-ignore
        if (model.internalModel.parameters) console.log("High-level Params:", model.internalModel.parameters);

        hasLoggedApi = true;
      }

      if (isSpeaking) {
        const t = Date.now() / 150; // Slower sine wave
        mouthValue = (Math.sin(t) + 1) / 2 * 0.8; // 0 to 0.8
        // DEBUG: Visual Signal (kept inside crop)
        canvas.style.boxShadow = 'inset 0 0 0 4px rgba(255, 60, 60, 0.92)';
      } else {
        mouthValue = Math.max(0, mouthValue - 0.1 * delta);
        canvas.style.boxShadow = 'none';
      }

      // --- UNIVERSAL PARAMETER SETTER ---
      // Try all known ways to set ParamMouthOpenY for Pixi-Live2D v0.4 / Cubism 4

      try {
        const im = model.internalModel;
        const core = im.coreModel;
        const paramId = 'ParamMouthOpenY';

        // Method 1: High Level .parameters (If exists)
        // @ts-ignore
        if (im.parameters && im.parameters.ids) {
          // @ts-ignore
          const idx = im.parameters.ids.indexOf(paramId);
          if (idx >= 0) {
            // @ts-ignore
            im.parameters.values[idx] = mouthValue;
            // Note: Some versions require .setValue(id, val)
          }
        }

        // Method 2: Core Model Index (Standard Cubism 4)
        // @ts-ignore
        if (core && core._parameterIds) {
          // @ts-ignore
          const idx = core._parameterIds.indexOf(paramId);
          if (idx >= 0) {
            // @ts-ignore
            core.setParameterValueByIndex(idx, mouthValue, 1.0);
          }
        }

        // Method 3: Core Model Direct ID (Cubism 2/3 Legacy or Wrapper)
        // @ts-ignore
        if (core && core.setParameterValueById) {
          // @ts-ignore
          core.setParameterValueById(paramId, mouthValue);
        }

      } catch (e) {
        // Suppress errors to avoid console flood
      }
    });

  } catch (e) {
    addLog(`❌ Live2D Load Error: ${e}`);
    showFatalError("Live2D 加载失败", e);
  }
}

let isSpeaking = false;
let reconnectTimer: number | undefined;

function setupWebSocket(model: Live2DModel) {
  if (reconnectTimer) {
    window.clearTimeout(reconnectTimer);
    reconnectTimer = undefined;
  }
  const socket = new WebSocket("ws://127.0.0.1:12345/ws");
  let lastMotionAt = 0;
  let expressionResetTimer: number | undefined;

  socket.onopen = () => console.log("🔌 Connected to Brain");

  socket.onerror = () => {
    try {
      socket.close();
    } catch (e) {
      console.error('Socket Close Error', e);
    }
  };

  socket.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);

      // Handle Speaking State
      if (data.type === "state") {
        console.log("State:", data.state, data.dialog_phase || "", data.pending_kind || "");
        try {
          window.dispatchEvent(new CustomEvent('kage:state', {
            detail: {
              state: data.state,
              dialogPhase: data.dialog_phase || '',
              pendingKind: data.pending_kind || '',
            }
          }));
        } catch (e) {
          console.error('State Event Error', e);
        }
        if (data.state === "SPEAKING") {
          isSpeaking = true;
        } else if (data.state === "IDLE" || data.state === "LISTENING") {
          isSpeaking = false;
        }
      }

      // Handle Speech Text
      if (data.type === "speech") {
        console.log("Kage Says: " + data.text);
      }

      if (data.type === "job") {
        console.log("Job Event:", data.event, data.job);
        try {
          window.dispatchEvent(new CustomEvent('kage:job', {
            detail: {
              event: data.event || '',
              job: data.job || {},
              dialogPhase: data.dialog_phase || '',
              pendingKind: data.pending_kind || '',
            }
          }));
        } catch (e) {
          console.error('Job Event Error', e);
        }
      }

      if (data.type === "audio") {
        console.log("Audio Event:", data.event, data.source || "");
        try {
          window.dispatchEvent(new CustomEvent('kage:audio', {
            detail: {
              event: data.event || '',
              source: data.source || '',
              dialogPhase: data.dialog_phase || '',
              pendingKind: data.pending_kind || '',
              textLen: Number(data.text_len || 0),
            }
          }));
        } catch (e) {
          console.error('Audio Event Error', e);
        }
      }

      // Handle Expression Change
      if (data.type === "expression") {
        console.log("Expression:", data.name);
        try {
          model.expression(data.name);
          if (expressionResetTimer) {
            window.clearTimeout(expressionResetTimer);
            expressionResetTimer = undefined;
          }
          if (data.duration) {
            const durationMs = Math.max(0, Number(data.duration) * 1000);
            if (durationMs > 0) {
              expressionResetTimer = window.setTimeout(() => {
                try {
                  model.expression(EXPRESSION_NEUTRAL);
                } catch (e) {
                  console.error('Expression Reset Error', e);
                }
              }, durationMs);
            }
          }
        } catch (e) { console.error("Expr Error", e); }
      }

      // Handle Motion Trigger
      if (data.type === "motion") {
        console.log("Motion:", data.group, data.index);
        const now = Date.now();
        if (now - lastMotionAt < MOTION_COOLDOWN_MS) {
          return;
        }
        lastMotionAt = now;
        try {
          model.motion(data.group, data.index);
        } catch (e) { console.error("Motion Error", e); }
      }

    } catch (e) {
      console.error("WS Parse Error", e);
    }
  };

  socket.onclose = () => {
    console.log("Disconnected. Retrying in 3s...");
    if (reconnectTimer) {
      return;
    }
    reconnectTimer = window.setTimeout(() => {
      reconnectTimer = undefined;
      setupWebSocket(model);
    }, 3000);
  };
}

function startMotionDemoLoop(model: Live2DModel) {
  const motions = [
    { group: 'Idle', index: 0 },
    { group: 'Idle', index: 1 },
    { group: 'Idle', index: 2 },
    { group: 'Tap', index: 0 },
    { group: 'Tap', index: 1 }
  ];
  let cursor = 0;

  setTimeout(() => {
    setInterval(() => {
      const motion = motions[cursor % motions.length];
      cursor += 1;
      console.log('Motion Demo:', motion.group, motion.index);
      try {
        model.motion(motion.group, motion.index);
      } catch (e) {
        console.error('Motion Demo Error', e);
      }
    }, MOTION_DEMO_INTERVAL_MS);
  }, 800);
}

function startExpressionDemoLoop(model: Live2DModel) {
  const label = ensureExpressionDemoLabel();
  const expressions = [
    'f00', 'f01', 'f02', 'f03', 'f04', 'f05', 'f06', 'f07'
  ];
  let cursor = 0;

  setTimeout(() => {
    setInterval(() => {
      const name = expressions[cursor % expressions.length];
      cursor += 1;
      console.log('Expression Demo:', name);
      try {
        if (label) {
          label.textContent = `Expression: ${name}`;
        }
        model.expression(name);
      } catch (e) {
        console.error('Expression Demo Error', e);
      }
    }, EXPRESSION_DEMO_INTERVAL_MS);
  }, 800);
}

function ensureExpressionDemoLabel() {
  let label = document.getElementById(EXPRESSION_DEMO_LABEL_ID);
  if (label) {
    return label;
  }

  label = document.createElement('div');
  label.id = EXPRESSION_DEMO_LABEL_ID;
  label.textContent = 'Expression: pending';
  label.style.position = 'fixed';
  label.style.left = '12px';
  label.style.top = '12px';
  label.style.padding = '6px 10px';
  label.style.fontFamily = 'system-ui, -apple-system, sans-serif';
  label.style.fontSize = '12px';
  label.style.color = '#ffffff';
  label.style.background = 'rgba(0, 0, 0, 0.6)';
  label.style.borderRadius = '8px';
  label.style.zIndex = '9999';
  label.style.pointerEvents = 'none';
  document.body.appendChild(label);
  return label;
}

// 启动主函数
main().catch((e) => {
  console.error("未捕获的错误:", e);
  showFatalError("未捕获的启动错误", e);
});
