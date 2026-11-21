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
    value = ""
    def readKey(self):
        return self.value
    def writeKey(self, value):
        if "--fixtures" not in sys.argv:
            raise RuntimeError("UI tests do not save model credentials")
        self.value = value


done = threading.Event()
for sig in (signal.SIGINT, signal.SIGTERM):
    signal.signal(sig, lambda *_: done.set())
with tempfile.TemporaryDirectory(prefix="csla-mobile-ui-") as root:
    info = json.loads(mobile_runtime.start(root, FakeVault()))
    if "--fixtures" in sys.argv:
        import deepseek
        from test_full_migration import full_section
        def validate(client):
            return {"models": ["deepseek-chat"]}
        def stream(client, messages, **kwargs):
            content = messages[-1]["content"]
            if '"avoid_questions"' in content:
                sources = json.loads(content).get("sources") or []
                yield json.dumps([{"stem": "八位补码表示的最大整数是？",
                    "options": ["127", "128", "255", "256"], "answer": "A",
                    "explanation": "最高位为符号位。",
                    "citation_ids": [s["citation_id"] for s in sources[:1]]}], ensure_ascii=False)
            else:
                yield full_section()
            if kwargs.get("on_finish"):
                kwargs["on_finish"]("stop")
        def complete(client, messages, **kwargs):
            if "视频方向" in messages[-1]["content"]:
                return json.dumps([{"title": "补码原理", "platform": "哔哩哔哩",
                                   "keyword": "补码原理", "reason": "巩固概念"}], ensure_ascii=False)
            return "临时测试学习总结：理解位宽与补码表示范围，复习溢出条件。"
        deepseek.DeepSeekClient.validate = validate
        deepseek.DeepSeekClient.stream_chat = stream
        deepseek.DeepSeekClient.complete = complete
        deepseek.DeepSeekClient.chat_with_tools = lambda *a, **k: {"content": "临时测试管理指令已完成"}
    # Ephemeral loopback credential consumed by the test process, never printed
    # by test output and never copied into the deliverable.
    print(json.dumps(info), flush=True)
    done.wait()
    mobile_runtime._server.shutdown()
    mobile_runtime._server.server_close()
    import server
    server.STORE._store.conn.close()
