import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import verify_course_catalog as verifier


def catalog_entry(**overrides):
    entry = {
        "id": "provider-course",
        "title": "Practical AI Course",
        "provider": "Provider",
        "url": "https://example.com/course",
        "skills": ["ai literacy"],
        "level": "beginner",
        "format": "course",
        "cost_type": "free",
        "cost_note": "Free",
        "time_hours": 3,
        "language": "English",
        "last_verified": "2026-07-19",
    }
    entry.update(overrides)
    return entry


class FakeResponse:
    def __init__(
        self,
        body=b"<html><title>Practical AI Course - Provider</title></html>",
        status=200,
        url="https://example.com/course",
    ):
        self.body = body
        self.status = status
        self.url = url
        self.headers = {"Content-Type": "text/html; charset=utf-8"}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, size=-1):
        return self.body[:size]

    def getcode(self):
        return self.status

    def geturl(self):
        return self.url


class CourseVerifierTests(unittest.TestCase):
    def write_catalog(self, entries):
        handle = tempfile.NamedTemporaryFile("w", delete=False, suffix=".json", encoding="utf-8")
        with handle:
            json.dump(entries, handle)
        return Path(handle.name)

    def test_offline_validates_schema_without_network(self):
        path = self.write_catalog([catalog_entry()])

        with patch.object(verifier.urllib.request, "urlopen") as urlopen:
            report = verifier.verify_catalog(path, offline=True)

        self.assertTrue(report["valid"])
        self.assertEqual(report["summary"]["total"], 1)
        urlopen.assert_not_called()

    def test_missing_required_field_fails(self):
        entry = catalog_entry()
        del entry["title"]
        path = self.write_catalog([entry])

        report = verifier.verify_catalog(path, offline=True)

        self.assertFalse(report["valid"])
        self.assertIn("missing required field: title", report["entries"][0]["errors"])

    def test_non_https_url_fails(self):
        path = self.write_catalog([catalog_entry(url="http://example.com/course")])

        report = verifier.verify_catalog(path, offline=True)

        self.assertFalse(report["valid"])
        self.assertIn("url must be HTTPS", report["entries"][0]["errors"])

    def test_duplicate_ids_fail(self):
        path = self.write_catalog([catalog_entry(), catalog_entry(title="Other")])

        report = verifier.verify_catalog(path, offline=True)

        self.assertFalse(report["valid"])
        self.assertIn("duplicate id", report["entries"][1]["errors"])

    def test_online_validation_records_status_redirect_and_title(self):
        path = self.write_catalog([catalog_entry()])

        with patch.object(
            verifier.urllib.request,
            "urlopen",
            return_value=FakeResponse(url="https://example.com/final"),
        ) as urlopen:
            report = verifier.verify_catalog(path, offline=False, timeout=1)

        self.assertTrue(report["valid"])
        self.assertEqual(report["entries"][0]["http"]["status"], 200)
        self.assertTrue(report["entries"][0]["http"]["redirected"])
        self.assertEqual(report["entries"][0]["http"]["page_title"], "Practical AI Course - Provider")
        urlopen.assert_called_once()

    def test_online_http_error_fails(self):
        path = self.write_catalog([catalog_entry()])

        with patch.object(verifier.urllib.request, "urlopen", return_value=FakeResponse(status=500)):
            report = verifier.verify_catalog(path, offline=False, timeout=1)

        self.assertFalse(report["valid"])
        self.assertIn("unexpected HTTP status: 500", report["entries"][0]["errors"])

    def test_title_mismatch_is_reported_as_warning_not_catalog_rewrite(self):
        path = self.write_catalog([catalog_entry()])
        before = path.read_text(encoding="utf-8")

        with patch.object(
            verifier.urllib.request,
            "urlopen",
            return_value=FakeResponse(body=b"<html><title>Different Topic</title></html>"),
        ):
            report = verifier.verify_catalog(path, offline=False, timeout=1)

        self.assertTrue(report["valid"])
        self.assertIn("page title differs from catalog title", report["entries"][0]["warnings"])
        self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_main_outputs_json_and_nonzero_for_invalid_catalog(self):
        path = self.write_catalog([catalog_entry(url="ftp://example.com/course")])
        output = io.StringIO()

        with patch("sys.stdout", output):
            exit_code = verifier.main(["--offline", str(path)])

        self.assertEqual(exit_code, 1)
        parsed = json.loads(output.getvalue())
        self.assertFalse(parsed["valid"])


if __name__ == "__main__":
    unittest.main()
