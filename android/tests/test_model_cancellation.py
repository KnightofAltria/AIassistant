"""Transport cancellation checks use fake responses and no model calls."""
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "AIassistant-v4/AIassistant/app"))
import deepseek


class ModelCancellation(unittest.TestCase):
    def test_desktop_default_keeps_stream_and_completion_behavior(self):
        with patch.object(deepseek, "CANCELLATION_CHECK_FACTORY", None), \
             patch.object(deepseek, "MOCK", False):
            client = deepseek.DeepSeekClient("fake")
            response = io.BytesIO(b'data: {"choices":[{"delta":{"content":"hello"},"finish_reason":"stop"}]}\n'
                                  b'data: [DONE]\n')
            finishes = []
            with patch.object(client, "_request", return_value=response):
                self.assertEqual(list(client.stream_chat([], on_finish=finishes.append)), ["hello"])
            self.assertEqual(finishes, ["stop"])
            self.assertTrue(response.closed)

    def test_cancel_during_open_closes_response(self):
        cancelled = [False]
        def check():
            if cancelled[0]:
                raise deepseek.DeepSeekError("cancelled", 409, True)
        response = io.BytesIO(b"{}")
        def opened(*args, **kwargs):
            cancelled[0] = True
            return response
        with patch.object(deepseek, "CANCELLATION_CHECK_FACTORY", return_value=check), \
             patch.object(deepseek.urllib.request, "urlopen", side_effect=opened):
            client = deepseek.DeepSeekClient("fake")
            with self.assertRaises(deepseek.DeepSeekError):
                client._request("/models")
        self.assertTrue(response.closed)

    def test_synchronous_payload_cannot_return_after_background_transition(self):
        cancelled = [False]
        def check():
            if cancelled[0]:
                raise deepseek.DeepSeekError("cancelled", 409, True)
        class Response(io.BytesIO):
            def read(self, *args):
                result = super().read(*args)
                cancelled[0] = True
                return result
        with patch.object(deepseek, "CANCELLATION_CHECK_FACTORY", return_value=check), \
             patch.object(deepseek, "MOCK", False):
            for operation in ("complete", "chat_with_tools", "validate"):
                with self.subTest(operation=operation):
                    cancelled[0] = False
                    client = deepseek.DeepSeekClient("fake")
                    response = Response(b'{"choices":[{"message":{"content":"draft"}}],"data":[]}')
                    with patch.object(client, "_request", return_value=response):
                        with self.assertRaises(deepseek.DeepSeekError):
                            if operation == "chat_with_tools":
                                client.chat_with_tools([], [])
                            elif operation == "complete":
                                client.complete([])
                            else:
                                client.validate()
                    self.assertTrue(response.closed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
