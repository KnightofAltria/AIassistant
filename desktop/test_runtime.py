"""Temporary-root integration checks. No real accounts or model calls."""
import base64
import io
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error
import urllib.request
import zipfile

from runtime import AlreadyRunning, DesktopRuntime


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="csla-desktop-test-")
        self.root = Path(self.temp.name)
        self.runtime = DesktopRuntime(self.root)

    def tearDown(self):
        self.runtime.stop()
        self.temp.cleanup()

    def call(self, path, body=None):
        with self.runtime.request(path, body) as resp:
            return json.load(resp)

    def register_login(self, name="desktop_test"):
        body = {"username": name, "password": "Desktop12345", "nickname": "桌面验收"}
        user = self.call("/api/auth/register", body)
        self.call("/api/auth/login", body)
        return user

    def assert_forbidden(self, req):
        with self.assertRaises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(req, timeout=3)
        self.assertEqual(err.exception.code, 403)
        err.exception.close()

    def test_local_gate_and_bootstrap(self):
        self.assert_forbidden(self.runtime.url + "/api/state")
        self.assert_forbidden(self.runtime.url + "/")
        request = urllib.request.Request(self.runtime.url + "/api/state",
            headers={"Cookie": "csla_desktop=" + self.runtime.cookie_token, "Origin": "https://example.com"})
        self.assert_forbidden(request)
        request = urllib.request.Request(self.runtime.url + "/api/state",
            headers={"Cookie": "csla_desktop=" + self.runtime.cookie_token, "Host": "example.com"})
        self.assert_forbidden(request)
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
        with opener.open(self.runtime.bootstrap_url) as response:
            self.assertIn(b"/desktop.js", response.read())
        self.assert_forbidden(self.runtime.bootstrap_url)
        with opener.open(self.runtime.url + "/api/state") as response:
            self.assertFalse(json.load(response)["auth"]["logged_in"])
        self.assert_forbidden(self.runtime.app.AUTH.base_url + "/auth/health")

    def test_registration_permissions_and_restore(self):
        self.register_login()
        state = self.call("/api/state")
        self.assertTrue(state["auth"]["is_admin"])
        second = self.call("/api/auth/register", {"username": "second_test", "password": "Desktop12345"})
        self.assertEqual(second["user"]["role"], "student")
        self.assertFalse(self.call("/api/state")["auth"]["is_admin"])
        self.call("/api/auth/login", {"username": "desktop_test", "password": "Desktop12345"})
        self.assertTrue((self.root / "learning/session.json").exists())
        old_url = self.runtime.url
        self.runtime.stop()
        self.runtime = DesktopRuntime(self.root)
        self.assertNotEqual(old_url, self.runtime.url)
        state = self.call("/api/state")
        self.assertTrue(state["auth"]["logged_in"])
        self.assertEqual(state["auth"]["user"]["username"], "desktop_test")
        self.call("/api/auth/logout", {})
        self.assertFalse(self.call("/api/state")["auth"]["logged_in"])
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.runtime.request("/api/materials")
        self.assertEqual(error.exception.code, 401)
        error.exception.close()

    def test_documents_and_offline_modules(self):
        self.register_login()
        for path in ("/api/subjects", "/api/materials", "/api/dashboard", "/api/profile",
                     "/api/review", "/api/graph", "/api/activity", "/api/admin/users"):
            self.assertIsInstance(self.call(path), dict)
        raw = io.BytesIO()
        with zipfile.ZipFile(raw, "w") as archive:
            archive.writestr("[Content_Types].xml",
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
            archive.writestr("word/document.xml",
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:body><w:p><w:r><w:t>Desktop document import test.</w:t></w:r></w:p></w:body></w:document>')
        body = {"filename": "测试资料.docx", "content": base64.b64encode(raw.getvalue()).decode()}
        imported = self.call("/api/materials/import", body)
        mid = imported["material"]["id"]
        filename, source = self.runtime.attachment(f"/api/materials/{mid}/source?download=1")
        self.assertTrue(filename.endswith(".docx"))
        self.assertEqual(source, raw.getvalue())
        text = b"BT /F1 12 Tf 72 720 Td (Desktop PDF import test. Operating systems manage processes and memory.) Tj ET"
        objects = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
            b"<< /Length " + str(len(text)).encode() + b" >>\nstream\n" + text + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
        ]
        pdf = bytearray(b"%PDF-1.4\n")
        offsets = [0]
        for index, obj in enumerate(objects, 1):
            offsets.append(len(pdf))
            pdf.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
        xref = len(pdf)
        pdf.extend(b"xref\n0 6\n0000000000 65535 f \n")
        for offset in offsets[1:]:
            pdf.extend(f"{offset:010} 00000 n \n".encode())
        pdf.extend(f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
        imported_pdf = self.call("/api/materials/import",
            {"filename": "Desktop.pdf", "content": base64.b64encode(pdf).decode()})
        self.assertEqual(imported_pdf["pages"], 1)
        self.assertGreater(imported_pdf["chars"], 40)
        _, source_pdf = self.runtime.attachment(
            f"/api/materials/{imported_pdf['material']['id']}/source?download=1")
        self.assertEqual(source_pdf, bytes(pdf))
        filename, report = self.runtime.attachment("/api/export/report")
        self.assertTrue(filename.endswith(".docx"))
        with zipfile.ZipFile(io.BytesIO(report)) as archive:
            self.assertIn("word/document.xml", archive.namelist())
        self.assertFalse(self.call("/api/state")["configured"])
        for url in ("https://example.com/", "//example.com/", "/api/state", "/api/export/report?url=bad"):
            with self.assertRaises(ValueError):
                self.runtime.attachment(url)

    def test_single_instance_cleanup(self):
        with self.assertRaises(AlreadyRunning):
            DesktopRuntime(self.root)
        services = list(self.runtime.services)
        self.runtime.closed.set()  # Native closing event must still release resources.
        self.runtime.stop()
        self.assertTrue(all(service.socket.fileno() == -1 for service in services))
        self.runtime = DesktopRuntime(self.root)
        self.assertFalse(self.runtime.closed.is_set())


if __name__ == "__main__":
    unittest.main(verbosity=2)
