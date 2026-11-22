"""User-invoked Windows check; only temporary accounts/data, no model calls."""
from __future__ import annotations
import ctypes
import json
import os
from pathlib import Path
import platform
import sys
import tempfile
import traceback


def main():
    result = {"platform": platform.platform(), "python": sys.version,
              "checks": [], "native_window_tested": False}
    try:
        assert sys.platform == "win32" and platform.machine().upper() in ("AMD64", "X86_64")
        root = Path(__file__).resolve().parents[1]
        os.environ["PYTHONNET_RUNTIME"] = "netfx"
        import clr
        clr.AddReference("System.Windows.Forms")
        from webview.util import interop_dll_path
        for name in ("Microsoft.Web.WebView2.Core.dll", "Microsoft.Web.WebView2.WinForms.dll"):
            clr.AddReference(interop_dll_path(name))
        ctypes.WinDLL(str(Path(interop_dll_path("win-x64")) / "WebView2Loader.dll"))
        assert (root / "webview2/msedgewebview2.exe").is_file()
        result["checks"].append(".NET / WinForms / WebView2 loader import")
        from runtime import DesktopRuntime
        with tempfile.TemporaryDirectory(prefix="csla-windows-check-") as data:
            runtime = DesktopRuntime(Path(data), demo=True)
            try:
                with runtime.request("/") as response:
                    assert b"/desktop.js" in response.read()
                with runtime.request("/api/state") as response:
                    assert json.load(response)["auth"]["enabled"]
                result["checks"].append("temporary local learning / account services")
            finally:
                runtime.stop()
        result["passed"] = True
    except Exception:
        result["passed"] = False
        result["error"] = traceback.format_exc()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
