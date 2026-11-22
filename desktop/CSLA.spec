# macOS arm64 bundle. Asset whitelist deliberately excludes all account/user data.
from pathlib import Path
root = Path(SPECPATH).parent
app = root / "AIassistant-v4/AIassistant/app"
desktop = root / "desktop"
datas = [(str(app / name), name) for name in ("static", "samples", "study_guides")]
datas.append((str(app / "reference_catalog.json"), "."))
datas.append((str(desktop / "desktop.js"), "."))
a = Analysis([str(desktop / "launcher.py")],
    pathex=[str(app), str(app.parent / "auth_server"), str(desktop)],
    binaries=[], datas=datas,
    hiddenimports=["server", "auth_server", "webview.platforms.cocoa", "certifi"],
    excludes=["tkinter", "PyQt5", "PyQt6", "PySide2", "PySide6", "webview.platforms.gtk",
              "webview.platforms.qt", "webview.platforms.winforms"],
    noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="CSLA",
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, target_arch="arm64", codesign_identity=None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="CSLA")
bundle = BUNDLE(coll, name="CSLA学习助手.app", icon=str(desktop / "CSLA.icns"),
    bundle_identifier="cn.csla.desktop",
    info_plist={"CFBundleShortVersionString": "0.2.0", "CFBundleVersion": "20261122",
        "NSHighResolutionCapable": True, "LSMinimumSystemVersion": "12.0",
        "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
        "NSHumanReadableCopyright": "CSLA 计算机课程学习助手"})
