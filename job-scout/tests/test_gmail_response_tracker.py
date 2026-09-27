"""Offline Gmail matching and tracker-write tests."""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path


SCOUT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCOUT_ROOT))

from gmail_response_tracker import (  # noqa: E402
    EmailMessage, GmailConfig, JobCandidate, ResponseMatch,
    gmail_query, match_message, run_response_check, should_replace,
)


def message(message_id: str, subject: str, text: str, *, day=27,
            sender="Jordan Recruiter <jordan@example.com>") -> EmailMessage:
    return EmailMessage(
        message_id, "thread-" + message_id, sender, subject,
        datetime(2026, 9, day, 16, 30, tzinfo=timezone.utc), text,
    )


def job(row=2, *, title="Paid Search Manager", response="") -> JobCandidate:
    return JobCandidate(
        row=row, company="Example Co", title=title,
        job_url="https://example.com/jobs/job-123", job_number="job-123",
        relevant_date=date(2026, 9, 20), existing_response=response,
    )


class FakeTracker:
    def __init__(self, rows):
        self.rows = rows
        self.writes = []

    def applied_response_rows(self):
        return self.rows

    def update_response_rows(self, updates):
        self.writes.append(dict(updates))
        for row in self.rows:
            if row["_row"] in updates:
                row["Response"] = updates[row["_row"]]
        return sorted(updates)


class FakeGmail:
    def __init__(self, messages):
        self.messages = {item.message_id: item for item in messages}
        self.reads = []

    def search_ids(self, _query, _limit):
        return list(self.messages)

    def get_message(self, message_id):
        self.reads.append(message_id)
        return self.messages[message_id]


class GmailMatchingTests(unittest.TestCase):
    def test_query_excludes_sent_promotional_and_social_mail(self):
        query = gmail_query(job(), date(2026, 9, 27))
        self.assertIn("after:2026/09/19", query)
        self.assertIn("-in:sent", query)
        self.assertIn("-category:promotions", query)
        self.assertIn("-category:social", query)

    def test_matches_interview_with_company_title_and_application_context(self):
        email = message(
            "m1", "Interview for Paid Search Manager at Example Co",
            "We reviewed your application and would like to schedule a 30-minute phone screen.",
        )
        match = match_message(email, [job()])
        self.assertIsNotNone(match)
        self.assertEqual(match.stage, "interview")
        self.assertIn("Interview request", match.summary)
        self.assertIn("Received 9/27/26", match.summary)

    def test_rejects_generic_job_alert(self):
        email = message(
            "m2", "Job alert: Paid Search Manager at Example Co",
            "Recommended jobs you may be interested in.",
            sender="LinkedIn Jobs <jobs-noreply@linkedin.com>",
        )
        self.assertIsNone(match_message(email, [job()]))

    def test_rejects_application_confirmation_without_substantive_next_step(self):
        email = message(
            "m3", "Application received - Example Co",
            "Thank you for applying for Paid Search Manager. We have received your application.",
        )
        self.assertIsNone(match_message(email, [job()]))

    def test_ambiguous_company_only_message_does_not_choose_between_two_jobs(self):
        email = message(
            "m4", "Example Co interview invitation",
            "We reviewed your application and would like to schedule an interview.",
        )
        self.assertIsNone(match_message(email, [
            job(2, title="Paid Search Manager"),
            job(3, title="Performance Marketing Director"),
        ]))

    def test_newer_rejection_replaces_prior_interview_but_older_status_does_not(self):
        prior = {"stage": "interview", "received_date": "2026-09-26"}
        rejection_message = message(
            "m5", "Update on your Example Co application",
            "Unfortunately, we will not be moving forward with your application for Paid Search Manager.",
            day=27,
        )
        rejection = match_message(rejection_message, [job()])
        self.assertTrue(should_replace("Interview request - Received 9/26/26.", rejection, prior))

        old_status = ResponseMatch(
            job(), message("m6", "Application status", "Update on your application.", day=25),
            "status_update", 9, "Status update - Received 9/25/26.",
        )
        self.assertFalse(should_replace("Interview request - Received 9/26/26.", old_status, prior))

    def test_repeat_run_uses_state_and_does_not_duplicate_tracker_update(self):
        rows = [{
            "_row": 2, "Company": "Example Co", "Job Title": "Paid Search Manager",
            "Job URL": "https://example.com/jobs/job-123", "Job Number": "job-123",
            "Date Found": "2026-09-20", "Response": "",
        }]
        tracker = FakeTracker(rows)
        gmail = FakeGmail([message(
            "m7", "Interview for Paid Search Manager at Example Co",
            "We reviewed your application and would like to schedule a phone screen.",
        )])
        with tempfile.TemporaryDirectory() as directory:
            config = GmailConfig(
                Path(directory) / "client.json", Path(directory) / "token.json",
                Path(directory) / "state.json", 25,
            )
            first = run_response_check(tracker, gmail, config, today=date(2026, 9, 27))
            second = run_response_check(tracker, gmail, config, today=date(2026, 9, 27))

        self.assertEqual((first.emails_checked, first.emails_matched, first.tracker_rows_updated),
                         (1, 1, 1))
        self.assertEqual((second.emails_checked, second.emails_matched, second.tracker_rows_updated),
                         (0, 0, 0))
        self.assertEqual(second.skipped_processed, 1)
        self.assertEqual(len([write for write in tracker.writes if write]), 1)


if __name__ == "__main__":
    unittest.main()
