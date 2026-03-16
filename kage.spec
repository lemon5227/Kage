from PyInstaller.utils.hooks import collect_all
import pathlib

block_cipher = None

# 1. Collect everything for complex ML packages
tmp_ret = collect_all('mlx')
datas_mlx, binaries_mlx, hiddenimports_mlx = tmp_ret

tmp_ret = collect_all('mlx_lm')
datas_mlx_lm, binaries_mlx_lm, hiddenimports_mlx_lm = tmp_ret

tmp_ret = collect_all('funasr')
datas_funasr, binaries_funasr, hiddenimports_funasr = tmp_ret

tmp_ret = collect_all('chromadb')
datas_chromadb, binaries_chromadb, hiddenimports_chromadb = tmp_ret

tmp_ret = collect_all('vosk')
datas_vosk, binaries_vosk, hiddenimports_vosk = tmp_ret

tmp_ret = collect_all('onnxruntime')
datas_onnx, binaries_onnx, hiddenimports_onnx = tmp_ret

tmp_ret = collect_all('openwakeword')
datas_oww, binaries_oww, hiddenimports_oww = tmp_ret

tmp_ret = collect_all('jieba')
datas_jieba, binaries_jieba, hiddenimports_jieba = tmp_ret

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules
datas_pil = []
binaries_pil = collect_dynamic_libs('PIL')
hiddenimports_pil = collect_submodules('PIL')

tmp_ret = collect_all('lxml')
datas_lxml, binaries_lxml, hiddenimports_lxml = tmp_ret

tmp_ret = collect_all('rumps')
datas_rumps, binaries_rumps, hiddenimports_rumps = tmp_ret

# 2. Base Hidden imports
base_hidden_imports = [
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
    'engineio.async_drivers.aiohttp',
    'modelscope',
    'edge_tts',
    'pygame',
    'numpy',
    'chromadb',
    'chromadb.telemetry.product.posthog', 
    'pyaudio',
    'wave',
    'sqlite3',
    'PIL',
    'lxml',
    'openpyxl',
    'pdf2image',
    'pypdf',
    'six',
    'Quartz',
    'rumps',
    'pyobjc',
    'objc',
    'uvicorn',
    'shutil',
    'fastapi',
    'starlette',
    'starlette',
    'pydantic',
    'overrides',
]



# Merge all
hidden_imports = base_hidden_imports + hiddenimports_mlx + hiddenimports_mlx_lm + hiddenimports_funasr + hiddenimports_chromadb + hiddenimports_vosk + hiddenimports_onnx + hiddenimports_oww + hiddenimports_jieba + hiddenimports_pil + hiddenimports_lxml + hiddenimports_rumps
all_datas = datas_mlx + datas_mlx_lm + datas_funasr + datas_chromadb + datas_vosk + datas_onnx + datas_oww + datas_jieba + datas_pil + datas_lxml + datas_rumps + [
    ('config', 'config'),      
    ('core', 'core'),          
    ('abilities', 'abilities'),
    ('assets', 'assets'),       # 托盘图标
    ('skills', 'skills'),       # 技能文件
]

# Explicitly include mlx.metallib without hard-coded paths.
try:
    import mlx  # type: ignore

    metallib = pathlib.Path(getattr(mlx, "__file__", "")).resolve().parent / "lib" / "mlx.metallib"
    if metallib.exists():
        all_datas.append((str(metallib), "."))
except Exception:
    pass
all_binaries = binaries_mlx + binaries_mlx_lm + binaries_funasr + binaries_chromadb + binaries_vosk + binaries_onnx + binaries_oww + binaries_jieba + binaries_pil + binaries_lxml + binaries_rumps

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=all_binaries,
    datas=all_datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'PyQt5', 'PySide2', 'ipython', 'pytest'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='kage-server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='kage-server',
)
