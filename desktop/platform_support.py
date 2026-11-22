"""Small OS adapter shared by the macOS and Windows desktop launchers."""
from __future__ import annotations
import os
from pathlib import Path
import subprocess
import sys
import errno


class LockBusy(OSError):
    pass


class DataLock:
    def __init__(self, path):
        self.file = Path(path).open("a+b")
        try:
            if sys.platform == "win32":
                import msvcrt
                if self.file.seek(0, os.SEEK_END) == 0:
                    self.file.write(b"\0")
                    self.file.flush()
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.file.close()
            if exc.errno in (errno.EACCES, errno.EAGAIN):
                raise LockBusy("Another desktop instance owns this data directory.") from exc
            raise

    def release(self):
        if self.file.closed:
            return
        try:
            if sys.platform == "win32":
                import msvcrt
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_UN)
        finally:
            self.file.close()


def default_data_dir():
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData/Local")) / "CSLA Desktop"
    return Path.home() / "Library/Application Support/CSLA Desktop"


def open_folder(path):
    if sys.platform == "win32":
        os.startfile(str(path))
    else:
        subprocess.Popen(["/usr/bin/open", str(path)])


def alert(message):
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, "CSLA 学习助手", 0x10)
    else:
        from AppKit import NSAlert
        popup = NSAlert.alloc().init()
        popup.setMessageText_("CSLA 学习助手")
        popup.setInformativeText_(message)
        popup.addButtonWithTitle_("好")
        popup.runModal()


def activate_existing():
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        user32.FindWindowW.restype = wintypes.HWND
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        window = user32.FindWindowW(None, "CSLA 学习助手")
        if window:
            user32.ShowWindow(window, 9)
            user32.SetForegroundWindow(window)
            return True
        return False
    subprocess.run(["/usr/bin/open", "-b", "cn.csla.desktop"], check=False)
    return False
