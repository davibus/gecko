import sys
from pathlib import Path
import unittest
from unittest.mock import patch, Mock
from types import SimpleNamespace
from httplib2 import Response
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from google_sheets_requests import SheetsRequest
from googleapiclient.errors import HttpError


class SheetsBackoffTests(unittest.TestCase):
    def test_response_count_excludes_timestamp_cells(self):
        from google_tracker import GoogleTracker
        tracker = object.__new__(GoogleTracker)
        tracker.config = SimpleNamespace(spreadsheet_id="test")
        tracker.api = Mock()
        tracker.scout = Mock(side_effect=[
            SimpleNamespace(headers={"Response": 1}, rows=[(2, {"Response":""})]),
            SimpleNamespace(rows=[(2, {"Response":"Reply", "Last Updated":"now"})]),
        ])
        tracker._prepare_writes = Mock(return_value=([{"range":"test", "values":[["Reply"]]}],
            {(2,"Response"):"Reply", (2,"Last Updated"):"now"}))
        self.assertEqual(tracker.update_response_rows({2:"Reply"}), [2])

    def request(self, method="GET"):
        return SheetsRequest(None, lambda response, content: content,
                             "https://sheets.googleapis.com/test", method=method)

    @patch("google_sheets_requests.time.sleep")
    def test_read_retries_and_returns_verified_response(self, sleep):
        error = HttpError(Response({"status":"429"}), b'quota')
        with patch("googleapiclient.http.HttpRequest.execute", side_effect=[error, {"rows":[]}]) as execute:
            self.assertEqual(self.request().execute(), {"rows":[]})
        self.assertEqual(execute.call_count, 2)
        sleep.assert_called_once_with(60)

    @patch("google_sheets_requests.time.sleep")
    def test_mutation_is_never_replayed(self, sleep):
        error = HttpError(Response({"status":"429"}), b'quota')
        with patch("googleapiclient.http.HttpRequest.execute", side_effect=error) as execute:
            with self.assertRaises(HttpError):
                self.request("POST").execute()
        self.assertEqual(execute.call_count, 1)
        sleep.assert_not_called()

    @patch("google_sheets_requests.time.sleep")
    def test_persistent_quota_failure_is_bounded(self, sleep):
        error = HttpError(Response({"status":"429"}), b'quota')
        with patch("googleapiclient.http.HttpRequest.execute", side_effect=error) as execute:
            with self.assertRaises(HttpError):
                self.request().execute()
        self.assertEqual(execute.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
