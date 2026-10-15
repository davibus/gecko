"""Correct this run's Stripe job-number filename and tracker target."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "job-scout"), str(ROOT / "scripts")]

import gecko_v2
from generate_apply_queue import _archived_description
from description_retrieval import description_is_sufficient
from google_tracker import GoogleTracker, verified_resume_file_uri

OLD = ROOT / "output/resumes/Dave-Call+Stripe+Product-Marketing-Manager,-Payments+Stripe.docx"
NEW = ROOT / "output/resumes/Dave-Call+Stripe+Product-Marketing-Manager,-Payments+8142770.docx"
OLD_ARCHIVE = ROOT / "input/job-descriptions/Stripe+Stripe.md"
NEW_ARCHIVE = ROOT / "input/job-descriptions/Stripe+8142770.md"
SCRATCH = ROOT / "scratch/Stripe+8142770"
REPORT = ROOT / "reports/stripe-job-id-repair.json"


def main() -> int:
    tracker = GoogleTracker()
    tab = tracker.scout(value_render_option="FORMULA")
    matches = [(row, data) for row, data in tab.rows
               if str(data.get("Scout ID") or "").strip() == "709"]
    if len(matches) != 1:
        raise RuntimeError("Stripe Scout ID 709 is missing or ambiguous")
    row, data = matches[0]
    if (data.get("Company") != "Stripe"
            or data.get("Job Title") != "Product Marketing Manager, Payments"
            or "8142770" not in str(data.get("Job URL") or "")
            or str(data.get("Apply?") or "").strip().casefold() != "yes"
            or str(data.get("Resume Created") or "").strip().casefold() != "x"
            or data.get("Resume Link") != verified_resume_file_uri(OLD)):
        raise RuntimeError("Stripe row changed; no repair made")
    if not OLD.is_file() or NEW.exists() or not OLD_ARCHIVE.is_file() or NEW_ARCHIVE.exists():
        raise RuntimeError("Stripe file/archive state changed; no repair made")
    old_text = OLD_ARCHIVE.read_text(encoding="utf-8-sig")
    if not description_is_sufficient(_archived_description(old_text)):
        raise RuntimeError("Stripe archive lacks a complete job description")
    before = "- **Job Number:** `Stripe`"
    if old_text.count(before) != 1:
        raise RuntimeError("Stripe archived job-number field is missing or ambiguous")
    SCRATCH.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps({"status": "planned", "row": row, "id": "709",
        "old_file": str(OLD), "new_file": str(NEW), "old_link": data["Resume Link"]}, indent=2))
    NEW_ARCHIVE.write_text(old_text.replace(before, "- **Job Number:** `8142770`"),
                           encoding="utf-8")
    OLD.replace(NEW)
    original_backup = SCRATCH / "superseded-source-id.docx"
    try:
        plan = gecko_v2.create_plan(NEW_ARCHIVE)
        qa = gecko_v2.native_qa(plan, NEW, SCRATCH)
        if qa["status"] != "pass":
            candidate = SCRATCH / "replacement-candidate.docx"
            generated = gecko_v2.generate_two_page_resume(plan, candidate, SCRATCH)
            if generated["status"] != "pass":
                raise RuntimeError("Stripe replacement did not pass Word-native QA")
            if original_backup.exists():
                raise RuntimeError("Stripe source backup already exists")
            NEW.replace(original_backup)
            candidate.replace(NEW)
            qa = gecko_v2.native_qa(plan, NEW, SCRATCH)
        if qa["status"] != "pass" or qa["word_pages"] != 2 or qa["pdf_pages"] != 2:
            raise RuntimeError("Corrected Stripe DOCX did not pass native Word QA")
        current = tracker.scout(value_render_option="FORMULA")
        live = dict(current.rows).get(row, {})
        if (str(live.get("Scout ID") or "") != "709"
                or live.get("Resume Link") != data["Resume Link"]
                or str(live.get("Resume Created") or "").strip().casefold() != "x"):
            raise RuntimeError("Stripe row changed during native QA")
        tracker._write(current, row, {"Resume Link": verified_resume_file_uri(NEW)})
        final = dict(tracker.scout().rows).get(row, {})
        if (str(final.get("Scout ID") or "") != "709"
                or str(final.get("Resume Created") or "").strip().casefold() != "x"
                or final.get("Resume Link") != verified_resume_file_uri(NEW)):
            raise RuntimeError("Stripe tracker readback failed")
    except Exception:
        # Keep any successfully written Sheet link attached to its file.
        current = dict(tracker.scout().rows).get(row, {})
        if current.get("Resume Link") == data["Resume Link"]:
            if original_backup.exists():
                NEW.replace(SCRATCH / "failed-replacement.docx")
                original_backup.replace(OLD)
            else:
                NEW.replace(OLD)
            NEW_ARCHIVE.unlink()
        raise
    old_backup = SCRATCH / "previous-archive.md"
    if not old_backup.exists():
        OLD_ARCHIVE.replace(old_backup)
    REPORT.write_text(json.dumps({"status": "verified", "row": row, "id": "709",
        "resume": str(NEW), "archive": str(NEW_ARCHIVE),
        "link": verified_resume_file_uri(NEW), "word_pages": 2, "pdf_pages": 2}, indent=2))
    print(REPORT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
