from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


SCOUT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCOUT_ROOT))

from ai_evaluation import (  # noqa: E402
    JobEvaluator, description_hash, meaningful_description_change,
)
from candidate_profile import load_candidate_profile  # noqa: E402
from deduplicate import find_duplicate  # noqa: E402
from hard_filters import deterministic_filter  # noqa: E402
from models import RawListing  # noqa: E402
from normalize import clean_text, normalize  # noqa: E402
from preferences import load_preferences  # noqa: E402
from service import discover_listings  # noqa: E402
from storage import JobStore  # noqa: E402


DESCRIPTION = (
    "Lead paid search and performance marketing across Google Ads and Microsoft Ads. "
    "Own budgets, forecasting, attribution, analytics, experimentation, reporting, "
    "team leadership, and cross-functional planning. " * 8
)


def job(source_id="one", *, title="Paid Search Manager", location="Remote - US",
        description=DESCRIPTION, salary="$120,000-$150,000"):
    return normalize(RawListing(
        source="test", source_job_id=source_id,
        url=f"https://jobs.example.test/{source_id}", title=title,
        company="Example", location=location, description=description,
        employment_type="Full-time", salary=salary,
    ))


class FakeAI:
    def __init__(self, triage="strong", apply="Yes"):
        self.calls = []
        self.triage = triage
        self.apply = apply

    def complete(self, *, model, system, payload):
        self.calls.append((model, system, payload))
        if "Classify" in system:
            return {"relevance": self.triage, "reason": "Relevant paid media leadership"}
        return {"match_score": 91, "apply": self.apply, "reason": "Strong evidence match"}


class CandidateProfileTests(unittest.TestCase):
    def test_profile_is_compact_and_verified_against_master(self):
        profile = load_candidate_profile()
        self.assertIn("paid_media_ppc", profile)
        self.assertLess(len(str(profile)), 6000)


class HardFilterTests(unittest.TestCase):
    def test_rejects_irrelevant_title_before_ai(self):
        accepted, reason = deterministic_filter(job(title="Senior Software Engineer"), load_preferences())
        self.assertFalse(accepted)
        self.assertIn("unrelated", reason)

    def test_rejects_non_remote_job_outside_preferred_locations(self):
        accepted, reason = deterministic_filter(job(location="Austin, TX"), load_preferences())
        self.assertFalse(accepted)
        self.assertIn("preferred", reason)

    def test_compensation_floor_is_configurable_and_missing_pay_is_not_invented(self):
        preferences = load_preferences()
        preferences["deterministic_filters"]["minimum_annual_salary"] = 130_000
        self.assertFalse(deterministic_filter(job(salary="$80,000-$100,000"), preferences)[0])
        candidate = job(salary="")
        self.assertTrue(deterministic_filter(candidate, preferences)[0])


class DescriptionCacheTests(unittest.TestCase):
    def test_hash_ignores_markup_case_and_whitespace(self):
        self.assertEqual(description_hash("<p>Hello  WORLD</p>"), description_hash("hello world"))

    def test_meaningful_change_ignores_shorter_snippet_but_detects_new_content(self):
        original = DESCRIPTION
        self.assertFalse(meaningful_description_change(original, "Lead paid search."))
        self.assertTrue(meaningful_description_change(
            original, original + (" New responsibility for retail media strategy." * 20)
        ))

    def test_two_stage_evaluation_is_cached_by_description(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            "JOB_SCOUT_TRIAGE_MODEL": "fast-model",
            "JOB_SCOUT_SCORING_MODEL": "strong-model",
        }, clear=False):
            with JobStore(Path(directory) / "jobs.sqlite3") as store:
                first = job("first")
                first.id = store.save(first)
                second = job("second")
                second.id = store.save(second)
                client = FakeAI()
                evaluator = JobEvaluator(store, load_preferences(), client=client)
                results, metrics = evaluator.evaluate([first])
                cached, cached_metrics = evaluator.evaluate([second])

                self.assertEqual(len(client.calls), 2)
                self.assertEqual(metrics.AI_triage_calls, 1)
                self.assertEqual(metrics.full_score_calls, 1)
                self.assertEqual(results[first.id].apply_decision, "Yes")
                self.assertEqual(cached_metrics.cached_unchanged, 1)
                self.assertEqual(cached[second.id].match_score, 91)
                self.assertIsNotNone(store.get_job_evaluation(second.id))

    def test_reject_triage_never_calls_full_scoring(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            "JOB_SCOUT_TRIAGE_MODEL": "fast-model",
            "JOB_SCOUT_SCORING_MODEL": "strong-model",
        }, clear=False):
            with JobStore(Path(directory) / "jobs.sqlite3") as store:
                candidate = job("reject")
                candidate.id = store.save(candidate)
                client = FakeAI(triage="reject")
                results, metrics = JobEvaluator(
                    store, load_preferences(), client=client
                ).evaluate([candidate])
                self.assertEqual(len(client.calls), 1)
                self.assertEqual(metrics.full_score_calls, 0)
                self.assertEqual(results[candidate.id].apply_decision, "No")

    def test_existing_job_is_requeued_only_for_meaningful_content_change(self):
        with tempfile.TemporaryDirectory() as directory:
            with JobStore(Path(directory) / "jobs.sqlite3") as store:
                original = job("changed")
                job_id = store.save(original)
                changed_text = DESCRIPTION + (" Own retail media and incrementality strategy." * 30)
                incoming = RawListing(
                    source="test", source_job_id="changed",
                    url="https://jobs.example.test/changed", title="Paid Search Manager",
                    company="Example", location="Remote - US", description=changed_text,
                    employment_type="Full-time",
                )
                summary = discover_listings(
                    [incoming], store, require_content=True, preserve_existing=True,
                    preexisting_ids={job_id}, preferences=load_preferences(),
                )
                self.assertEqual(summary.changed_job_ids, [job_id])
                self.assertEqual(store.get(job_id).description, clean_text(changed_text))


class IdentityDeduplicationTests(unittest.TestCase):
    def test_provider_job_id_precedes_fuzzy_fields(self):
        existing = job("stable-id")
        existing.id = 42
        changed = job("stable-id", title="Director of Performance Marketing", location="Utah")
        self.assertEqual(find_duplicate(changed, [existing]).id, 42)


if __name__ == "__main__":
    unittest.main()
