"""Temporary native-runtime harness for browser checks, never uses user data."""
import json
import signal
import sys
import tempfile
import threading
from pathlib import Path

repo = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(repo / "android/app/src/main/python"),
                str(repo / "AIassistant-v4/AIassistant/app")]
import mobile_runtime


class FakeVault:
    def readKey(self):
        return ""
    def writeKey(self, value):
        raise RuntimeError("UI tests do not save model credentials")


done = threading.Event()
for sig in (signal.SIGINT, signal.SIGTERM):
    signal.signal(sig, lambda *_: done.set())
with tempfile.TemporaryDirectory(prefix="csla-mobile-ui-") as root:
    info = json.loads(mobile_runtime.start(root, FakeVault()))
    # Ephemeral loopback credential consumed by the test process, never printed
    # by test output and never copied into the deliverable.
    print(json.dumps(info), flush=True)
    done.wait()
    mobile_runtime._server.shutdown()
    mobile_runtime._server.server_close()
    import server
    server.STORE._store.conn.close()
