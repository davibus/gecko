from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import run_gecko


class GeckoCommandTests(unittest.TestCase):
    def test_failed_stage_stops_later_writes(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(run_gecko, "ROOT", Path(temp)), patch.object(
                run_gecko.subprocess, "run", return_value=SimpleNamespace(returncode=7)
            ) as process:
                self.assertEqual(run_gecko.main(), 7)
            self.assertEqual(process.call_count, 1)
            status = json.loads((Path(temp) / "reports/gecko-command/latest.json").read_text())
            self.assertEqual(status["status"], "failed")
            self.assertEqual(status["steps"][0]["exit_code"], 7)

    def test_duplicate_run_does_not_replace_active_status(self):
        @contextmanager
        def busy():
            raise OSError("already running")
            yield
        with tempfile.TemporaryDirectory() as temp:
            status = Path(temp) / "reports/gecko-command/latest.json"
            status.parent.mkdir(parents=True)
            status.write_text('{"status":"running","run_id":"original"}')
            with patch.object(run_gecko, "ROOT", Path(temp)), patch.object(run_gecko, "run_lock", busy), patch.object(
                run_gecko.subprocess, "run"
            ) as process:
                self.assertEqual(run_gecko.main(), 1)
            process.assert_not_called()
            self.assertEqual(json.loads(status.read_text())["run_id"], "original")


if __name__ == "__main__":
    unittest.main()
