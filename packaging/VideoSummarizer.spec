# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs, collect_submodules
from pathlib import Path

project_root = Path(SPECPATH).parent
datas = [
    (str(project_root / "examples"), "examples"),
    (str(project_root / "frontend_dist"), "frontend_dist"),
    (str(project_root / "vendor" / "whispercpp" / "runtime"), "whispercpp"),
    (str(project_root / "THIRD_PARTY_NOTICES.md"), "."),
    (str(project_root / "LICENSE"), "."),
    (str(project_root / "vendor" / "licenses"), "licenses"),
]
binaries = []
hiddenimports = collect_submodules("yt_dlp.extractor")
for package in ("av",):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

analysis = Analysis(
    [str(project_root / "backend" / "videosummarizer" / "launcher.py")], pathex=[str(project_root / "backend")], binaries=binaries, datas=datas,
    hiddenimports=hiddenimports + ["uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto", "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on"],
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=["torch", "tensorflow", "faster_whisper", "ctranslate2", "onnxruntime"], noarchive=False, optimize=1,
)
pyz = PYZ(analysis.pure)
exe = EXE(pyz, analysis.scripts, [], exclude_binaries=True, name="VideoSummarizer", debug=False, bootloader_ignore_signals=False, strip=False, upx=True, console=False, disable_windowed_traceback=False, argv_emulation=False, target_arch=None, codesign_identity=None, entitlements_file=None)
coll = COLLECT(exe, analysis.binaries, analysis.datas, strip=False, upx=True, upx_exclude=[], name="VideoSummarizer")
