"""Process the third September 24 Scout batch with Gecko and the canonical tracker.

Usage: python scripts/process_requested_scout_batch_20260924c.py START COUNT
The tracker worker is serialized and receives a job only after its Word-validated
resume and match report exist. Run successive non-overlapping slices of IDS.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import re
import subprocess
import sys

import generate_requested_scout_batch as gecko

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "job-scout"))
from handoff import job_number, safe_name  # noqa: E402
from storage import JobStore  # noqa: E402

IDS = tuple(int(x) for x in """
112 808 212 709 280 769 502 486 675 444 845 128 281 379 277 613 729 683 616 208
16 694 135 292 726 415 558 58 21 566 727 319 651 206 501 643 198 369 655 409
81 364 470 838 837 676 57 152 311 61 63 67 416 474 505 738 686 371 370 615
368 491 143 573 367 90 111 362 587 404 375 758 767 842 658 265 86 728 127 133
682 7 564 565 781 448 323 467 365 427 363 225 734 559 54 652 583 523 669 485
481 183 190 574 332 567 617 458 331 298 158 335 403 488 654 642 657 641 116 531
584 680 554 832 414 580 223 179 231 260 267 270 261 333 737 649 504 816 800 549
581 801 457 233 226 263 430 795 599 770 782 783 784 796 793 662 460 794 764 780
227 446 785 610 771 374 305 445 609 340 337 230 339 608 234 586 528 262 477 672
366 553 15 563 611 6 582 529 797 296 834 178 229 443 235 406 144 295 452 28
478 508 740 753 159 82 266 530 271 10 766 236 30 11 13 19 306 279 228 162
532 341 472 768 199 222 376 1 47 32 35 25 400 397 27 43 401 44
""".split())

# These records are plainly outside the marketing resume's professional field.
UNRELATED = {
    486, 470, 474, 467, 485, 481, 477, 478, 472, 6, 47, 32, 400,
    401, 44, 162, 30, 236, 10, 366, 553, 332,
}

SPECIAL = {
    709: ("digital", 34, "Payments product positioning and product launches are not documented in the master."),
    694: ("digital", 35, "Insurance product and channel-marketing ownership are not documented in the master."),
    280: ("analytics", 49, "BI data architecture and engineering ownership are not documented in the master."),
    281: ("analytics", 47, "AI-driven analytics program ownership is not documented in the master."),
    838: ("growth", 37, "ABM program ownership, CRM orchestration, and sourced pipeline are not documented."),
    837: ("growth", 48, "End-to-end B2B demand generation and sourced pipeline are not documented."),
    676: ("sales", 21, "Enterprise performance-marketing sales leadership and a sales quota are not documented."),
    54: ("sales", 20, "Strategic account executive quota and deal-closing history are not documented."),
    508: ("sales", 16, "Building-automation business development and sales-closing history are not documented."),
    199: ("sales", 21, "Beverage market-development sales and distributor account ownership are not documented."),
    409: ("digital", 49, "Cannabis or wellness industry marketing requirements are not documented."),
    116: ("content", 33, "SEO and AI-search editorial ownership are not documented."),
    331: ("content", 34, "Organic growth and SEO program ownership are not documented."),
    642: ("content", 35, "End-to-end technical and content SEO ownership are not documented."),
    641: ("content", 35, "End-to-end technical and content SEO ownership are not documented."),
    403: ("sales", 18, "Business-lending acquisition and financial-services sales leadership are not documented."),
    737: ("sales", 18, "Business-lending acquisition and financial-services sales leadership are not documented."),
    260: ("growth", 39, "Vice-president-level SaaS demand generation and marketing-sourced pipeline leadership are not documented."),
    61: ("digital", 34, "Medical-device surgery product marketing and clinical buyer expertise are not documented."),
    67: ("digital", 30, "Cryptocurrency trading product marketing and financial product launches are not documented."),
    27: ("sales", 28, "Ad-sales client development and quota-bearing sales leadership are not documented."),
    43: ("sales", 25, "Shopping business-direction and commercial ownership are not documented."),
}

GAPS = {
    "paid": "The current master supports search execution and account strategy, but does not establish any role-specific vertical, platform, or account requirement omitted from the short listing.",
    "social": "The master documents Meta, Instagram, and TikTok alongside broader paid media, but not a dedicated social-only program or every social platform in this role.",
    "analytics": "The master supports dashboards, SQL, Python, attribution, and forecasting; enterprise data architecture and unlisted BI platforms are not established.",
    "ecommerce": "The master documents ecommerce leadership, B2B/B2C expansion, and acquisition, but not this employer's merchandising systems or category experience.",
    "growth": "The master documents acquisition and experimentation, but not full CRM lifecycle, ABM, or marketing-sourced pipeline ownership.",
    "digital": "The master documents cross-channel digital marketing; brand, industry, and program ownership specific to this opening are not established.",
    "content": "The master documents SEO collaboration and measurement, but not full editorial, organic-search, or content-program ownership.",
    "sales": "The master documents client consultation and account strategy, but not a sales quota, prospecting pipeline, or closing record.",
}

BASE = {
    "paid": 77, "social": 56, "analytics": 64, "ecommerce": 64,
    "growth": 55, "digital": 52, "content": 36, "sales": 24,
}


def classify(job, scout_id: int) -> tuple[str, int, list[str], str]:
    # Re-read the master while scoring; gecko.prepare independently re-reads it
    # during generation and again for the final match report.
    master = gecko.source_text()
    if "75+ Google Ads accounts" not in master or "Built Tableau dashboards" not in master:
        raise RuntimeError("Current master resume evidence changed; review assessments")
    title = job.title.casefold()
    desc = job.description.casefold()
    if scout_id in UNRELATED:
        family, score = "digital", 7
        first = f"The master resume does not document the core qualifications for {job.title}."
    elif scout_id in SPECIAL:
        family, score, first = SPECIAL[scout_id]
    elif re.search(r"paid search|\bppc\b|\bsem\b|search engine marketing|paid media|advertising manager", title):
        family, score = "paid", BASE["paid"]
        first = GAPS[family]
    elif re.search(r"social media|social channels|paid social|instagram", title):
        family, score = "social", BASE["social"]
        first = GAPS[family]
    elif re.search(r"analytics|analyst|insights|data analyst|business intelligence", title):
        family, score = "analytics", BASE["analytics"]
        first = GAPS[family]
    elif re.search(r"e-?commerce|commerce|retail media|online retail", title):
        family, score = "ecommerce", BASE["ecommerce"]
        first = GAPS[family]
    elif re.search(r"product marketing|segment marketing|channel marketing|brand marketing|field marketing|event marketing|public relations", title):
        family, score = "digital", 34
        first = "Product positioning, go-to-market launches, brand/field programs, or event ownership named by the title are not documented in the master."
    elif re.search(r"email|lifecycle|marketing operations|web operations", title):
        family, score = "digital", 39
        first = "End-to-end email/CRM lifecycle automation or website operations ownership is not documented in the master."
    elif re.search(r"content|seo|organic", title):
        family, score = "content", BASE["content"]
        first = GAPS[family]
    elif re.search(r"sales|account executive|business development|partnerships", title):
        family, score = "sales", BASE["sales"]
        first = GAPS[family]
    elif re.search(r"growth|demand generation|acquisition", title):
        family, score = "growth", BASE["growth"]
        first = GAPS[family]
    else:
        family, score = "digital", BASE["digital"]
        first = GAPS[family]
    if family == "paid" and ("google ads" in desc or "microsoft ads" in desc):
        score += 4
    if family == "analytics" and ("tableau" in desc or "sql" in desc or "looker" in desc):
        score += 3
    if family == "ecommerce" and ("google ads" in desc or "amazon" in desc):
        score += 3
    if family == "social" and ("meta" in desc or "tiktok" in desc):
        score += 3
    if family == "paid" and "director" in title:
        score -= 6
    if len(job.description) < 600 and score > 20:
        score -= 3
    score = max(5, min(85, score))
    second = ("Scout contains only a short excerpt, so the full requirements and current opening must be confirmed."
              if len(job.description) < 1000 else
              "Review the full listing for additional requirements and application eligibility.")
    if "sa360" in desc or "search ads 360" in desc:
        second = "Search Ads 360 is mentioned in the listing but is not documented in the current master resume."
    elif "power bi" in desc:
        second = "Power BI is mentioned in the listing but is not documented in the current master resume."
    elif "salesforce" in desc or "marketo" in desc or "hubspot" in desc:
        second = "The named CRM or automation platform is not documented in the current master resume."
    if scout_id in UNRELATED:
        second = "This opening is outside the master resume's documented digital marketing, ecommerce, and analytics experience."
    note = ("This is a conservative assessment from the available Scout record. Verify the live employer posting and exact requirements before applying."
            if len(job.description) < 1000 else
            "Use the archived full listing to check all role requirements and eligibility before applying.")
    if scout_id in {613, 615}:
        note += " Wpromote's B2B director role may be the same opening under two Scout records; confirm the application destination."
    return family, score, [first, second], note


def tracker_add(result: dict) -> tuple[int, str]:
    args = [sys.executable, str(ROOT / "scripts/manage_job_tracker.py"), "add",
            "--resume", result["resume"], "--match-report", result["report"],
            "--job-description", result["listing"]]
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(args, cwd=ROOT, env=env, capture_output=True, text=True, errors="replace")
    message = (proc.stdout + " " + proc.stderr).strip().replace("\n", " ")
    print(("TRACKED" if proc.returncode == 0 else "TRACKER_FAILED"), result["scout_id"], message, flush=True)
    return proc.returncode, message


def run_slice(start: int, count: int) -> int:
    if start < 0 or count < 1 or start + count > len(IDS):
        raise ValueError(f"Invalid slice {start}:{start + count} for {len(IDS)} IDs")
    futures = []
    failures = []
    with ThreadPoolExecutor(max_workers=1) as tracker:
        with JobStore() as store:
            for scout_id in IDS[start:start + count]:
                try:
                    job = store.get(scout_id)
                    if job is None:
                        raise ValueError("Scout record missing")
                    gecko.JOBS[scout_id] = classify(job, scout_id)
                    result = gecko.prepare(scout_id)
                    report = Path(result["report"])
                    body = report.read_text(encoding="utf-8")
                    report.write_text(f"# {job.title} - {job.company}" + body[body.index("\n"):], encoding="utf-8")
                    print("VALIDATED", scout_id, job.company, result["word_pages"], result["pdf_pages"], flush=True)
                    futures.append((scout_id, tracker.submit(tracker_add, result)))
                except Exception as exc:
                    print("GENERATION_FAILED", scout_id, repr(exc), flush=True)
                    failures.append(scout_id)
        for scout_id, future in futures:
            try:
                if future.result()[0]:
                    failures.append(scout_id)
            except Exception as exc:
                print("TRACKER_FAILED", scout_id, repr(exc), flush=True)
                failures.append(scout_id)
    print("SLICE_DONE", start, count, "FAILURES", failures, flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: python scripts/process_requested_scout_batch_20260924c.py START COUNT")
    raise SystemExit(run_slice(int(sys.argv[1]), int(sys.argv[2])))
