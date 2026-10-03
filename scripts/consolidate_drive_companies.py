"""Consolidate company folders in one explicitly identified Google Drive tree.

The command is live by default.  It inventories the entire tree before planning
or changing anything, journals every mutation, and can reverse completed moves,
renames, and trash operations with ``--restore``.

Google Workspace editor files are deliberately never deduplicated: the Drive
API does not expose one canonical byte stream containing every meaningful
feature (formatting, notes, embedded objects, formulas, and so on).  Stored
binary files are deduplicated only after complete downloads compare by SHA-256.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import random
import re
import socket
import ssl
import sys
import time
from typing import Any, Callable, Iterable
import zipfile


FOLDER_MIME = "application/vnd.google-apps.folder"
SHORTCUT_MIME = "application/vnd.google-apps.shortcut"
NATIVE_PREFIX = "application/vnd.google-apps."
DEFAULT_FOLDER_ID = "1ULYn6nDvbEqR8h7LDuEUfPUcXiObcwvw"
SCOPES = ["https://www.googleapis.com/auth/drive"]
FIELDS = (
    "id,name,mimeType,size,version,createdTime,modifiedTime,viewedByMeTime,"
    "parents,trashed,md5Checksum,sha1Checksum,sha256Checksum,headRevisionId,"
    "webViewLink,originalFilename,fileExtension,fullFileExtension,description,"
    "starred,ownedByMe,writersCanShare,copyRequiresWriterPermission,"
    "capabilities(canDownload,canMoveItemWithinDrive,canMoveItemOutOfDrive,canTrash),"
    "shortcutDetails(targetId,targetMimeType,targetResourceKey),"
    "permissions(id,type,role,emailAddress,domain,allowFileDiscovery,deleted,pendingOwner,"
    "permissionDetails(inherited,inheritedFrom,permissionType,role)),linkShareMetadata,"
    "resourceKey,driveId"
)

PRIORITY_ALIASES = {
    "tpg": {"tpg", "travelpassgroup", "travelpass", "dcalltpg"},
    "1800contacts": {"18c", "1800contacts", "dcall1800contacts"},
    "grip6": {"grip6", "dcallgrip6"},
    "stonebridge": {"stonebridge", "dcallstonebridge"},
}
DISPLAY_NAMES = {
    "tpg": ("TPG", "Travelpass Group", "Travel Pass Group"),
    "1800contacts": ("1800 Contacts", "1-800 Contacts", "1800Contacts", "18C"),
    "grip6": ("GRIP6", "GRIP 6"),
    "stonebridge": ("Stonebridge",),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_environment(root: Path) -> None:
    for name in (".env.drive-cleanup.local", ".env.local", ".env.google-sheets.local", ".env"):
        path = root / name
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key and key.replace("_", "").isalnum() and not key[0].isdigit():
                os.environ.setdefault(key, value.strip().strip("\"'"))


def credential_selection(project_root: Path) -> tuple[str, Path]:
    """Return the selected credential kind and path without reading secret values."""
    load_environment(project_root)
    token_value = os.getenv("GOOGLE_DRIVE_TOKEN_FILE", "").strip()
    service_value = (
        os.getenv("GOOGLE_DRIVE_CREDENTIALS_FILE", "").strip()
        or os.getenv("GOOGLE_SHEETS_CREDENTIALS_FILE", "").strip()
    )
    if token_value:
        return "user_oauth", Path(os.path.expandvars(token_value)).expanduser().resolve()
    if service_value:
        return "service_account", Path(os.path.expandvars(service_value)).expanduser().resolve()
    raise RuntimeError(
        "No authorized Drive credential is configured. Set GOOGLE_DRIVE_TOKEN_FILE "
        "or GOOGLE_DRIVE_CREDENTIALS_FILE."
    )


def build_drive_service(project_root: Path):
    """Reuse an already-authorized OAuth token or service-account key."""
    load_environment(project_root)
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials as UserCredentials
        from google.oauth2.service_account import Credentials as ServiceCredentials
        from googleapiclient.discovery import build
        from google_auth_httplib2 import AuthorizedHttp
        import httplib2
    except ImportError as error:
        raise RuntimeError(
            "Google Drive dependencies are missing; install job-scout/requirements.txt"
        ) from error

    kind, selected_path = credential_selection(project_root)
    credentials = None
    if kind == "user_oauth":
        token = selected_path
        if not token.is_file():
            raise RuntimeError(f"Configured Google Drive token file is unavailable: {token}")
        token_metadata = json.loads(token.read_text(encoding="utf-8"))
        granted = set(token_metadata.get("scopes") or [])
        if SCOPES[0] not in granted:
            raise RuntimeError(
                "The selected Drive OAuth token was not granted the full Drive scope. "
                "Run this script with --authorize; changing the requested scope alone is insufficient."
            )
        credentials = UserCredentials.from_authorized_user_file(str(token))
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
    elif kind == "service_account":
        key = selected_path
        if not key.is_file():
            raise RuntimeError(f"Configured Google credential file is unavailable: {key}")
        credentials = ServiceCredentials.from_service_account_file(str(key), scopes=SCOPES)
    # Bound individual socket reads. Higher-level retry() handles transient
    # failures with backoff, while mutation helpers perform readback before retry.
    http = AuthorizedHttp(credentials, http=httplib2.Http(timeout=120))
    return build("drive", "v3", http=http, cache_discovery=False)


def authorize_drive_user(project_root: Path, client_file: Path, token_file: Path) -> None:
    """Run explicit full-Drive consent and create only the dedicated cleanup token."""
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as error:
        raise RuntimeError(
            "Google OAuth dependencies are missing; install job-scout/requirements.txt"
        ) from error
    client_file = client_file.expanduser().resolve()
    token_file = token_file.expanduser().resolve()
    if not client_file.is_file():
        raise RuntimeError(f"Google OAuth client configuration is unavailable: {client_file}")
    if token_file.exists():
        raise RuntimeError(
            f"Refusing to overwrite the existing cleanup token: {token_file}. "
            "Move it aside explicitly before reauthorization."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(client_file), scopes=SCOPES)
    credentials = flow.run_local_server(
        host="localhost", port=0, open_browser=True,
        authorization_prompt_message=(
            "A browser has been opened. Select the Google account that owns "
            "ILT Marketing/Companies and approve full Google Drive access."
        ),
        success_message="Drive cleanup authorization completed. You may close this browser tab.",
        access_type="offline", prompt="consent",
    )
    if not credentials.has_scopes(SCOPES):
        raise RuntimeError("OAuth completed without the required full Google Drive scope")
    token_file.parent.mkdir(parents=True, exist_ok=True)
    with token_file.open("x", encoding="utf-8") as handle:
        handle.write(credentials.to_json())


def auth_diagnostic(project_root: Path, folder_id: str) -> dict[str, Any]:
    kind, path = credential_selection(project_root)
    service = build_drive_service(project_root)
    credentials = service._http.credentials
    about = retry(lambda: service.about().get(fields="user").execute()).get("user", {})
    result: dict[str, Any] = {
        "credential_file": str(path),
        "credential_type": kind,
        "credential_class": type(credentials).__name__,
        "authenticated_identity": about.get("emailAddress") or about.get("displayName"),
        "about_user": {
            key: about.get(key) for key in ("displayName", "emailAddress", "permissionId", "me")
        },
        "granted_scopes": sorted(getattr(credentials, "scopes", None) or []),
    }
    try:
        result["folder"] = retry(lambda: service.files().get(
            fileId=folder_id,
            fields=("id,name,parents,mimeType,trashed,webViewLink,"
                    "capabilities(canListChildren,canAddChildren,canEdit,"
                    "canMoveItemWithinDrive,canMoveChildrenWithinDrive,canTrash)"),
            supportsAllDrives=True,
        ).execute())
        parents = result["folder"].get("parents") or []
        if parents:
            result["parent"] = retry(lambda: service.files().get(
                fileId=parents[0], fields="id,name,mimeType,trashed,webViewLink",
                supportsAllDrives=True,
            ).execute())
        listing = retry(lambda: service.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            spaces="drive", pageSize=1000,
            fields="nextPageToken,files(id)",
            supportsAllDrives=True, includeItemsFromAllDrives=True,
        ).execute())
        result["listing_access"] = {
            "accessible": True,
            "first_page_items": len(listing.get("files", [])),
            "has_next_page": bool(listing.get("nextPageToken")),
        }
    except Exception as error:
        result["folder_error"] = str(error)
    return result


def retriable_error(error: Exception) -> bool:
    status = getattr(getattr(error, "resp", None), "status", None)
    if status in {408, 429, 500, 502, 503, 504}:
        return True
    if isinstance(error, (TimeoutError, ConnectionError, socket.timeout, ssl.SSLError)):
        return True
    message = str(error).casefold()
    return any(fragment in message for fragment in (
        "read operation timed out", "timed out", "temporarily unavailable",
        "connection reset", "connection aborted", "remote end closed connection",
        "server not found", "name resolution",
    ))


def retry(call: Callable[[], Any], *, attempts: int = 5) -> Any:
    delay = 1.0
    for number in range(1, attempts + 1):
        try:
            return call()
        except Exception as error:
            if number == attempts or not retriable_error(error):
                raise
            time.sleep(delay + random.random() * 0.25)
            delay = min(delay * 2, 16)


def normalize_company(name: str) -> str:
    text = name.casefold().strip()
    text = re.sub(r"^dcall[\s_+\-]+", "", text)
    if re.fullmatch(r"grip[\s_-]*6[\s_+\-]+\d{1,2}[\s_.-]+\d{1,2}[\s_.-]+\d{2,4}[\s_+\-]+and[\s_+\-]+on", text):
        return "grip6"
    text = re.sub(r"(?:[\s_+\-]+(?:v(?:ersion)?\s*)?\d+(?:[._-]\d+)*)$", "", text)
    text = re.sub(r"[\s_+\-.,&'()]", "", text)
    text = re.sub(r"(?:from|since)?\d{1,2}\d{1,2}\d{2,4}andon$", "", text)
    for key, aliases in PRIORITY_ALIASES.items():
        if text in aliases:
            return key
    return text


def split_name(name: str) -> tuple[str, str]:
    if name.startswith(".") and name.count(".") == 1:
        return name, ""
    stem, dot, suffix = name.rpartition(".")
    return (stem, dot + suffix) if dot and stem else (name, "")


def allocate_collision_name(name: str, occupied: Iterable[str]) -> str:
    folded = {item.casefold() for item in occupied}
    if name.casefold() not in folded:
        return name
    stem, extension = split_name(name)
    base = re.sub(r"\+\d+$", "", stem)
    number = 1
    while f"{base}+{number}{extension}".casefold() in folded:
        number += 1
    return f"{base}+{number}{extension}"


@dataclass
class Journal:
    path: Path
    completed: dict[str, dict[str, Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            return
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("phase") == "after" and row.get("status") == "confirmed":
                self.completed[row["operation_id"]] = row

    def append(self, data: dict[str, Any]) -> None:
        row = {"time": utc_now(), **data}
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        if row.get("phase") == "after" and row.get("status") == "confirmed":
            self.completed[row["operation_id"]] = row

    def done(self, operation_id: str) -> bool:
        return operation_id in self.completed

    def rows(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [
            json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def pending(self) -> list[dict[str, Any]]:
        before: dict[str, dict[str, Any]] = {}
        for row in self.rows():
            operation_id = row.get("operation_id")
            if operation_id and row.get("phase") == "before":
                before[operation_id] = row
        return [row for operation_id, row in before.items() if operation_id not in self.completed]


@dataclass
class Inventory:
    root_id: str
    items: dict[str, dict[str, Any]] = field(default_factory=dict)
    children: dict[str, list[str]] = field(default_factory=dict)
    failures: list[dict[str, str]] = field(default_factory=list)

    def path(self, item_id: str) -> str:
        names = []
        seen = set()
        current = item_id
        while current and current not in seen:
            seen.add(current)
            item = self.items.get(current)
            if not item:
                break
            names.append(item.get("name", current))
            if current == self.root_id:
                break
            parents = item.get("parents") or []
            current = parents[0] if parents else ""
        return "/".join(reversed(names))


class HashingBuffer(io.BytesIO):
    """Retain downloaded bytes for archive inspection while hashing every chunk."""
    def __init__(self):
        super().__init__()
        self.sha256 = hashlib.sha256()

    def write(self, value: bytes) -> int:
        self.sha256.update(value)
        return super().write(value)


class DriveCleanup:
    def __init__(self, service: Any, root_id: str, journal: Journal, report_dir: Path,
                 *, dry_run: bool = False):
        self.service = service
        self.files = service.files()
        self.root_id = root_id
        self.journal = journal
        self.report_dir = report_dir
        self.dry_run = dry_run
        self.inventory = Inventory(root_id)
        self.results: list[dict[str, Any]] = []
        self.unresolved: list[dict[str, Any]] = []
        self.archive_inventory: dict[str, Any] = {}

    def get(self, file_id: str, fields: str = FIELDS) -> dict[str, Any]:
        return retry(lambda: self.files.get(
            fileId=file_id, fields=fields, supportsAllDrives=True
        ).execute())

    def reconcile_pending_journal(self) -> dict[str, int]:
        """Resolve ambiguous prior outcomes by readback before any new mutation."""
        recovered = retryable = 0
        ambiguous: list[str] = []
        for record in self.journal.pending():
            action = record.get("action")
            file_id = str(record.get("file_id") or "")
            if not file_id or action not in {"move", "trash"}:
                ambiguous.append(f"{record.get('operation_id')}: unsupported pending action")
                continue
            current = self.get(file_id, "id,name,parents,trashed,modifiedTime,version")
            if action == "move":
                source = str(record.get("source_parent") or "")
                destination = str(record.get("destination_parent") or "")
                target_name = str(record.get("target_name") or "")
                parents = current.get("parents") or []
                if (destination in parents and source not in parents
                        and current.get("name") == target_name and not current.get("trashed")):
                    self.journal.append({
                        "operation_id": record["operation_id"], "phase": "after",
                        "status": "confirmed", "action": "move", "recovered": True,
                        "recovery_reason": "fresh Drive readback matched the intended final state",
                        "file_id": file_id, "before": record.get("before"),
                        "source_parent": source, "destination_parent": destination,
                        "final": current,
                    })
                    recovered += 1
                    continue
                before = record.get("before") or {}
                if (source in parents and destination not in parents
                        and current.get("name") == before.get("name") and not current.get("trashed")):
                    retryable += 1
                    continue
                ambiguous.append(
                    f"{record['operation_id']}: current move state does not match before or intended after"
                )
            else:
                if current.get("trashed"):
                    self.journal.append({
                        "operation_id": record["operation_id"], "phase": "after",
                        "status": "confirmed", "action": "trash", "recovered": True,
                        "recovery_reason": "fresh Drive readback confirmed trashed=true",
                        "file_id": file_id, "before": record.get("before"),
                        "reason": record.get("reason"), "final": current,
                    })
                    recovered += 1
                else:
                    retryable += 1
        if ambiguous:
            raise RuntimeError(
                "Pending journal reconciliation found ambiguous Drive state; no new mutation was attempted:\n- "
                + "\n- ".join(ambiguous)
            )
        return {"recovered": recovered, "retryable": retryable}

    def mutation_with_readback(
        self, mutate: Callable[[], Any], readback: Callable[[], dict[str, Any]],
        after_matches: Callable[[dict[str, Any]], bool],
        before_matches: Callable[[dict[str, Any]], bool], *, attempts: int = 5,
    ) -> dict[str, Any]:
        """Retry a mutation only after readback proves the prior attempt did not finish."""
        delay = 1.0
        for number in range(1, attempts + 1):
            try:
                mutate()
            except Exception as error:
                if not retriable_error(error):
                    raise
                try:
                    current = retry(readback)
                except Exception as readback_error:
                    raise RuntimeError(
                        "Drive mutation outcome is unknown because fresh readback failed; "
                        "the pending journal entry was preserved and the mutation was not retried"
                    ) from readback_error
                if after_matches(current):
                    return current
                if not before_matches(current):
                    raise RuntimeError(
                        "Drive mutation outcome is ambiguous because fresh metadata matches "
                        "neither the original before-state nor the intended after-state; "
                        "the pending journal entry was preserved and the mutation was not retried"
                    ) from error
                if number == attempts:
                    raise
                time.sleep(delay + random.random() * 0.25)
                delay = min(delay * 2, 16)
                continue
            try:
                current = retry(readback)
            except Exception as readback_error:
                raise RuntimeError(
                    "Drive mutation returned but confirmation readback failed; the pending "
                    "journal entry was preserved and the mutation was not retried"
                ) from readback_error
            if after_matches(current):
                return current
            if not before_matches(current):
                raise RuntimeError(
                    "Drive mutation confirmation is ambiguous because fresh metadata matches "
                    "neither the original before-state nor the intended after-state; "
                    "the pending journal entry was preserved and the mutation was not retried"
                )
            if number == attempts:
                raise RuntimeError("Drive mutation completed without the expected readback state")
            time.sleep(delay + random.random() * 0.25)
            delay = min(delay * 2, 16)
        raise AssertionError("unreachable mutation retry state")

    def list_children(self, folder_id: str) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        token = None
        while True:
            response = retry(lambda token=token: self.files.list(
                q=f"'{folder_id}' in parents and trashed = false",
                spaces="drive", pageSize=1000, pageToken=token,
                fields=f"nextPageToken,files({FIELDS})",
                supportsAllDrives=True, includeItemsFromAllDrives=True,
            ).execute())
            output.extend(response.get("files", []))
            token = response.get("nextPageToken")
            if not token:
                return output

    def build_inventory(self) -> Inventory:
        root = self.get(self.root_id)
        if root.get("mimeType") != FOLDER_MIME or root.get("trashed"):
            raise RuntimeError("The verified target ID is not an active Drive folder")
        self.inventory.items[self.root_id] = root
        queue = [self.root_id]
        while queue:
            folder_id = queue.pop(0)
            try:
                children = self.list_children(folder_id)
            except Exception as error:
                self.inventory.failures.append({
                    "folder_id": folder_id,
                    "path": self.inventory.path(folder_id),
                    "error": str(error),
                })
                continue
            self.inventory.children[folder_id] = []
            for item in children:
                item_id = item["id"]
                self.inventory.items[item_id] = item
                self.inventory.children[folder_id].append(item_id)
                if item.get("mimeType") == FOLDER_MIME:
                    queue.append(item_id)
        return self.inventory

    def save_inventory(self) -> None:
        self.report_dir.mkdir(parents=True, exist_ok=True)
        rows = []
        for item_id, item in self.inventory.items.items():
            rows.append({**item, "originalPath": self.inventory.path(item_id)})
        payload = {
            "root_id": self.root_id,
            "completed_at": utc_now(),
            "failures": self.inventory.failures,
            "items": rows,
        }
        (self.report_dir / "inventory.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        fields = ["id", "originalPath", "name", "mimeType", "size", "version",
                  "createdTime", "modifiedTime", "md5Checksum", "sha1Checksum",
                  "sha256Checksum", "parents", "shortcutDetails", "permissions"]
        with (self.report_dir / "inventory.csv").open("w", encoding="utf-8-sig", newline="") as h:
            writer = csv.DictWriter(h, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
                                 for k, v in row.items()})

    def _record(self, action: str, item: dict[str, Any], **extra: Any) -> None:
        self.results.append({
            "action": action, "file_id": item.get("id"), "name": item.get("name"), **extra
        })

    def top_level_groups(self) -> dict[str, list[dict[str, Any]]]:
        groups: dict[str, list[dict[str, Any]]] = {}
        for item_id in self.inventory.children.get(self.root_id, []):
            item = self.inventory.items[item_id]
            if item.get("mimeType") != FOLDER_MIME:
                continue
            key = normalize_company(item.get("name", ""))
            if key:
                groups.setdefault(key, []).append(item)
        return groups

    @staticmethod
    def choose_canonical(key: str, folders: list[dict[str, Any]]) -> dict[str, Any]:
        preferred = [x.casefold() for x in DISPLAY_NAMES.get(key, ())]
        def rank(item: dict[str, Any]) -> tuple[int, str, str]:
            name = item.get("name", "")
            try:
                priority = preferred.index(name.casefold())
            except ValueError:
                priority = len(preferred) + (1 if re.search(r"(?:v|version)[ _-]*\d+$", name, re.I) else 0)
            return priority, item.get("createdTime", ""), item["id"]
        return min(folders, key=rank)

    def _permission_signature(self, item: dict[str, Any]) -> tuple[tuple[str, str, str], ...]:
        return tuple(sorted((str(p.get("id", "")), str(p.get("type", "")), str(p.get("role", "")))
                            for p in item.get("permissions") or [] if not p.get("deleted")))

    def permission_safe(self, source_parent: str, destination_parent: str) -> tuple[bool, str]:
        source = self.get(source_parent, "id,permissions(id,type,role,deleted)")
        destination = self.get(destination_parent, "id,permissions(id,type,role,deleted)")
        if self._permission_signature(source) != self._permission_signature(destination):
            return False, "source and destination parent permissions differ"
        return True, "same effective parent permission identities and roles"

    def names_in(self, folder_id: str) -> list[str]:
        return [item.get("name", "") for item in self.list_children(folder_id)]

    def move(self, item: dict[str, Any], source_parent: str, destination_parent: str,
             *, requested_name: str | None = None) -> dict[str, Any] | None:
        operation_id = f"move:{item['id']}:{source_parent}:{destination_parent}"
        if self.journal.done(operation_id):
            return self.get(item["id"])
        current = self.get(item["id"])
        parents = current.get("parents") or []
        if destination_parent in parents and source_parent not in parents:
            self.journal.append({"operation_id": operation_id, "phase": "after",
                                 "status": "confirmed", "action": "move", "recovered": True,
                                 "file_id": item["id"], "final": current})
            return current
        if source_parent not in parents:
            self._record("skipped", item, reason="source parent changed before move")
            return None
        safe, reason = self.permission_safe(source_parent, destination_parent)
        if not safe:
            self._record("skipped", item, reason=reason)
            return None
        target_name = allocate_collision_name(requested_name or current["name"], self.names_in(destination_parent))
        before = {"id": current["id"], "name": current["name"], "parents": parents,
                  "modifiedTime": current.get("modifiedTime"), "version": current.get("version")}
        self.journal.append({"operation_id": operation_id, "phase": "before", "action": "move",
                             "file_id": item["id"], "source_parent": source_parent,
                             "destination_parent": destination_parent, "before": before,
                             "target_name": target_name})
        if self.dry_run:
            self._record("would_move", item, destination_parent=destination_parent, new_name=target_name)
            return current
        def readback() -> dict[str, Any]:
            return self.files.get(
                fileId=item["id"], fields=FIELDS, supportsAllDrives=True
            ).execute()

        def after_matches(value: dict[str, Any]) -> bool:
            parents_after = value.get("parents") or []
            return (destination_parent in parents_after and source_parent not in parents_after
                    and value.get("name") == target_name and not value.get("trashed"))

        def before_matches(value: dict[str, Any]) -> bool:
            if value.get("name") != before["name"] or bool(value.get("trashed")):
                return False
            if set(value.get("parents") or []) != set(before["parents"]):
                return False
            return all(
                before.get(field) is None or value.get(field) == before.get(field)
                for field in ("modifiedTime", "version")
            )

        verified = self.mutation_with_readback(
            lambda: self.files.update(
                fileId=item["id"], addParents=destination_parent, removeParents=source_parent,
                body={"name": target_name}, fields=FIELDS, supportsAllDrives=True,
            ).execute(),
            readback, after_matches, before_matches,
        )
        self.journal.append({"operation_id": operation_id, "phase": "after", "status": "confirmed",
                             "action": "move", "file_id": item["id"], "before": before,
                             "source_parent": source_parent, "destination_parent": destination_parent,
                             "final": verified})
        self._record("moved", item, destination_parent=destination_parent,
                     old_name=current["name"], new_name=target_name)
        return verified

    def merge_folder(self, source: dict[str, Any], destination: dict[str, Any]) -> None:
        try:
            source_children = self.list_children(source["id"])
            destination_children = self.list_children(destination["id"])
        except Exception as error:
            self._record("skipped_folder", source, reason=f"fresh listing failed: {error}")
            return
        destination_folders = {
            child["name"].casefold(): child for child in destination_children
            if child.get("mimeType") == FOLDER_MIME
        }
        for child in source_children:
            if child.get("mimeType") == FOLDER_MIME and child["name"].casefold() in destination_folders:
                self.merge_folder(child, destination_folders[child["name"].casefold()])
                self.trash_empty_folder(child)
            else:
                self.move(child, source["id"], destination["id"])

    def _loose_company_key(self, name: str, known: set[str]) -> str | None:
        stem = split_name(name)[0]
        normalized = normalize_company(stem)
        for key in known:
            aliases = PRIORITY_ALIASES.get(key, {key})
            patterns = [re.escape(alias) for alias in aliases | {key} if len(alias) >= 3]
            collapsed = re.sub(r"[^a-z0-9]+", "", stem.casefold())
            if any(re.match(rf"^(?:dcall)?{p}(?:\d|v\d|report|marketing|_|-|$)", collapsed)
                   for p in patterns):
                return key
        return normalized if normalized in known else None

    def consolidate(self) -> dict[str, dict[str, Any]]:
        groups = self.top_level_groups()
        canonicals: dict[str, dict[str, Any]] = {}
        for key, folders in groups.items():
            if len(folders) == 1:
                canonicals[key] = folders[0]
                continue
            # Non-priority grouping is allowed only for an exact normalized alias.
            canonical = self.choose_canonical(key, folders)
            canonicals[key] = canonical
            for source in folders:
                if source["id"] == canonical["id"]:
                    continue
                self.merge_folder(source, canonical)
                self.trash_empty_folder(source)
        for item_id in list(self.inventory.children.get(self.root_id, [])):
            item = self.inventory.items[item_id]
            if item.get("mimeType") == FOLDER_MIME:
                continue
            key = self._loose_company_key(item.get("name", ""), set(canonicals))
            if key and key in canonicals:
                self.move(item, self.root_id, canonicals[key]["id"])
            else:
                self.unresolved.append({"id": item["id"], "path": self.inventory.path(item["id"]),
                                        "reason": "loose file company assignment is ambiguous"})
        return canonicals

    def trash_empty_folder(self, folder: dict[str, Any]) -> None:
        operation_id = f"trash-folder:{folder['id']}"
        if self.journal.done(operation_id):
            return
        try:
            remaining = self.list_children(folder["id"])
        except Exception as error:
            self._record("skipped_folder", folder, reason=f"fresh empty check failed: {error}")
            return
        if remaining:
            self._record("kept_folder", folder, reason=f"not empty ({len(remaining)} visible items)")
            return
        self._trash(folder, operation_id, reason="fresh complete listing confirmed empty")

    def download_hash(self, item: dict[str, Any]) -> tuple[str, bytes]:
        if item.get("mimeType", "").startswith(NATIVE_PREFIX):
            raise ValueError("native Google files require unsupported full-structure comparison")
        request = self.files.get_media(fileId=item["id"], supportsAllDrives=True)
        try:
            from googleapiclient.http import MediaIoBaseDownload
        except ImportError as error:
            raise RuntimeError("google-api-python-client is required") from error
        stream = HashingBuffer()
        downloader = MediaIoBaseDownload(stream, request, chunksize=8 * 1024 * 1024)
        done = False
        while not done:
            _, done = retry(lambda: downloader.next_chunk())
        data = stream.getvalue()
        expected = item.get("size")
        if expected is not None and int(expected) != len(data):
            raise RuntimeError(f"complete download size mismatch for {item['id']}")
        return stream.sha256.hexdigest(), data

    def inspect_archive(self, item: dict[str, Any], data: bytes) -> None:
        if item.get("mimeType") != "application/zip" and not item.get("name", "").casefold().endswith(".zip"):
            return
        try:
            members = []
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                for info in archive.infolist():
                    path = PurePosixPath(info.filename.replace("\\", "/"))
                    unsafe = path.is_absolute() or ".." in path.parts
                    digest = None
                    if not info.is_dir() and not unsafe:
                        with archive.open(info, "r") as member:
                            sha = hashlib.sha256()
                            while chunk := member.read(1024 * 1024):
                                sha.update(chunk)
                            digest = sha.hexdigest()
                    members.append({"name": info.filename, "size": info.file_size,
                                    "compressed_size": info.compress_size, "crc": info.CRC,
                                    "sha256": digest, "unsafe_path": unsafe})
            self.archive_inventory[item["id"]] = members
        except (zipfile.BadZipFile, OSError, RuntimeError) as error:
            self.unresolved.append({"id": item["id"], "reason": f"archive inspection failed: {error}"})

    def descendants(self, folder_id: str) -> list[dict[str, Any]]:
        output = []
        queue = [folder_id]
        while queue:
            current = queue.pop(0)
            children = self.list_children(current)
            for child in children:
                output.append(child)
                if child.get("mimeType") == FOLDER_MIME:
                    queue.append(child["id"])
        return output

    def comments_or_history_unsafe(self, item: dict[str, Any]) -> tuple[bool, str]:
        comments = retry(lambda: self.files.list(
            q=f"'{item['id']}' in parents", pageSize=1, fields="files(id)"
        ).execute()) if False else None  # Comments use a different resource; kept explicit below.
        try:
            response = retry(lambda: self.service.comments().list(
                fileId=item["id"], pageSize=1, fields="nextPageToken,comments(id,deleted)"
            ).execute())
            if any(not comment.get("deleted") for comment in response.get("comments", [])):
                return True, "file has comments"
        except Exception as error:
            return True, f"comments could not be verified: {error}"
        try:
            response = retry(lambda: self.service.revisions().list(
                fileId=item["id"], pageSize=2, fields="nextPageToken,revisions(id)"
            ).execute())
            if len(response.get("revisions", [])) > 1 or response.get("nextPageToken"):
                return True, "file has distinct revision history"
        except Exception as error:
            return True, f"revision history could not be verified: {error}"
        return False, "no comments or multi-revision history observed"

    def changed(self, before: dict[str, Any], now: dict[str, Any]) -> bool:
        keys = ("name", "size", "version", "modifiedTime", "md5Checksum", "sha256Checksum", "parents")
        return any(before.get(key) != now.get(key) for key in keys)

    def known_shortcut_references(self, file_id: str) -> list[str]:
        return sorted(
            item["id"] for item in self.inventory.items.values()
            if item.get("mimeType") == SHORTCUT_MIME
            and (item.get("shortcutDetails") or {}).get("targetId") == file_id
        )

    def deduplicate(self, canonicals: dict[str, dict[str, Any]]) -> None:
        for company, canonical in canonicals.items():
            try:
                items = [x for x in self.descendants(canonical["id"])
                         if x.get("mimeType") != FOLDER_MIME]
            except Exception as error:
                self.unresolved.append({"company": company, "reason": f"dedupe listing failed: {error}"})
                continue
            by_size: dict[str, list[dict[str, Any]]] = {}
            for item in items:
                if item.get("mimeType", "").startswith(NATIVE_PREFIX):
                    self.unresolved.append({"id": item["id"], "company": company,
                                            "reason": "native full-structure equality unsupported; preserved"})
                    continue
                by_size.setdefault(str(item.get("size", "unknown")), []).append(item)
            for candidates in by_size.values():
                if len(candidates) < 2:
                    # ZIP member evidence is still recorded even without a candidate.
                    if candidates and candidates[0].get("mimeType") == "application/zip":
                        try:
                            _, data = self.download_hash(candidates[0])
                            self.inspect_archive(candidates[0], data)
                        except Exception as error:
                            self.unresolved.append({"id": candidates[0]["id"], "reason": str(error)})
                    continue
                hashed: dict[str, list[tuple[dict[str, Any], bytes]]] = {}
                for item in candidates:
                    try:
                        digest, data = self.download_hash(item)
                        self.inspect_archive(item, data)
                        hashed.setdefault(digest, []).append((item, data))
                    except Exception as error:
                        self.unresolved.append({"id": item["id"], "reason": f"content unverified: {error}"})
                for digest, matches in hashed.items():
                    if len(matches) < 2:
                        continue
                    canonical_path = self.inventory.path(canonical["id"])
                    ordered = sorted(
                        (pair[0] for pair in matches),
                        key=lambda x: (
                            0 if self.inventory.path(x["id"]).startswith(canonical_path + "/") else 1,
                            x.get("createdTime", ""), x["id"],
                        ),
                    )
                    retained = ordered[0]
                    for duplicate in ordered[1:]:
                        references = self.known_shortcut_references(duplicate["id"])
                        if references:
                            self._record("kept_duplicate", duplicate,
                                         reason="known shortcut reference(s): " + ", ".join(references),
                                         sha256=digest)
                            continue
                        if self._permission_signature(retained) != self._permission_signature(duplicate):
                            self._record("kept_duplicate", duplicate, reason="distinct permissions", sha256=digest)
                            continue
                        unsafe, reason = self.comments_or_history_unsafe(duplicate)
                        if unsafe:
                            self._record("kept_duplicate", duplicate, reason=reason, sha256=digest)
                            continue
                        retained_now = self.get(retained["id"])
                        duplicate_now = self.get(duplicate["id"])
                        if self.changed(retained, retained_now) or self.changed(duplicate, duplicate_now):
                            try:
                                keep_hash, _ = self.download_hash(retained_now)
                                duplicate_hash, _ = self.download_hash(duplicate_now)
                            except Exception as error:
                                self._record("kept_duplicate", duplicate, reason=f"changed-file recheck failed: {error}")
                                continue
                            if keep_hash != duplicate_hash:
                                self._record("kept_duplicate", duplicate, reason="content changed after comparison")
                                continue
                        self._trash(duplicate_now, f"trash-duplicate:{duplicate['id']}",
                                    reason="complete byte streams have identical SHA-256",
                                    retained_id=retained["id"], sha256=digest)

    def _trash(self, item: dict[str, Any], operation_id: str, *, reason: str, **extra: Any) -> None:
        if self.journal.done(operation_id):
            return
        before = {k: item.get(k) for k in ("id", "name", "parents", "modifiedTime", "version",
                                            "size", "mimeType", "permissions")}
        self.journal.append({"operation_id": operation_id, "phase": "before", "action": "trash",
                             "file_id": item["id"], "before": before, "reason": reason, **extra})
        if self.dry_run:
            self._record("would_trash", item, reason=reason, **extra)
            return
        fields = "id,name,parents,trashed,modifiedTime,version"
        verified = self.mutation_with_readback(
            lambda: self.files.update(
                fileId=item["id"], body={"trashed": True}, fields=fields,
                supportsAllDrives=True,
            ).execute(),
            lambda: self.files.get(
                fileId=item["id"], fields=fields, supportsAllDrives=True
            ).execute(),
            lambda value: bool(value.get("trashed")),
            lambda value: (
                not bool(value.get("trashed"))
                and value.get("name") == before.get("name")
                and set(value.get("parents") or []) == set(before.get("parents") or [])
                and all(
                    before.get(field) is None or value.get(field) == before.get(field)
                    for field in ("modifiedTime", "version")
                )
            ),
        )
        self.journal.append({"operation_id": operation_id, "phase": "after", "status": "confirmed",
                             "action": "trash", "file_id": item["id"], "before": before,
                             "reason": reason, "final": verified, **extra})
        self._record("trashed", item, reason=reason, **extra)

    def verify_tree(self) -> dict[str, Any]:
        verification = Inventory(self.root_id)
        original = self.inventory
        self.inventory = verification
        try:
            self.build_inventory()
        finally:
            result = self.inventory
            self.inventory = original
        return {"verified_at": utc_now(), "item_count": len(result.items),
                "failures": result.failures,
                "paths": {item_id: result.path(item_id) for item_id in result.items}}

    def restore(self) -> None:
        records = list(self.journal.completed.values())
        for record in reversed(records):
            restore_id = f"restore:{record['operation_id']}"
            if self.journal.done(restore_id):
                continue
            before = record.get("before") or {}
            file_id = record["file_id"]
            self.journal.append({"operation_id": restore_id, "phase": "before", "action": "restore",
                                 "file_id": file_id, "source_operation": record["operation_id"]})
            if record.get("action") == "trash":
                retry(lambda: self.files.update(fileId=file_id, body={"trashed": False},
                                                fields="id,name,parents,trashed",
                                                supportsAllDrives=True).execute())
            elif record.get("action") == "move":
                current = self.get(file_id)
                destination = record["destination_parent"]
                source = record["source_parent"]
                retry(lambda: self.files.update(
                    fileId=file_id, addParents=source,
                    removeParents=destination if destination in (current.get("parents") or []) else None,
                    body={"name": before.get("name", current.get("name"))},
                    fields="id,name,parents,trashed", supportsAllDrives=True,
                ).execute())
            verified = self.get(file_id, "id,name,parents,trashed")
            self.journal.append({"operation_id": restore_id, "phase": "after", "status": "confirmed",
                                 "action": "restore", "file_id": file_id, "final": verified,
                                 "source_operation": record["operation_id"]})

    def write_report(self, canonicals: dict[str, dict[str, Any]], verification: dict[str, Any]) -> None:
        self.report_dir.mkdir(parents=True, exist_ok=True)
        payload = {"completed_at": utc_now(), "dry_run": self.dry_run,
                   "root_id": self.root_id, "canonicals": canonicals,
                   "operations": self.results, "unresolved": self.unresolved,
                   "archives": self.archive_inventory, "verification": verification}
        (self.report_dir / "cleanup-results.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        with (self.report_dir / "operations.csv").open("w", encoding="utf-8-sig", newline="") as h:
            columns = ["action", "file_id", "name", "old_name", "new_name", "destination_parent",
                       "retained_id", "sha256", "reason"]
            writer = csv.DictWriter(h, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(self.results)
        counts: dict[str, int] = {}
        for row in self.results:
            counts[row["action"]] = counts.get(row["action"], 0) + 1
        lines = ["# Google Drive company cleanup", "", f"Target folder ID: `{self.root_id}`",
                 f"Mode: {'dry run' if self.dry_run else 'live'}", "", "## Canonical companies", ""]
        for key, item in sorted(canonicals.items()):
            lines.append(f"- {key}: [{item['name']}](https://drive.google.com/drive/folders/{item['id']})")
        lines += ["", "## Confirmed operation counts", ""]
        lines += [f"- {key}: {value}" for key, value in sorted(counts.items())] or ["- None"]
        lines += ["", "## Unresolved or preserved", "",
                  f"- {len(self.unresolved)} item(s); see `cleanup-results.json`.", "",
                  "## Verification", "",
                  f"- Items visible after execution: {verification.get('item_count', 0)}",
                  f"- Incomplete branches: {len(verification.get('failures', []))}", "",
                  "## Restoration", "",
                  f"Run `python scripts/consolidate_drive_companies.py --folder-id {self.root_id} "
                  f"--journal \"{self.journal.path}\" --restore`. Trash is never emptied.", ""]
        (self.report_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder-id", default=DEFAULT_FOLDER_ID)
    parser.add_argument("--journal", type=Path,
                        default=Path("scratch/drive-companies-cleanup/execution-journal.jsonl"))
    parser.add_argument("--report-dir", type=Path,
                        default=Path("scratch/drive-companies-cleanup"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--restore", action="store_true")
    parser.add_argument("--diagnose-auth", action="store_true",
                        help="Print safe credential, identity, scope, and target-folder diagnostics")
    parser.add_argument("--authorize", action="store_true",
                        help="Launch user OAuth consent for a separate full-Drive cleanup token")
    parser.add_argument("--oauth-client-file", type=Path,
                        default=Path(".secrets/gmail-oauth-client.json"))
    parser.add_argument("--oauth-token-file", type=Path,
                        default=Path(".secrets/drive-cleanup-token.json"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    journal = Journal((root / args.journal).resolve() if not args.journal.is_absolute() else args.journal)
    report_dir = (root / args.report_dir).resolve() if not args.report_dir.is_absolute() else args.report_dir
    try:
        if args.authorize:
            client_file = ((root / args.oauth_client_file).resolve()
                           if not args.oauth_client_file.is_absolute() else args.oauth_client_file)
            token_file = ((root / args.oauth_token_file).resolve()
                          if not args.oauth_token_file.is_absolute() else args.oauth_token_file)
            authorize_drive_user(root, client_file, token_file)
            print(json.dumps({"authorized": True, "token_file": str(token_file),
                              "scopes": SCOPES}, indent=2))
            return 0
        if args.diagnose_auth:
            print(json.dumps(auth_diagnostic(root, args.folder_id), indent=2))
            return 0
        service = build_drive_service(root)
        cleanup = DriveCleanup(service, args.folder_id, journal, report_dir, dry_run=args.dry_run)
        if args.restore:
            cleanup.restore()
            return 0
        recovery = cleanup.reconcile_pending_journal()
        if recovery["recovered"] or recovery["retryable"]:
            print(json.dumps({"journal_reconciliation": recovery}, sort_keys=True), flush=True)
        inventory = cleanup.build_inventory()
        cleanup.save_inventory()
        if inventory.failures:
            cleanup.write_report({}, {"item_count": len(inventory.items), "failures": inventory.failures})
            raise RuntimeError(
                f"Inventory incomplete in {len(inventory.failures)} branch(es); no Drive changes were made"
            )
        canonicals = cleanup.consolidate()
        cleanup.deduplicate(canonicals)
        verification = cleanup.verify_tree() if not args.dry_run else {
            "item_count": len(inventory.items), "failures": [], "dry_run": True
        }
        cleanup.write_report(canonicals, verification)
        if verification.get("failures"):
            raise RuntimeError("Post-execution verification has incomplete branches; see report")
        return 0
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
