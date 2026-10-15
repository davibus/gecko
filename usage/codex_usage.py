"""Private, idempotent Codex rollout collector stored in Gecko Main.

Only metadata, a short opt-in description, and usage counters are retained.
The source transcript is never copied into the usage directory.
"""

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
from zoneinfo import ZoneInfo

DATA = Path(__file__).resolve().parent
DB = DATA / "codex_usage.sqlite3"
DENVER = ZoneInfo("America/Denver")
PARSER_VERSION = "6"
TOKEN_FIELDS = ("input_tokens", "cached_input_tokens", "cache_write_input_tokens", "output_tokens", "reasoning_output_tokens", "total_tokens")
SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
 session_id TEXT NOT NULL, turn_id TEXT NOT NULL, started_utc TEXT, ended_utc TEXT,
 local_date TEXT, duration_seconds REAL, status TEXT NOT NULL, description TEXT,
 source TEXT, terminal_name TEXT, model TEXT, effort TEXT, git_branch TEXT,
 input_tokens INTEGER, cached_input_tokens INTEGER, cache_write_input_tokens INTEGER,
 output_tokens INTEGER, reasoning_output_tokens INTEGER, total_tokens INTEGER,
 usage_quality TEXT NOT NULL, transcript_path TEXT NOT NULL,
 PRIMARY KEY(session_id, turn_id)
);
CREATE TABLE IF NOT EXISTS scanned_files (
 transcript_path TEXT PRIMARY KEY, file_size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS rate_samples (
 transcript_path TEXT NOT NULL, line_number INTEGER NOT NULL, observed_utc TEXT NOT NULL,
 limit_id TEXT NOT NULL, used_percent REAL NOT NULL, window_minutes INTEGER,
 resets_at INTEGER, PRIMARY KEY(transcript_path, line_number, limit_id)
);
CREATE INDEX IF NOT EXISTS rate_samples_time ON rate_samples(observed_utc, limit_id);
CREATE TABLE IF NOT EXISTS collector_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def iso_utc(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return dt.datetime.fromtimestamp(value, dt.timezone.utc).isoformat()
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(dt.timezone.utc).isoformat()
    except ValueError:
        return None


def short_description(message):
    if not message:
        return None
    request_header = list(re.finditer(r"(?im)^#{1,3}\s*my request:\s*", message))
    if request_header:
        message = message[request_header[-1].end():]
    message = re.sub(r"</?image\b[^>]*>", "", message, flags=re.IGNORECASE)
    message = re.sub(r"\s+", " ", message).strip()
    # Keep a deliberately short title. Never retain full prompts or tool output.
    message = re.sub(r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*[^\s,;]+", r"\1=[REDACTED]", message)
    return message[:160] if message else None


def text_from_user(payload):
    if payload.get("type") != "message" or payload.get("role") != "user":
        return None
    pieces = [x.get("text", "") for x in payload.get("content", []) if x.get("type") == "input_text"]
    text = " ".join(pieces).strip()
    if (text.startswith("# AGENTS.md instructions") or text.startswith("<environment_context>")
            or text.startswith("<external_codex_apps_open_page>")):
        return None
    return short_description(text)


def parse_rollout(path, include_descriptions=True):
    session = None
    turns = {}
    current = None
    previous_usage = None
    service_tier = None
    terminal = None  # Codex transcripts do not record Cursor's custom tab name.
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for line in stream:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue  # A live transcript can end with a partial line.
            kind = record.get("type")
            payload = record.get("payload") or {}
            stamp = iso_utc(record.get("timestamp"))
            if kind == "session_meta":
                session = payload
            elif kind == "event_msg" and payload.get("type") == "thread_settings_applied":
                settings = payload.get("thread_settings") or {}
                service_tier = settings.get("service_tier")
            elif kind == "event_msg" and payload.get("type") == "task_started":
                turn_id = payload.get("turn_id")
                if not turn_id:
                    continue
                current = turn_id
                turns.setdefault(turn_id, {"turn_id": turn_id, "started_utc": iso_utc(payload.get("started_at")) or stamp,
                                           "ended_utc": None, "status": "running", "description": None,
                                           "model": None, "effort": None, "service_tier": service_tier,
                                           "tokens": {f: 0 for f in TOKEN_FIELDS},
                                           "usage_seen": False})
            elif kind == "turn_context":
                turn_id = payload.get("turn_id")
                if turn_id in turns:
                    turns[turn_id]["model"] = payload.get("model")
                    turns[turn_id]["effort"] = payload.get("effort")
            elif kind == "response_item" and current in turns and include_descriptions:
                desc = text_from_user(payload)
                if desc and not turns[current]["description"]:
                    turns[current]["description"] = desc
            elif kind == "event_msg" and payload.get("type") == "token_count":
                usage = (payload.get("info") or {}).get("total_token_usage")
                if isinstance(usage, dict):
                    if current in turns:
                        for field in TOKEN_FIELDS:
                            now = usage.get(field)
                            before = (previous_usage or {}).get(field, 0)
                            if isinstance(now, int) and now >= 0:
                                turns[current]["tokens"][field] += now - before if isinstance(before, int) and now >= before else now
                        turns[current]["usage_seen"] = True
                    previous_usage = usage
            elif kind == "event_msg" and payload.get("type") in ("task_complete", "turn_aborted"):
                turn_id = payload.get("turn_id") or current
                if turn_id in turns:
                    turns[turn_id]["ended_utc"] = iso_utc(payload.get("completed_at")) or stamp
                    turns[turn_id]["status"] = "completed" if payload.get("type") == "task_complete" else "interrupted"
                if current == turn_id:
                    current = None
    if not session:
        return []
    output = []
    source = session.get("source")
    if not isinstance(source, str):
        source = json.dumps(source, sort_keys=True) if source is not None else None
    for turn in turns.values():
        start = turn["started_utc"]
        end = turn["ended_utc"]
        duration = None
        if start and end:
            duration = max(0, (dt.datetime.fromisoformat(end) - dt.datetime.fromisoformat(start)).total_seconds())
        local_date = dt.datetime.fromisoformat(start).astimezone(DENVER).date().isoformat() if start else None
        output.append({"session_id": session.get("id") or session.get("session_id") or path.stem,
                       "turn_id": turn["turn_id"], "started_utc": start, "ended_utc": end,
                       "local_date": local_date, "duration_seconds": duration,
                       "status": turn["status"], "description": turn["description"],
                       "source": source, "terminal_name": terminal,
                       "working_directory": session.get("cwd"),
                       "model": turn["model"], "effort": turn["effort"],
                       "service_tier": turn["service_tier"],
                       "git_branch": (session.get("git") or {}).get("branch"),
                       **{f: turn["tokens"][f] if turn["usage_seen"] else None for f in TOKEN_FIELDS},
                       "usage_quality": "observed_counter_delta" if turn["usage_seen"] else "unavailable",
                       "transcript_path": str(path)})
    return output


def parse_rate_samples(path):
    """Collect only the account meter, never content, from local Codex events."""
    samples = []
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for line_number, line in enumerate(stream, 1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = record.get("payload") or {}
            if record.get("type") != "event_msg" or payload.get("type") != "token_count":
                continue
            limits = payload.get("rate_limits") or {}
            primary = limits.get("primary") or {}
            used = primary.get("used_percent")
            stamp = iso_utc(record.get("timestamp"))
            if not stamp or not isinstance(used, (int, float)) or isinstance(used, bool) or not 0 <= used <= 100:
                continue
            samples.append((str(path), line_number, stamp, str(limits.get("limit_id") or "unknown"),
                            float(used), primary.get("window_minutes"), primary.get("resets_at")))
    return samples


def connect(db_path=DB):
    db = sqlite3.connect(db_path, timeout=30)
    db.execute("PRAGMA busy_timeout=30000")
    db.executescript(SCHEMA)
    columns = {row[1] for row in db.execute("PRAGMA table_info(tasks)")}
    additions = {
        "working_directory": "TEXT",
        "service_tier": "TEXT",
        "usage_left_before_percent": "REAL", "usage_left_after_percent": "REAL",
        "usage_before_observed_utc": "TEXT", "usage_after_observed_utc": "TEXT",
        "usage_window_resets_at": "INTEGER", "usage_meter_note": "TEXT",
    }
    if not set(additions).issubset(columns):
        with db:
            for column, datatype in additions.items():
                if column not in columns:
                    db.execute(f"ALTER TABLE tasks ADD COLUMN {column} {datatype}")
            # Existing files must be rescanned once to import their meter snapshots.
            db.execute("DELETE FROM scanned_files")
    previous_version = db.execute("SELECT value FROM collector_meta WHERE key='parser_version'").fetchone()
    if previous_version != (PARSER_VERSION,):
        with db:
            db.execute("DELETE FROM scanned_files")
            db.execute("INSERT INTO collector_meta(key,value) VALUES ('parser_version',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (PARSER_VERSION,))
    return db


def update_usage_meters(db):
    # The UI meter is an account-wide, seven-day primary limit. A previous
    # observation is useful only when recent and in the same reset window.
    tasks = db.execute("SELECT session_id,turn_id,started_utc,ended_utc,status FROM tasks").fetchall()
    for session_id, turn_id, started, ended, status in tasks:
        if not started:
            continue
        before = db.execute("""SELECT observed_utc,used_percent,resets_at FROM rate_samples
          WHERE limit_id='codex' AND window_minutes=10080 AND observed_utc<?
          AND observed_utc>=? ORDER BY observed_utc DESC LIMIT 1""",
          (started, (dt.datetime.fromisoformat(started) - dt.timedelta(minutes=30)).isoformat())).fetchone()
        after = None
        if status in ("completed", "interrupted") and ended:
            after = db.execute("""SELECT observed_utc,used_percent,resets_at FROM rate_samples
              WHERE limit_id='codex' AND window_minutes=10080 AND observed_utc>=?
              AND observed_utc<=? ORDER BY observed_utc DESC LIMIT 1""",
              (started, ended)).fetchone()
        note = None
        if before and after and before[2] != after[2]:
            note = "Usage window reset during task"
        elif not before:
            note = "No recent pre-task reading"
        elif not after:
            note = "No completed-task reading yet"
        else:
            note = "Account-wide readings; parallel tasks may contribute"
        db.execute("""UPDATE tasks SET usage_left_before_percent=?,usage_left_after_percent=?,
          usage_before_observed_utc=?,usage_after_observed_utc=?,usage_window_resets_at=?,usage_meter_note=?
          WHERE session_id=? AND turn_id=?""",
          (100-before[1] if before else None, 100-after[1] if after else None,
           before[0] if before else None, after[0] if after else None,
           after[2] if after else before[2] if before else None, note, session_id, turn_id))


def scan(db, sessions_root, days=3, include_descriptions=True):
    today = dt.datetime.now(DENVER).date()
    modified_since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).timestamp()
    paths = []
    for day_offset in range(days):
        day = today - dt.timedelta(days=day_offset)
        paths.extend((sessions_root / day.strftime("%Y") / day.strftime("%m") / day.strftime("%d")).glob("*.jsonl"))
    # A resumed old session keeps its original date path. An archived session
    # can move before the next scheduled collection.
    for root in (sessions_root, sessions_root.parent / "archived_sessions"):
        for path in root.rglob("*.jsonl") if root.exists() else ():
            try:
                if path.stat().st_mtime >= modified_since:
                    paths.append(path)
            except OSError:
                continue
    # Preserve coverage for long-running sessions started before the date window.
    paths.extend(Path(row[0]) for row in db.execute("SELECT transcript_path FROM scanned_files"))
    changed = 0
    for path in sorted(set(paths)):
        try:
            stat = path.stat()
        except OSError:
            continue
        cached = db.execute("SELECT file_size, mtime_ns FROM scanned_files WHERE transcript_path=?", (str(path),)).fetchone()
        if cached == (stat.st_size, stat.st_mtime_ns):
            continue
        try:
            rows = parse_rollout(path, include_descriptions)
            samples = parse_rate_samples(path)
        except OSError:
            continue
        with db:
            db.execute("DELETE FROM rate_samples WHERE transcript_path=?", (str(path),))
            db.executemany("INSERT INTO rate_samples VALUES (?,?,?,?,?,?,?)", samples)
            for row in rows:
                columns = list(row)
                db.execute(f"INSERT INTO tasks ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)}) "
                           + "ON CONFLICT(session_id,turn_id) DO UPDATE SET "
                           + ",".join(f"{col}=excluded.{col}" for col in columns if col not in ("session_id", "turn_id")),
                           tuple(row.values()))
            db.execute("INSERT INTO scanned_files VALUES (?,?,?) ON CONFLICT(transcript_path) DO UPDATE SET file_size=excluded.file_size,mtime_ns=excluded.mtime_ns",
                       (str(path), stat.st_size, stat.st_mtime_ns))
        changed += len(rows)
    with db:
        update_usage_meters(db)
    return changed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions-root", type=Path, default=Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "sessions")
    parser.add_argument("--db", type=Path, default=DB)
    parser.add_argument("--days", type=int, default=3)
    parser.add_argument("--no-descriptions", action="store_true", help="Do not store a short user prompt")
    parser.add_argument("--export-json", type=Path, help="Write a temporary JSON snapshot for workbook export")
    args = parser.parse_args(argv)
    if args.days < 1:
        parser.error("--days must be positive")
    args.db.parent.mkdir(parents=True, exist_ok=True)
    with connect(args.db) as db:
        changed = scan(db, args.sessions_root, args.days, not args.no_descriptions)
        count = db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        if args.export_json:
            db.row_factory = sqlite3.Row
            rows = [dict(row) for row in db.execute("SELECT * FROM tasks ORDER BY started_utc DESC")]
            args.export_json.parent.mkdir(parents=True, exist_ok=True)
            args.export_json.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    print(f"Recorded Codex turns: {count}; refreshed rows: {changed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
