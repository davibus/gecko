from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import run_gecko


class GeckoCommandTests(unittest.TestCase):
    def test_selected_run_never_dispatches_broad_discovery(self):
        ids=list(range(2555,2569))
        with tempfile.TemporaryDirectory() as temp, patch.object(run_gecko,'ROOT',Path(temp)), patch.object(run_gecko.subprocess,'run',return_value=SimpleNamespace(returncode=0)) as process:
            self.assertEqual(run_gecko.main(ids),0)
            commands=[c.args[0] for c in process.call_args_list]
            self.assertNotIn('gecko_daily.py',[Path(c[2]).name for c in commands])
            selected=[c for c in commands if Path(c[2]).name=='selected_daily.py']
            self.assertEqual([c[3] for c in selected],['preflight','resumes','responses'])
            for command in selected:self.assertEqual(command[4:],['--ids',*map(str,ids)])
            for call in process.call_args_list:
                self.assertEqual(call.kwargs['env']['GECKO_ALLOWED_JOB_IDS'],','.join(map(str,ids)))
            status=json.loads((Path(temp)/'reports/gecko-command/latest.json').read_text())
            self.assertEqual(status['job_ids'],ids)
            self.assertEqual(status['status'],'complete')

    def test_selected_preflight_failure_blocks_resume_and_export(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(run_gecko,'ROOT',Path(temp)), patch.object(run_gecko.subprocess,'run',return_value=SimpleNamespace(returncode=1)) as process:
            self.assertEqual(run_gecko.main([2555]),1)
            self.assertEqual(process.call_count,1)

    def test_partial_daily_failure_still_refreshes_tracker_and_report(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(run_gecko, "ROOT", Path(temp)), patch.object(
                run_gecko.subprocess, "run", side_effect=[SimpleNamespace(returncode=code) for code in (0, 7, 0, 0, 0)]
            ) as process:
                self.assertEqual(run_gecko.main(), 7)
            self.assertEqual(process.call_count, 4)
            status = json.loads((Path(temp) / "reports/gecko-command/latest.json").read_text())
            self.assertEqual(status["status"], "failed")
            self.assertEqual(len(status["steps"]), 4)

    def test_full_run_does_not_export_to_sheets(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(run_gecko, 'ROOT', Path(temp)), patch.object(
                run_gecko.subprocess,'run',return_value=SimpleNamespace(returncode=0)) as process:
                self.assertEqual(run_gecko.main(),0)
            commands=[call.args[0] for call in process.call_args_list]
            self.assertEqual([Path(command[2]).name for command in commands],
                ['daily_report.py','gecko_daily.py','sync_gecko_local.py','daily_report.py'])
            self.assertIn('--apply',commands[1])
            self.assertNotIn('--resume-ids',commands[1])
            self.assertEqual(json.loads((Path(temp)/'reports/gecko-command/latest.json').read_text())['status'],'complete')

    def test_automatic_export_entrypoint_does_not_touch_sheets(self):
        import export_sqlite_tracker
        with patch.object(export_sqlite_tracker,'export_sheet') as export:
            self.assertEqual(export_sqlite_tracker.main(),0)
            export.assert_not_called()

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
