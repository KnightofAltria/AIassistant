"""Build a complete Windows x64 portable app on macOS/Linux/Windows.

Build tools: Python with Pillow, packaging and ziglang. Target dependency wheels
and the official Python/WebView2 archives must already exist in --work.
No application code, database, or model is run by this build script.
"""
from __future__ import annotations
import argparse
from email.parser import BytesParser
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import zipfile

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from PIL import Image

APP_MODULES = (
    "auth_client", "crawl", "curriculum", "deepseek", "extras", "lessons", "pdftext",
    "prompts", "rag", "references", "seed", "server", "store", "textbooks", "tools",
    "reindex",
)
WINDOWS = {
    "sys_platform": "win32", "os_name": "nt", "platform_system": "Windows",
    "platform_machine": "AMD64", "python_version": "3.13",
    "python_full_version": "3.13.17", "implementation_name": "cpython",
    "implementation_version": "3.13.17", "platform_python_implementation": "CPython",
    "extra": "",
}


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def run(*command, cwd=None):
    print("RUN", *map(str, command), flush=True)
    subprocess.run(list(map(str, command)), cwd=cwd, check=True)


def extract_zip(archive, destination, wheel=False):
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            path = PurePosixPath(info.filename)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError(f"Unsafe archive member: {info.filename}")
            if info.is_dir():
                continue
            if wheel and len(path.parts) > 2 and path.parts[0].endswith(".data"):
                if path.parts[1] not in ("purelib", "platlib"):
                    continue
                path = PurePosixPath(*path.parts[2:])
            target = destination.joinpath(*path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(info))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args()
    desktop = Path(__file__).resolve().parent
    source = desktop.parent / "AIassistant-v4/AIassistant"
    work, output = args.work.resolve(), args.output.resolve()
    bundle = output / "CSLA-Windows-x64"
    if bundle.exists():
        raise SystemExit(f"Output already exists: {bundle}")
    downloads, wheels = work / "downloads", work / "wheels"
    sources = json.loads((downloads / "runtime-sources.json").read_text())
    for name, entry in sources.items():
        path = downloads / name
        assert path.stat().st_size == entry["bytes"] and sha256(path) == entry["sha256"], name

    required = [Requirement(line) for line in
                (desktop / "requirements-windows.txt").read_text().splitlines()
                if line.strip() and not line.startswith("#")]
    packages, dependencies = {}, []
    archives = sorted(wheels.glob("*.whl"))
    for archive in archives:
        with zipfile.ZipFile(archive) as z:
            metadata = BytesParser().parsebytes(z.read(next(
                name for name in z.namelist() if name.endswith(".dist-info/METADATA"))))
        name = canonicalize_name(metadata["Name"])
        assert name not in packages, f"Duplicate wheel: {name}"
        packages[name] = {"version": metadata["Version"], "wheel": archive.name,
                          "sha256": sha256(archive)}
        dependencies.extend(Requirement(r) for r in metadata.get_all("Requires-Dist", []))
    for requirement in required + dependencies:
        if requirement.marker and not requirement.marker.evaluate(WINDOWS):
            continue
        package = packages.get(canonicalize_name(requirement.name))
        assert package and package["version"] in requirement.specifier, str(requirement)
    assert set(packages) == {canonicalize_name(r.name) for r in required}
    internal = bundle / "internal"
    python = internal / "python"
    python.mkdir(parents=True)
    extract_zip(downloads / "python-3.13.17-embed-amd64.zip", python)
    site = python / "Lib/site-packages"
    site.mkdir(parents=True)
    for archive in archives:
        extract_zip(archive, site, wheel=True)
    (python / "python313._pth").write_text(
        "python313.zip\n.\nLib/site-packages\n../desktop\n"
        "../AIassistant-v4/AIassistant/app\n../AIassistant-v4/AIassistant/auth_server\n"
        "import site\n", encoding="ascii")

    target_app = internal / "AIassistant-v4/AIassistant/app"
    target_app.mkdir(parents=True)
    for name in APP_MODULES:
        shutil.copy2(source / "app" / f"{name}.py", target_app)
    for name in ("static", "samples", "study_guides"):
        shutil.copytree(source / "app" / name, target_app / name,
                        ignore=shutil.ignore_patterns("__pycache__", ".DS_Store"))
    shutil.copy2(source / "app/reference_catalog.json", target_app)
    auth = internal / "AIassistant-v4/AIassistant/auth_server"
    auth.mkdir()
    shutil.copy2(source / "auth_server/auth_server.py", auth)
    (internal / "desktop").mkdir()
    for name in ("launcher.py", "runtime.py", "platform_support.py", "desktop.js",
                 "windows_diagnostics.py"):
        shutil.copy2(desktop / name, internal / "desktop")

    unpacked = work / "webview2-unpacked"
    browser = unpacked / "Microsoft.WebView2.FixedVersionRuntime.158.0.4370.33.x64"
    if not browser.exists():
        unpacked.mkdir(exist_ok=True)
        run("tar", "-xf", downloads / "webview2-x64.cab", "-C", unpacked)
    assert (browser / "msedgewebview2.exe").is_file()
    shutil.copytree(browser, internal / "webview2")

    icon = internal / "CSLA.ico"
    with Image.open(source / "app/static/assets/cs-logo-concept.png") as image:
        image.convert("RGBA").save(icon, format="ICO",
            sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)])
    build = work / "native"
    build.mkdir(exist_ok=True)
    shutil.copy2(icon, build / "CSLA.ico")
    manifest = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">'
        '<assemblyIdentity version="0.2.0.0" processorArchitecture="amd64" '
        'name="cn.csla.desktop" type="win32"/>'
        '<trustInfo xmlns="urn:schemas-microsoft-com:asm.v3"><security>'
        '<requestedPrivileges><requestedExecutionLevel level="asInvoker" uiAccess="false"/>'
        '</requestedPrivileges></security></trustInfo>'
        '<compatibility xmlns="urn:schemas-microsoft-com:compatibility.v1"><application>'
        '<supportedOS Id="{8e0f7a12-bfb3-4fe8-b9a5-48fd50a15a9a}"/>'
        '</application></compatibility></assembly>')
    (build / "CSLA.manifest").write_text(manifest, encoding="utf-8")
    resource = (
        '// CSLA Unicode resources.\n#pragma code_page(65001)\n'
        '1 ICON "CSLA.ico"\n1 24 "CSLA.manifest"\n'
        '1 VERSIONINFO\nFILEVERSION 0,2,0,0\nPRODUCTVERSION 0,2,0,0\n'
        'FILEOS 0x40004\nFILETYPE 1\nBEGIN\n'
        'BLOCK "StringFileInfo"\nBEGIN\nBLOCK "040904b0"\nBEGIN\n'
        'VALUE "FileDescription", "CSLA 学习助手 Windows 桌面版\\0"\n'
        'VALUE "FileVersion", "0.2.0\\0"\nVALUE "ProductName", "CSLA 学习助手\\0"\n'
        'VALUE "ProductVersion", "0.2.0\\0"\nVALUE "OriginalFilename", "CSLA.exe\\0"\n'
        'END\nEND\nBLOCK "VarFileInfo"\nBEGIN\n'
        'VALUE "Translation", 0x409, 1200\nEND\nEND\n')
    (build / "CSLA.rc").write_text(resource, encoding="utf-8")
    run(sys.executable, "-m", "ziglang", "rc", "/:auto-includes", "none",
        "/:target", "x86_64", "/fo", "CSLA.res", "CSLA.rc", cwd=build)
    run(sys.executable, "-m", "ziglang", "cc", "-target", "x86_64-windows-gnu",
        "-O2", "-g0", "-s", "-municode", "-Wl,--subsystem,windows", desktop / "windows_launcher.c",
        build / "CSLA.res", "-luser32", "-o", bundle / "CSLA.exe")
    (bundle / "运行自检.cmd").write_text(
        '@echo off\r\nchcp 65001 >nul\r\nset PYTHONUTF8=1\r\n'
        'set PYTHONNET_RUNTIME=netfx\r\n'
        '"%~dp0internal\\python\\python.exe" -B '
        '"%~dp0internal\\desktop\\windows_diagnostics.py"\r\n'
        'set "CSLA_CHECK_EXIT=%ERRORLEVEL%"\r\n'
        'echo.\r\necho 自检退出码：%CSLA_CHECK_EXIT% （0 为通过）\r\n'
        'echo 此检查不打开界面；请另行双击 CSLA.exe 验证窗口和操作。\r\n'
        'pause\r\nexit /b %CSLA_CHECK_EXIT%\r\n', encoding="utf-8")
    (bundle / "创建桌面快捷方式.ps1").write_text(
        "$ErrorActionPreference = 'Stop'\n"
        "$exe = Join-Path $PSScriptRoot 'CSLA.exe'\n"
        "$shell = New-Object -ComObject WScript.Shell\n"
        "$link = $shell.CreateShortcut((Join-Path "
        "[Environment]::GetFolderPath('Desktop') 'CSLA 学习助手.lnk'))\n"
        "$link.TargetPath = $exe\n$link.WorkingDirectory = $PSScriptRoot\n"
        "$link.IconLocation = \"$exe,0\"\n$link.Save()\n"
        "Write-Host '桌面快捷方式已创建。请保留当前软件目录。'\n",
        encoding="utf-8-sig")
    (bundle / "创建桌面快捷方式.cmd").write_text(
        '@echo off\r\nchcp 65001 >nul\r\npowershell.exe -NoProfile -ExecutionPolicy Bypass '
        '-File "%~dp0创建桌面快捷方式.ps1"\r\npause\r\n', encoding="utf-8")
    manifest = {"target": "Windows 10 22H2 / Windows 11 x64",
                "version": "0.2.0", "runtime_sources": sources, "packages": packages,
                "native_windows_tested": False,
                "python_license": "internal/python/LICENSE.txt",
                "package_licenses": "internal/python/Lib/site-packages/*.dist-info/",
                "webview2_terms": "https://go.microsoft.com/fwlink/p/?LinkId=2124703",
                "webview2_third_party_notices":
                    "internal/webview2/show_third_party_software_licenses.bat"}
    (bundle / "构建信息.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                                           encoding="utf-8")
    print(f"Built: {bundle}", flush=True)


if __name__ == "__main__":
    main()
