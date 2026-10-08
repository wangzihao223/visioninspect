# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_dynamic_libs

datas = [('E:/work/模型评估/VisionInspect/examples', 'examples')]
binaries = []
datas += collect_data_files('imgui_bundle')
binaries += collect_dynamic_libs('imgui_bundle')


a = Analysis(
    ['E:/work/模型评估/desktop/entry.py'],
    pathex=['E:/work/模型评估/VisionInspect'],
    binaries=binaries,
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PySide6', 'PyQt6', 'PyQt5', 'torch', 'torchvision', 'ultralytics', 'matplotlib', 'pandas', 'scipy', 'cv2', 'IPython', 'notebook', 'jupyterlab', 'pytest', 'pyodide', 'js'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='VisionInspect',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='VisionInspect',
)
