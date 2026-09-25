"""Generate the September 25 requested Scout batch with Gecko.

Usage: python scripts/generate_requested_scout_batch_20260925.py <scout-id>

Tracker updates remain separate so visual review can finish after native Word
validation and before any live Google Sheet mutation.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

import generate_requested_scout_batch as gecko


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "job-scout"))
from storage import JobStore  # noqa: E402

JOBS = {
    5: (
        "digital",
        8,
        [
            "The master resume does not document audio/video system design, office AV implementation, or enterprise workplace-technology architecture.",
            "AV engineering tools, infrastructure standards, vendor delivery, and role-specific technical certifications are unsupported; Scout also contains only a short excerpt.",
        ],
        "This opening is outside the master resume's documented digital marketing, ecommerce, and marketing-analytics experience.",
    ),
    29: (
        "digital",
        34,
        [
            "Hospitality venue marketing, restaurant promotions, and property-level event support are not documented in the master resume.",
            "The role is explicitly junior and hourly, creating a substantial seniority and compensation mismatch for a candidate with 14+ years of experience; Scout contains only a short excerpt.",
        ],
        "Confirm the day-to-day scope and whether the employer would consider an experienced candidate for this junior Marketing Associate position.",
    ),
    49: (
        "sales",
        10,
        [
            "The master resume does not document eligibility for a 2027 internship or an early-career sales-operations program.",
            "Quota-bearing sales, business-development pipeline ownership, and the internship's complete requirements are unsupported; Scout contains only a short excerpt.",
        ],
        "This internship is a clear seniority mismatch and is unlikely to be an appropriate application target.",
    ),
    907: (
        "digital",
        67,
        [
            "Marketing advisory specialization across PwC's PLS, TMT, and FS sectors is not documented in the master resume.",
            "The complete consulting-methodology, education, travel, and platform requirements are unavailable because Scout contains only a short excerpt.",
        ],
        "Lead with client consultation, customer-journey analysis, audience and messaging recommendations, campaign measurement, revenue analysis, and team leadership; verify the full PwC requirements before applying.",
    ),
}


def prepare(scout_id: int) -> dict:
    if scout_id not in JOBS:
        raise ValueError(f"Scout ID {scout_id} is not in this batch")
    gecko.JOBS[scout_id] = JOBS[scout_id]
    result = gecko.prepare(scout_id)
    report = Path(result["report"])
    body = report.read_text(encoding="utf-8")
    # Keep the report title ASCII-stable while preserving the exact job title.
    title = body.splitlines()[0].replace(" â€” ", " - ")
    with JobStore() as store:
        job = store.get(scout_id)
    if job is None:
        raise ValueError(f"Scout ID {scout_id} disappeared during generation")
    title = f"# {job.title} - {job.company}"
    report.write_text("\n".join([title, *body.splitlines()[1:]]), encoding="utf-8")
    return result


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python scripts/generate_requested_scout_batch_20260925.py <scout-id>")
    print(json.dumps(prepare(int(sys.argv[1])), indent=2))
