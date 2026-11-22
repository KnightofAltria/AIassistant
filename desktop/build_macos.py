"""Build with the interpreter that installed requirements-macos.txt."""
from pathlib import Path
import argparse
import platform
import shutil
import subprocess
import sys


def run(*args):
    subprocess.run([str(arg) for arg in args], check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--work", type=Path, default=Path("/private/tmp/csla-desktop-packaging/build"))
    args = parser.parse_args()
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise SystemExit("This build requires macOS Apple Silicon.")
    desktop = Path(__file__).resolve().parent
    args.output.mkdir(parents=True, exist_ok=True)
    args.work.mkdir(parents=True, exist_ok=True)
    iconset = args.work / "CSLA.iconset"
    iconset.mkdir(exist_ok=True)
    logo = desktop.parent / "AIassistant-v4/AIassistant/app/static/assets/cs-logo-concept.png"
    for size in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            name = f"icon_{size}x{size}" + ("@2x" if scale == 2 else "") + ".png"
            run("/usr/bin/sips", "-z", size * scale, size * scale, logo, "--out", iconset / name)
    run("/usr/bin/iconutil", "-c", "icns", iconset, "-o", desktop / "CSLA.icns")
    run(sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--distpath", args.work / "dist", "--workpath", args.work / "pyinstaller",
        desktop / "CSLA.spec")
    built = args.work / "dist/CSLA学习助手.app"
    target = args.output / built.name
    if target.exists():
        shutil.rmtree(target)
    run("/usr/bin/ditto", built, target)
    run("/usr/bin/codesign", "--verify", "--deep", "--strict", target)
    print(f"Built: {target}")


if __name__ == "__main__":
    main()
