"""Synchronize one explicitly mapped Cursor instruction file and Sheet cell.

Preview is the default. A write requires --apply; initial divergence and later
two-sided edits also require an expected destination hash from the preview.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager, redirect_stdout
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "job-scout"))
from google_tracker import Config, build_service  # noqa: E402

STATE_DIR = ROOT / "scratch" / "cursor-sheet-sync"
CELL_RE = re.compile(r"([A-Z]+)([1-9][0-9]*)\Z")
MAX_CELL_CHARS = 50_000
WATCH_STATUS = STATE_DIR / "watch-status.json"
WATCH_EVENTS = STATE_DIR / "watch-events.log"


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".sync-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def local_file(value: str) -> Path:
    candidate = ROOT / value
    path = candidate.resolve(strict=True)
    if not path.is_relative_to(ROOT.resolve()) or not path.is_file():
        raise ValueError("Cursor instruction file must exist inside Gecko Main")
    if path.suffix not in {".md", ".mdc"}:
        raise ValueError("Cursor instruction file must be .md or .mdc")
    return path


def a1(tab: str, cell: str) -> str:
    return "'" + tab.replace("'", "''") + "'!" + cell


def sheet_value(api, spreadsheet_id: str, tab: str, cell: str) -> str:
    result = api.values().get(spreadsheetId=spreadsheet_id, range=a1(tab, cell),
                              valueRenderOption="FORMULA").execute()
    values = result.get("values", [])
    value = values[0][0] if values and values[0] else ""
    if not isinstance(value, str):
        raise ValueError(f"{tab}!{cell} must contain text, not a number or boolean")
    if value.startswith("="):
        raise ValueError(f"{tab}!{cell} contains a formula; refusing to overwrite it")
    return value


def verify_tab(api, spreadsheet_id: str, tab: str, sheet_id: int, cell: str) -> None:
    result = api.get(spreadsheetId=spreadsheet_id,
                     fields="sheets(properties(sheetId,title,gridProperties),protectedRanges(range))").execute()
    matches = [s for s in result.get("sheets", [])
               if s.get("properties", {}).get("title") == tab
               and s.get("properties", {}).get("sheetId") == sheet_id]
    if len(matches) != 1:
        raise ValueError("Tab title and sheet ID do not identify the same unique live tab")
    match = CELL_RE.fullmatch(cell)
    if not match:
        raise ValueError("Cell must be a single A1 address, such as A1")
    column = 0
    for letter in match.group(1):
        column = column * 26 + ord(letter) - ord("A") + 1
    row = int(match.group(2))
    grid = matches[0]["properties"].get("gridProperties", {})
    if row > grid.get("rowCount", 0) or column > grid.get("columnCount", 0):
        raise ValueError("Cell is outside the existing tab grid")
    for entry in matches[0].get("protectedRanges", []):
        area = entry.get("range", {})
        if (area.get("startRowIndex", 0) <= row - 1 < area.get("endRowIndex", grid["rowCount"])
                and area.get("startColumnIndex", 0) <= column - 1 < area.get("endColumnIndex", grid["columnCount"])):
            raise ValueError("Cell is within a protected Sheet range")


def state_path(spreadsheet_id: str, sheet_id: int, cell: str, file: Path) -> Path:
    identity = json.dumps([spreadsheet_id, sheet_id, cell, str(file)], separators=(",", ":"))
    return STATE_DIR / (hashlib.sha256(identity.encode("utf-8")).hexdigest() + ".json")


def backup(source: str, target: str, direction: str, path: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = STATE_DIR / "backups" / f"{stamp}-{direction}-{path.stem}.json"
    atomic_write(output, json.dumps({"direction": direction, "source": source,
                                     "target": target, "file": str(path)},
                                    ensure_ascii=False, indent=2).encode("utf-8"))
    return output


def save_baseline(path: Path, spreadsheet_id: str, content: str) -> None:
    atomic_write(path, json.dumps({"spreadsheet_id": spreadsheet_id,
                                   "content_sha256": digest(content)}).encode("utf-8"))


def run(args, api, spreadsheet_id: str) -> str:
    file = local_file(args.file)
    cell = args.cell.upper()
    verify_tab(api, spreadsheet_id, args.tab, args.sheet_id, cell)
    sheet = sheet_value(api, spreadsheet_id, args.tab, cell)
    cursor = file.read_text(encoding="utf-8-sig")
    source, target = ((sheet, cursor) if args.command == "sheets-to-cursor"
                      else (cursor, sheet))
    if not source:
        raise ValueError("Source is blank; refusing to clear instructions")
    if len(source) > MAX_CELL_CHARS:
        raise ValueError("Source exceeds the Google Sheets 50,000 character cell limit")
    state_file = state_path(spreadsheet_id, args.sheet_id, cell, file)
    baseline = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else None
    if baseline and baseline.get("spreadsheet_id") != spreadsheet_id:
        raise ValueError("Saved sync state belongs to another spreadsheet")
    source_hash, target_hash = digest(source), digest(target)
    print(f"Direction: {args.command}")
    print(f"Target: {args.tab}!{cell} (tab ID {args.sheet_id}) / {file}")
    print(f"Source SHA-256: {source_hash}")
    print(f"Destination SHA-256: {target_hash}")
    if source == target:
        print("Already equal; no content write needed")
        if args.apply:
            save_baseline(state_file, spreadsheet_id, source)
        return "equal"
    conflict = baseline is None or target_hash != baseline.get("content_sha256")
    if conflict:
        print("Destination differs from the last synced value, or no baseline exists")
        if not (args.apply and args.expect_destination_sha256 == target_hash):
            print("Write blocked; rerun with --apply --expect-destination-sha256 " + target_hash)
            return "conflict"
    elif args.expect_destination_sha256 and args.expect_destination_sha256 != target_hash:
        raise ValueError("Expected destination hash no longer matches")
    if not args.apply:
        print("Preview only; rerun with --apply to sync")
        return "preview"

    # Compare both endpoints once more directly before creating the backup/write.
    if file.read_text(encoding="utf-8-sig") != cursor:
        raise RuntimeError("Cursor file changed during preflight")
    verify_tab(api, spreadsheet_id, args.tab, args.sheet_id, cell)
    if sheet_value(api, spreadsheet_id, args.tab, cell) != sheet:
        raise RuntimeError("Sheet cell changed during preflight")
    saved = backup(source, target, args.command, file)
    if args.command == "sheets-to-cursor":
        atomic_write(file, source.encode("utf-8"))
        if file.read_text(encoding="utf-8") != source:
            raise RuntimeError(f"Cursor file readback failed; backup: {saved}")
    else:
        api.values().update(spreadsheetId=spreadsheet_id, range=a1(args.tab, cell),
                            valueInputOption="RAW", body={"values": [[source]]}).execute()
        if sheet_value(api, spreadsheet_id, args.tab, cell) != source:
            raise RuntimeError(f"Sheet cell readback failed; backup: {saved}")
    save_baseline(state_file, spreadsheet_id, source)
    print(f"Synced and verified. Backup: {saved}")
    return "synced"


def watch_once(args, api, spreadsheet_id: str) -> str:
    file = local_file(args.file)
    cell = args.cell.upper()
    verify_tab(api, spreadsheet_id, args.tab, args.sheet_id, cell)
    sheet = sheet_value(api, spreadsheet_id, args.tab, cell)
    cursor = file.read_text(encoding="utf-8-sig")
    state_file = state_path(spreadsheet_id, args.sheet_id, cell, file)
    baseline = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else None
    if baseline and baseline.get("spreadsheet_id") != spreadsheet_id:
        raise ValueError("Saved sync state belongs to another spreadsheet")
    if sheet == cursor:
        if not baseline or baseline.get("content_sha256") != digest(sheet):
            save_baseline(state_file, spreadsheet_id, sheet)
        return "equal"
    if not sheet or not cursor or baseline is None:
        return "conflict"
    previous = baseline.get("content_sha256")
    if digest(sheet) == previous and digest(cursor) != previous:
        direction = "cursor-to-sheets"
    elif digest(cursor) == previous and digest(sheet) != previous:
        direction = "sheets-to-cursor"
    else:
        return "conflict"
    invocation = argparse.Namespace(command=direction, file=args.file, tab=args.tab,
                                    sheet_id=args.sheet_id, cell=cell, apply=True,
                                    expect_destination_sha256=None)
    with redirect_stdout(io.StringIO()):
        result = run(invocation, api, spreadsheet_id)
    return direction if result == "synced" else result


def record_watch(outcome: str, *, detail: str = "") -> None:
    now = datetime.now(timezone.utc).isoformat()
    previous = None
    if WATCH_STATUS.exists():
        try:
            previous = json.loads(WATCH_STATUS.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    status = {"checked_at_utc": now, "outcome": outcome, "detail": detail}
    if previous and previous.get("outcome") == outcome and previous.get("detail") == detail:
        status["last_changed_at_utc"] = previous.get("last_changed_at_utc", now)
    else:
        status["last_changed_at_utc"] = now
        WATCH_EVENTS.parent.mkdir(parents=True, exist_ok=True)
        with WATCH_EVENTS.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(status, ensure_ascii=False) + "\n")
    atomic_write(WATCH_STATUS, json.dumps(status, indent=2).encode("utf-8"))


@contextmanager
def watch_lock():
    import msvcrt

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with (STATE_DIR / "watch.lock").open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            raise RuntimeError("Another Cursor/Sheet watcher is already running") from error
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def watch(args, api, spreadsheet_id: str) -> None:
    with watch_lock():
        while True:
            try:
                outcome = watch_once(args, api, spreadsheet_id)
                detail = ("Both sides changed or the sync baseline is missing; inspect both before a manual resolution"
                          if outcome == "conflict" else "")
                record_watch(outcome, detail=detail)
            except Exception as error:
                record_watch("error", detail=f"{type(error).__name__}: {error}")
            if args.once:
                return
            time.sleep(args.interval_seconds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list-tabs", help="Read live tab titles and IDs without changing the workbook")
    watcher = sub.add_parser("watch", help="Automatically sync whichever endpoint changed")
    watcher.add_argument("--interval-seconds", type=int, default=60,
                         help="Polling interval; default 60 seconds")
    watcher.add_argument("--once", action="store_true", help="Check one time and exit")
    for name in ("sheets-to-cursor", "cursor-to-sheets", "watch"):
        command = watcher if name == "watch" else sub.add_parser(name)
        command.add_argument("--file", required=True, help="Existing .md or .mdc in Gecko Main")
        command.add_argument("--tab", required=True, help="Exact live tab title")
        command.add_argument("--sheet-id", required=True, type=int, help="Exact live numeric tab ID")
        command.add_argument("--cell", required=True, help="Single A1 cell, such as A1")
        if name != "watch":
            command.add_argument("--apply", action="store_true", help="Permit a guarded write")
            command.add_argument("--expect-destination-sha256", help="Required for initial divergence or changed destination")
    args = parser.parse_args(argv)
    try:
        config = Config.from_environment()
        api = build_service(config).spreadsheets()
        if args.command == "list-tabs":
            result = api.get(spreadsheetId=config.spreadsheet_id,
                             fields="properties(title),sheets(properties(sheetId,title,hidden))").execute()
            print("Workbook: " + result.get("properties", {}).get("title", "(untitled)"))
            for item in result.get("sheets", []):
                props = item["properties"]
                print(f"{props['title']} | ID {props['sheetId']} | hidden={props.get('hidden', False)}")
            return 0
        if args.command == "watch":
            if args.interval_seconds < 15:
                raise ValueError("Watcher interval must be at least 15 seconds")
            watch(args, api, config.spreadsheet_id)
            return 0
        result = run(args, api, config.spreadsheet_id)
        return 2 if result == "conflict" else 0
    except Exception as error:
        print(f"Sync stopped: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
