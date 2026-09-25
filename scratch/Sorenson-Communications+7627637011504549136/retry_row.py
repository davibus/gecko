import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "job-scout"))

import generate_apply_queue as queue
from google_tracker import GoogleTracker
from storage import DEFAULT_DB

tracker = GoogleTracker()
pending, _ = queue.read_queue(tracker)
item = next(row for row in pending if row.scout_id == 765)
artifacts = queue.generate(item, DEFAULT_DB)
queue.record_success(item, artifacts, tracker)
score = queue.manage_job_tracker.extract_score(
    artifacts.report.read_text(encoding="utf-8-sig")
)
print(
    f"RETRIED_SUCCESS|{item.row}|{item.scout_id}|{item.company}|{item.title}|"
    f"{artifacts.resume}|{score}|existing={artifacts.existing}"
)
