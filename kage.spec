from PyInstaller.utils.hooks import collect_all

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
    'sqlite3'
]

# Merge all
hidden_imports = base_hidden_imports + hiddenimports_mlx + hiddenimports_mlx_lm + hiddenimports_funasr + hiddenimports_chromadb
all_datas = datas_mlx + datas_mlx_lm + datas_funasr + datas_chromadb + [
    ('config', 'config'),      
    ('core', 'core'),          
    ('abilities', 'abilities') 
]
all_binaries = binaries_mlx + binaries_mlx_lm + binaries_funasr + binaries_chromadb

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
