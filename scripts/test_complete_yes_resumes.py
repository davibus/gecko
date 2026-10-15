"""Focused source-identity and description gates for the Yes-row resume pass."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest
from types import SimpleNamespace

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "job-scout"),
                str(Path(__file__).resolve().parent)]

from description_retrieval import description_is_sufficient
from generate_apply_queue import (QueueRow, _archive_has_live_source_id,
                                  _archived_description, _job_number,
                                  _stored_job_matches_row)


class ResumeSourceTests(unittest.TestCase):
    def test_short_or_truncated_description_is_blocked(self):
        text = "# Role\n\n## Full job description\n\n" + "Real duties. " * 65 + "..."
        self.assertFalse(description_is_sufficient(_archived_description(text)))
        self.assertFalse(description_is_sufficient(_archived_description(
            "# Role\n\n## Full job description\n\n## Scout excerpt\n" + "Excerpt " * 100)))

    def test_substantive_description_is_accepted(self):
        text = "# Role\n\n## Full job description\n\n" + "Specific responsibilities and qualifications. " * 30
        self.assertTrue(description_is_sufficient(_archived_description(text)))

    def test_source_link_can_prove_aggregator_to_employer_match(self):
        item = QueueRow(2, 42, "6sense", "Marketing Manager",
                        "https://boards.greenhouse.io/6sense/jobs/7512125", "jobicy")
        job = SimpleNamespace(source="greenhouse", company=item.company, title=item.title,
            url="https://jobicy.com/jobs/152834-marketing-manager", original_url="",
            authoritative_url="", url_redirect_url="", source_links=[
                {"url": "https://boards.greenhouse.io/6sense/jobs/7512125"}])
        self.assertTrue(_stored_job_matches_row(job, item))
        item = QueueRow(2, 42, item.company, item.title,
                        "https://boards.greenhouse.io/6sense/jobs/other", "jobicy")
        self.assertFalse(_stored_job_matches_row(job, item))

    def test_adzuna_archive_number_requires_exact_live_path_id(self):
        item = QueueRow(2, 42, "Deloitte", "Manager",
                        "https://www.adzuna.com/land/ad/5900550784?se=abc", "adzuna")
        self.assertTrue(_archive_has_live_source_id(item, "5900550784", "5900550784"))
        self.assertFalse(_archive_has_live_source_id(item, "5900550784", "5900550785"))

    def test_web_careers_numeric_url_id_beats_generic_source_label(self):
        job = SimpleNamespace(source="web-careers", source_job_id="Stripe",
                              url="https://stripe.com/careers/listing/role/8142770")
        self.assertEqual(_job_number(job), "8142770")


if __name__ == "__main__":
    unittest.main()
