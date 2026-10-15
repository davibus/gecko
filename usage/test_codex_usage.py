import json
from pathlib import Path
import tempfile
import unittest

import codex_usage as usage


def record(kind, subtype, stamp, **payload):
    return {"timestamp": stamp, "type": kind, "payload": {"type": subtype, **payload}}


class CollectorTests(unittest.TestCase):
    def make_log(self, path, cwd=None, complete=True):
        cwd = cwd or str(Path(__file__).resolve().parents[1])
        events = [
            record("session_meta", None, "2026-10-11T10:00:00Z", id=path.stem, cwd=cwd,
                   source="vscode", git={"branch": "main"}),
            record("event_msg", "task_started", "2026-10-11T10:00:00Z", turn_id="turn-1", started_at=1791712800),
            record("turn_context", None, "2026-10-11T10:00:01Z", turn_id="turn-1", model="gpt-test", effort="medium"),
            record("response_item", "message", "2026-10-11T10:00:02Z", role="user", content=[{"type":"input_text","text":"Build usage report"}]),
            record("event_msg", "token_count", "2026-10-11T10:00:03Z", info={"total_token_usage":{"input_tokens":10,"cached_input_tokens":3,"output_tokens":2,"reasoning_output_tokens":1,"total_tokens":12}}),
            record("event_msg", "token_count", "2026-10-11T10:00:04Z", info={"total_token_usage":{"input_tokens":15,"cached_input_tokens":4,"output_tokens":4,"reasoning_output_tokens":1,"total_tokens":19}}),
        ]
        if complete:
            events.append(record("event_msg", "task_complete", "2026-10-11T10:01:00Z", turn_id="turn-1", completed_at=1791712860))
        path.write_text("\n".join(json.dumps(x) for x in events) + "\n", encoding="utf-8")

    def test_parse_counter_delta_and_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "session.jsonl"
            self.make_log(path)
            rows = usage.parse_rollout(path)
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual((row["input_tokens"], row["total_tokens"]), (15, 19))
            self.assertEqual(row["duration_seconds"], 60)
            self.assertEqual(row["status"], "completed")
            self.assertEqual(row["description"], "Build usage report")
            self.assertEqual(row["git_branch"], "main")
            self.assertIsNone(row["terminal_name"])

    def test_parallel_sessions_deduplicate_and_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "sessions"
            day = usage.dt.datetime.now(usage.DENVER).strftime("%Y/%m/%d")
            target = root / day
            target.mkdir(parents=True)
            first, second = target / "a.jsonl", target / "b.jsonl"
            self.make_log(first, complete=False)
            self.make_log(second)
            db = usage.connect(Path(folder) / "ledger.sqlite3")
            self.assertEqual(usage.scan(db, root, 1), 2)
            self.assertEqual(usage.scan(db, root, 1), 0)
            self.make_log(first, complete=True)
            self.assertEqual(usage.scan(db, root, 1), 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM tasks WHERE status='completed'").fetchone()[0], 2)
            db.close()

    def test_other_checkout_is_included_and_secret_is_redacted(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "session.jsonl"
            self.make_log(path, cwd=r"G:\My Drive\projects\gecko\gecko_main_other")
            self.assertEqual(usage.parse_rollout(path)[0]["working_directory"], r"G:\My Drive\projects\gecko\gecko_main_other")
            self.assertEqual(usage.short_description("token=abc123 do work"), "token=[REDACTED] do work")
            self.assertEqual(usage.short_description("## Referenced ChatGPT conversation:\nold context\n## My request:\nTrack usage"), "Track usage")
            self.assertEqual(usage.short_description('Track usage <image name="Screenshot" path="C:\\Temp\\private.png"></image>'), "Track usage")
            self.assertIsNone(usage.text_from_user({"type":"message","role":"user","content":[{"type":"input_text","text":"<external_codex_apps_open_page>{}\u003c/external_codex_apps_open_page>"}]}))

    def test_second_turn_uses_prior_cumulative_baseline_and_partial_tail(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "session.jsonl"
            self.make_log(path)
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record("event_msg", "task_started", "2026-10-11T10:02:00Z", turn_id="turn-2")) + "\n")
                stream.write(json.dumps(record("event_msg", "token_count", "2026-10-11T10:02:05Z", info={"total_token_usage":{"input_tokens":20,"cached_input_tokens":6,"output_tokens":6,"reasoning_output_tokens":2,"total_tokens":26}})) + "\n")
                stream.write(json.dumps(record("event_msg", "turn_aborted", "2026-10-11T10:02:06Z", turn_id="turn-2")) + "\n")
                stream.write('{"timestamp":')
            rows = usage.parse_rollout(path)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[1]["input_tokens"], 5)
            self.assertEqual(rows[1]["total_tokens"], 7)
            self.assertEqual(rows[1]["status"], "interrupted")

    def test_fast_mode_uses_settings_applied_before_each_turn(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "session.jsonl"
            self.make_log(path)
            events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            events.extend([
                record("event_msg", "thread_settings_applied", "2026-10-11T10:01:30Z",
                       thread_settings={"service_tier": "priority"}),
                record("event_msg", "task_started", "2026-10-11T10:02:00Z", turn_id="turn-2"),
                record("event_msg", "task_complete", "2026-10-11T10:03:00Z", turn_id="turn-2"),
                record("event_msg", "thread_settings_applied", "2026-10-11T10:03:30Z",
                       thread_settings={"service_tier": "default"}),
                record("event_msg", "task_started", "2026-10-11T10:04:00Z", turn_id="turn-3"),
            ])
            path.write_text("\n".join(json.dumps(x) for x in events) + "\n", encoding="utf-8")
            self.assertEqual([r["service_tier"] for r in usage.parse_rollout(path)],
                             [None, "priority", "default"])

    def test_account_meter_before_after_from_observed_samples(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "sessions"
            day = usage.dt.datetime.now(usage.DENVER).strftime("%Y/%m/%d")
            target = root / day
            target.mkdir(parents=True)
            prior = target / "prior.jsonl"
            prior.write_text("\n".join(json.dumps(x) for x in [
                record("session_meta", None, "2026-10-11T09:59:00Z", id="other", cwd=r"C:\Other"),
                record("event_msg", "token_count", "2026-10-11T09:59:30Z", rate_limits={"limit_id":"codex","primary":{"used_percent":5,"window_minutes":10080,"resets_at":1792314030}}),
            ]) + "\n", encoding="utf-8")
            task = target / "task.jsonl"
            self.make_log(task)
            events = [json.loads(line) for line in task.read_text(encoding="utf-8").splitlines()]
            events[-2]["payload"]["rate_limits"] = {"limit_id":"codex","primary":{"used_percent":6,"window_minutes":10080,"resets_at":1792314030}}
            task.write_text("\n".join(json.dumps(x) for x in events) + "\n", encoding="utf-8")
            db = usage.connect(Path(folder) / "ledger.sqlite3")
            try:
                usage.scan(db, root, 1)
                before, after, note = db.execute("SELECT usage_left_before_percent,usage_left_after_percent,usage_meter_note FROM tasks").fetchone()
                self.assertEqual((before, after), (95, 94))
                self.assertIn("parallel", note)
                usage.scan(db, root, 1)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM rate_samples").fetchone()[0], 2)
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
