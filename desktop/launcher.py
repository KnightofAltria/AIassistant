"""Double-click launcher; no installed Python or separate server is required."""
from __future__ import annotations
import argparse
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import webbrowser

from runtime import AlreadyRunning, DesktopRuntime
from platform_support import activate_existing, alert, default_data_dir, open_folder


class DesktopBridge:
    def __init__(self, runtime):
        self._runtime = runtime
        self._window = None
        self._save_directory = Path.home() / "Downloads"

    def save_file(self, path):
        import webview
        try:
            name, data = self._runtime.attachment(path)
            selected = self._window.create_file_dialog(webview.FileDialog.SAVE,
                directory=str(self._save_directory), save_filename=name)
            if not selected:
                return {"cancelled": True}
            target = Path(selected[0] if isinstance(selected, (list, tuple)) else selected)
            fd, tmp = tempfile.mkstemp(prefix=".csla-export-", dir=target.parent)
            try:
                with os.fdopen(fd, "wb") as file:
                    file.write(data)
                os.replace(tmp, target)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            return {"ok": True, "name": target.name}
        except Exception as exc:
            logging.exception("File export failed")
            return {"error": str(exc)}

    def open_external(self, url):
        from urllib.parse import urlsplit
        if urlsplit(url).scheme not in ("https", "http"):
            return {"error": "不支持此链接"}
        if urlsplit(url).hostname in ("localhost", "127.0.0.1", "::1"):
            return {"error": "本地链接请在应用内打开"}
        webbrowser.open(url)
        return {"ok": True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=default_data_dir())
    parser.add_argument("--demo", action="store_true", help="Explicit offline test mode")
    parser.add_argument("--headless-check", action="store_true")
    parser.add_argument("--diagnostics-file", type=Path, help="Write private temporary UI-test metadata")
    parser.add_argument("--ui-check-dir", type=Path, help="Run WebKit smoke checks in a temporary test account")
    args = parser.parse_args([arg for arg in sys.argv[1:] if not arg.startswith("-psn_")])
    if args.ui_check_dir and sys.platform == "win32":
        parser.error("--ui-check-dir currently supports Cocoa only; use --headless-check on Windows.")
    os.umask(0o077)
    args.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    logging.basicConfig(filename=args.data_dir / "desktop.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", encoding="utf-8")
    try:
        runtime = DesktopRuntime(args.data_dir, args.demo)
    except AlreadyRunning as exc:
        if not args.headless_check:
            if not activate_existing():
                alert(str(exc))
        return 0
    except Exception:
        logging.exception("Startup failed")
        if not args.headless_check:
            alert("启动失败，请查看用户数据目录中的 desktop.log。")
        return 1
    try:
        if args.headless_check:
            with runtime.request("/") as response:
                assert b"/desktop.js" in response.read()
            with runtime.request("/api/state") as response:
                assert json.load(response)["auth"]["enabled"]
            print("CSLA frozen backend check: PASS")
            return 0
        if args.diagnostics_file:
            args.diagnostics_file.write_text(json.dumps({"url": runtime.url,
                "bootstrap_url": runtime.bootstrap_url}), encoding="utf-8")
            args.diagnostics_file.chmod(0o600)
        import webview
        from webview.menu import Menu, MenuAction
        webview.settings["ALLOW_DOWNLOADS"] = False
        webview.settings["ALLOW_FILE_URLS"] = False
        icon = None
        gui = "cocoa"
        if sys.platform == "win32":
            gui = "edgechromium"
            bundle = Path(__file__).resolve().parent.parent
            browser = bundle / "webview2"
            if not (browser / "msedgewebview2.exe").is_file():
                raise RuntimeError("WebView2 文件缺失，请重新解压完整 Windows 软件包。")
            webview.settings["WEBVIEW2_RUNTIME_PATH"] = str(browser)
            icon = str(bundle / "CSLA.ico")
        bridge = DesktopBridge(runtime)
        window = webview.create_window("CSLA 学习助手", runtime.bootstrap_url, js_api=bridge,
            width=1180, height=800, min_size=(900, 640), text_select=True)
        bridge._window = window
        window.events.closing += lambda: runtime.closed.set()
        # closed only signals cancellation; finally below performs service/DB cleanup.
        menu = [Menu("学习助手", [
            MenuAction("打开数据目录", lambda: open_folder(runtime.root)),
            MenuAction("刷新页面", lambda: window.evaluate_js("location.reload()")),
            MenuAction("关于学习助手", lambda: window.evaluate_js(
                "alert('CSLA 桌面版 0.2.0\\n账号与学习数据保存在本机；AI 功能需要 DeepSeek API Key。')"))
        ])]
        check = None
        if args.ui_check_dir:
            from smoke import run_check
            check = lambda: run_check(window, runtime, bridge, args.ui_check_dir)
        webview.start(func=check, gui=gui, private_mode=False,
                      storage_path=str(runtime.root / "webview"), menu=menu, icon=icon)
        return 0
    except Exception:
        logging.exception("Desktop window failed")
        alert("窗口启动失败，请查看 desktop.log。")
        return 1
    finally:
        runtime.stop()


if __name__ == "__main__":
    raise SystemExit(main())
