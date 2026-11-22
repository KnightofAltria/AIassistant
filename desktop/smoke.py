"""Opt-in real WKWebView smoke test; only use with a disposable --data-dir."""
from __future__ import annotations
import json
from pathlib import Path
import threading
import time


def run_check(window, runtime, bridge, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    bridge._save_directory = output  # Every test export remains in the disposable evidence directory.
    checks = []

    def wait(script):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if window.evaluate_js("Boolean(" + script + ")"):
                return
            time.sleep(0.15)
        raise AssertionError("WebKit predicate timed out: " + script)

    def record(name):
        checks.append({"name": name, "passed": True})
        (output / "progress.json").write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding="utf-8")

    def snapshot(name):
        from PyObjCTools import AppHelper
        import AppKit
        from webview.platforms.cocoa import BrowserView
        complete = threading.Event()
        error = []

        def capture():
            def done(image, err):
                try:
                    if err or image is None:
                        raise RuntimeError(str(err))
                    bitmap = AppKit.NSBitmapImageRep.imageRepWithData_(image.TIFFRepresentation())
                    png = bitmap.representationUsingType_properties_(AppKit.NSPNGFileType, {})
                    png.writeToFile_atomically_(str(output / name), True)
                except Exception as exc:
                    error.append(str(exc))
                finally:
                    complete.set()
            BrowserView.instances[window.uid].webview.takeSnapshotWithConfiguration_completionHandler_(None, done)
        # Allow CSS entrance animations to paint before requesting a WK snapshot.
        time.sleep(0.5)
        AppHelper.callAfter(capture)
        assert complete.wait(15), "Snapshot timeout"
        assert not error, error

    try:
        assert runtime.root.name.startswith("csla-desktop-"), "Use a disposable test directory."
        wait("window.pywebview?.api && window.CSLA_DESKTOP && "
             "!document.getElementById('entry-choice').classList.contains('hidden') && "
             "!document.getElementById('entry-user').textContent.includes('正在检查')")
        assert window.evaluate_js("Object.keys(window.pywebview.api).sort()") == ["open_external", "save_file"]
        record("Only file-save and external-link bridge methods exposed")
        window.evaluate_js("document.getElementById('entry-switch').click()")
        wait("!document.getElementById('auth').classList.contains('hidden')")
        snapshot("01-登录.png")
        record("Native window rendered login form")
        body = {"username": "webkit_test", "password": "Desktop12345", "nickname": "桌面验收"}
        # Create only a disposable local account. The actual form below verifies login/reload.
        try:
            with runtime.request("/api/auth/register", body) as response:
                json.load(response)
        except Exception:
            with runtime.request("/api/auth/login", body):
                pass
        window.evaluate_js("document.getElementById('auth-username').value='webkit_test';"
                           "document.getElementById('auth-password').value='Desktop12345';"
                           "document.getElementById('auth-form').requestSubmit();")
        wait("!document.getElementById('gate').classList.contains('hidden') && window.pywebview?.api")
        record("Login submitted through real WebKit form and page reloaded")
        window.evaluate_js("document.getElementById('desktop-browse').click()")
        wait("!document.getElementById('app').classList.contains('hidden') && state.view==='home'")
        snapshot("02-首页.png")
        record("Entered full desktop home without API Key")
        for view in ("materials", "study", "dashboard", "profile"):
            window.evaluate_js(f"switchView({json.dumps(view)})")
            wait(f"state.view==={json.dumps(view)} && !document.getElementById('view-{view}').classList.contains('hidden')")
            record(f"Rendered {view} view")
            snapshot(f"03-{view}.png")
        # Real native panels are opened and cancelled using their own AppKit API.
        import webview
        from PyObjCTools import AppHelper
        import AppKit
        import Foundation

        def cancel_panel(result, target=None):
            deadline = time.monotonic() + 10
            def schedule(func):
                # Default-mode delayed selectors pause inside NSSavePanel.runModal().
                # Dispatch explicitly into its modal run-loop mode.
                runner = AppHelper.PyObjCMessageRunner.alloc().initWithPayload_((func, (), {}))
                runner.performSelectorOnMainThread_withObject_waitUntilDone_modes_(
                    runner.scheduleCallWithDelay_, None, False,
                    [Foundation.NSDefaultRunLoopMode, AppKit.NSModalPanelRunLoopMode])
            def inspect():
                panel = AppKit.NSApplication.sharedApplication().modalWindow()
                panels = [panel] if panel else []
                panels += list(AppKit.NSApplication.sharedApplication().windows())
                panel = next((p for p in panels if p.isKindOfClass_(AppKit.NSSavePanel)), None)
                if panel:
                    result.update(title=str(panel.title()), panel=type(panel).__name__)
                    if target:
                        panel.setDirectoryURL_(Foundation.NSURL.fileURLWithPath_(str(target.parent)))
                        panel.setNameFieldStringValue_(target.name)
                        def accept():
                            result["selected"] = str(panel.filename())
                            AppKit.NSApplication.sharedApplication().stopModalWithCode_(
                                AppKit.NSFileHandlingPanelOKButton)
                        timer = threading.Timer(0.4, lambda: schedule(accept))
                        timer.daemon = True
                        timer.start()
                    else:
                        panel.cancel_(None)
                    return
                if time.monotonic() < deadline:
                    timer = threading.Timer(0.1, lambda: schedule(inspect))
                    timer.daemon = True
                    timer.start()
                else:
                    result["error"] = "Native panel was not observed"
                    AppKit.NSApplication.sharedApplication().abortModal()
            timer = threading.Timer(0.3, lambda: schedule(inspect))
            timer.daemon = True
            timer.start()

        for kind in (webview.FileDialog.OPEN, webview.FileDialog.SAVE):
            observed = {}
            cancel_panel(observed)
            value = window.create_file_dialog(kind, save_filename="CSLA桌面验收.docx")
            assert observed and not observed.get("error") and not value, observed
            record(f"Native {observed['panel']} opened and cancelled")
        # The native bridge handles cancellation for the real generated Word report.
        observed = {}
        cancel_panel(observed)
        result = bridge.save_file("/api/export/report")
        assert result.get("cancelled") and observed, result
        record("Protected Word export reached native save panel and cancel preserved page")
        snapshot("04-导出后页面.png")
        target = output / runtime.attachment("/api/export/report")[0]
        target.unlink(missing_ok=True)
        observed = {}
        cancel_panel(observed, target)
        result = bridge.save_file("/api/export/report")
        assert result.get("ok") and target.exists(), result
        import zipfile
        with zipfile.ZipFile(target) as archive:
            assert "word/document.xml" in archive.namelist()
        record("Protected Word report saved through real native save panel and DOCX verified")
        window.load_url(runtime.url)
        wait("!document.getElementById('entry-choice').classList.contains('hidden') && "
             "document.getElementById('entry-user').textContent.includes('webkit_test')")
        window.evaluate_js("document.getElementById('entry-default').click()")
        wait("!document.getElementById('gate').classList.contains('hidden') && "
             "document.getElementById('entry-choice').classList.contains('hidden')")
        window.evaluate_js("document.getElementById('desktop-browse').click()")
        wait("!document.getElementById('app').classList.contains('hidden')")
        record("Reload restored local login and default-account entry remained usable")
        report = {"passed": True, "renderer": "WKWebView", "checks": checks}
    except Exception as exc:
        details = window.evaluate_js("({url:location.href, text:document.body.innerText,"
            "bridgeKeys:Object.keys(window.pywebview||{}), apiKeys:Object.keys(window.pywebview?.api||{}),"
            "panels:['entry-choice','auth','gate','app'].map(id=>({id,hidden:document.getElementById(id)?.classList.contains('hidden')}))})")
        snapshot("failure.png")
        report = {"passed": False, "error": str(exc), "checks": checks, "details": details}
    finally:
        (output / "webkit-check.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        window.destroy()
