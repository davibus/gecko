"""Two-stage, cached AI screening for newly discovered jobs."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import hashlib
import html
import json
import os
import re
import sys
from urllib.request import Request, urlopen

from candidate_profile import candidate_profile_hash, compact_profile_text, load_candidate_profile


@dataclass
class Evaluation:
    description_hash: str
    profile_hash: str
    triage_model: str
    scoring_model: str
    relevance: str
    triage_reason: str
    match_score: int | None = None
    apply_decision: str = "No"
    score_reason: str = ""
    evaluated_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EvaluationMetrics:
    cached_unchanged: int = 0
    AI_triage_calls: int = 0
    full_score_calls: int = 0
    Apply_Yes: int = 0
    failures: int = 0
    disabled: bool = False


def normalize_description(value: str) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", value or "")).casefold()
    text = re.sub(r"https?://\S+", " <url> ", text)
    text = re.sub(r"[^a-z0-9+#.$%]+", " ", text)
    return " ".join(text.split())


def description_hash(value: str) -> str:
    return hashlib.sha256(normalize_description(value).encode("utf-8")).hexdigest()


def meaningful_description_change(previous: str, current: str) -> bool:
    """Ignore whitespace/punctuation churn and shorter aggregator snippets."""
    before, after = normalize_description(previous), normalize_description(current)
    if not before or not after or before == after or len(after) < len(before) * 0.65:
        return False
    left, right = set(before.split()), set(after.split())
    similarity = len(left & right) / len(left | right) if left and right else 1.0
    return similarity < 0.97


class OpenAIJsonClient:
    """Small OpenAI-compatible JSON client with no added runtime dependency."""

    def __init__(self, api_key: str | None = None, base_url: str | None = None,
                 timeout: float | None = None):
        self.api_key = (api_key if api_key is not None else os.getenv("OPENAI_API_KEY", "")).strip()
        self.base_url = (base_url or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
        self.timeout = float(timeout or os.getenv("JOB_SCOUT_AI_TIMEOUT_SECONDS", "60"))

    def complete(self, *, model: str, system: str, payload: dict) -> dict:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is required when Job Scout AI models are configured")
        body = json.dumps({
            "model": model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
        }).encode("utf-8")
        request = Request(
            f"{self.base_url}/chat/completions", data=body, method="POST",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
            content = result["choices"][0]["message"]["content"]
            return json.loads(content)
        except Exception as error:
            raise RuntimeError(f"Job Scout AI request failed for model {model}: {error}") from error


class JobEvaluator:
    def __init__(self, store, preferences: dict, client=None):
        settings = preferences.get("ai_evaluation", {})
        self.triage_model = os.getenv("JOB_SCOUT_TRIAGE_MODEL", settings.get("triage_model", "")).strip()
        self.scoring_model = os.getenv("JOB_SCOUT_SCORING_MODEL", settings.get("scoring_model", "")).strip()
        self.resume_model = os.getenv("GECKO_RESUME_MODEL", settings.get("resume_model", "")).strip()
        self.max_triage_chars = int(settings.get("max_triage_description_chars", 6000))
        self.max_scoring_chars = int(settings.get("max_scoring_description_chars", 14000))
        self.store = store
        self.client = client or OpenAIJsonClient()
        self.profile = load_candidate_profile(settings.get("candidate_profile") or None)
        self.profile_text = compact_profile_text(self.profile)
        self.profile_hash = candidate_profile_hash(self.profile)

    @property
    def enabled(self) -> bool:
        return bool(self.triage_model and self.scoring_model)

    @staticmethod
    def _description(job) -> str:
        return max((job.description or "", job.enriched_description or ""), key=len)

    def evaluate(self, jobs: list, *, dry_run: bool = False) -> tuple[dict[int, Evaluation], EvaluationMetrics]:
        results: dict[int, Evaluation] = {}
        metrics = EvaluationMetrics(disabled=not self.enabled)
        if dry_run or not self.enabled:
            return results, metrics
        for job in jobs:
            if job is None or job.id is None:
                continue
            description = self._description(job)
            digest = description_hash(description)
            cached = self.store.find_cached_evaluation(
                digest, self.profile_hash, self.triage_model, self.scoring_model
            )
            if cached:
                evaluation = Evaluation(**cached)
                self.store.save_job_evaluation(job.id, evaluation.to_dict())
                results[job.id] = evaluation
                metrics.cached_unchanged += 1
                metrics.Apply_Yes += int(evaluation.apply_decision == "Yes")
                continue
            try:
                if len(normalize_description(description)) < 100:
                    raise ValueError("job description is too short for reliable AI evaluation")
                metrics.AI_triage_calls += 1
                triage = self.client.complete(
                    model=self.triage_model,
                    system=("Classify job relevance to the candidate. Return JSON only with "
                            "relevance=reject|possible|strong and a concise reason. Do not score or write a report."),
                    payload={
                        "candidate_profile": json.loads(self.profile_text),
                        "job": {"title": job.title, "company": job.company,
                                "location": job.location, "work_arrangement": job.work_arrangement,
                                "description": description[:self.max_triage_chars]},
                    },
                )
                relevance = str(triage.get("relevance", "")).casefold()
                if relevance not in {"reject", "possible", "strong"}:
                    raise ValueError("triage response has invalid relevance")
                evaluation = Evaluation(
                    description_hash=digest, profile_hash=self.profile_hash,
                    triage_model=self.triage_model, scoring_model=self.scoring_model,
                    relevance=relevance, triage_reason=str(triage.get("reason", ""))[:1000],
                    evaluated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                )
                if relevance != "reject":
                    metrics.full_score_calls += 1
                    score = self.client.complete(
                        model=self.scoring_model,
                        system=("Evaluate candidate/job fit. Return JSON only with integer match_score "
                                "from 0 to 100, apply as Yes or No, and a concise evidence-based reason. "
                                "Do not invent candidate experience."),
                        payload={
                            "candidate_profile": json.loads(self.profile_text),
                            "triage": triage,
                            "job": {"title": job.title, "company": job.company,
                                    "location": job.location, "work_arrangement": job.work_arrangement,
                                    "employment_type": job.employment_type, "salary": job.salary,
                                    "description": description[:self.max_scoring_chars]},
                        },
                    )
                    evaluation.match_score = max(0, min(100, int(score["match_score"])))
                    decision = str(score.get("apply", "No")).strip().casefold()
                    evaluation.apply_decision = "Yes" if decision == "yes" else "No"
                    evaluation.score_reason = str(score.get("reason", ""))[:2000]
                self.store.cache_evaluation(evaluation.to_dict())
                self.store.save_job_evaluation(job.id, evaluation.to_dict())
                results[job.id] = evaluation
                metrics.Apply_Yes += int(evaluation.apply_decision == "Yes")
            except (KeyError, TypeError, ValueError, RuntimeError) as error:
                metrics.failures += 1
                print(f"Warning: AI evaluation failed for Scout ID {job.id}: {error}", file=sys.stderr)
        return results, metrics
