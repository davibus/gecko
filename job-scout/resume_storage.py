"""Persistent Google Drive storage for completed Gecko resumes."""

from __future__ import annotations

from dataclasses import dataclass
import io
import os
from pathlib import Path
from typing import Any


DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@dataclass(frozen=True)
class ResumeUpload:
    file_id: str
    url: str
    existing: bool


def _drive_service(credentials_file: Path):
    try:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build
    except ImportError as error:
        raise RuntimeError(
            "Google Drive dependencies are missing; install job-scout/requirements.txt"
        ) from error
    credentials = Credentials.from_service_account_file(
        str(credentials_file), scopes=[DRIVE_SCOPE]
    )
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def _escape_query(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _web_url(item: dict[str, Any]) -> str:
    file_id = str(item.get("id") or "").strip()
    url = str(item.get("webViewLink") or "").strip()
    if not file_id:
        raise RuntimeError("Google Drive upload returned no file ID")
    return url or f"https://drive.google.com/file/d/{file_id}/view"


class GoogleDriveResumeStore:
    """Upload once per stable job identity and reuse the same persistent Drive URL."""

    def __init__(self, credentials_file: Path, folder_id: str | None = None, service=None):
        self.folder_id = (folder_id or os.getenv("GOOGLE_DRIVE_RESUME_FOLDER_ID", "")).strip()
        if not self.folder_id:
            raise RuntimeError(
                "Google Drive resume storage is required: set GOOGLE_DRIVE_RESUME_FOLDER_ID "
                "to a folder shared with the Gecko service account"
            )
        self.service = service or _drive_service(credentials_file)

    def publish(self, resume: Path, job_number: str, *, scout_id: int | None = None) -> ResumeUpload:
        resume = Path(resume)
        if not resume.is_file():
            raise ValueError("Final DOCX is missing; Google Drive upload was not attempted")
        if resume.suffix.casefold() != ".docx":
            raise ValueError("Only a completed DOCX can be stored as a Gecko resume")
        stable_job = str(job_number or "").strip()
        if not stable_job:
            raise ValueError("Job Number is required for idempotent resume storage")

        properties = {"geckoJobNumber": stable_job}
        if scout_id is not None:
            properties["geckoScoutId"] = str(scout_id)
        query_parts = [
            f"'{_escape_query(self.folder_id)}' in parents",
            "trashed = false",
            f"appProperties has {{ key='geckoJobNumber' and value='{_escape_query(stable_job)}' }}",
        ]
        try:
            response = self.service.files().list(
                q=" and ".join(query_parts), spaces="drive",
                fields="files(id,name,webViewLink,appProperties)",
                pageSize=10, includeItemsFromAllDrives=True,
                supportsAllDrives=True,
            ).execute()
        except Exception as error:
            raise RuntimeError(f"Could not search Google Drive for an existing resume: {error}") from error
        matches = response.get("files", [])
        if len(matches) > 1:
            raise RuntimeError(
                f"Multiple Google Drive resumes match job {stable_job}; refusing to attach the wrong file"
            )
        if matches:
            item = matches[0]
            stored_scout = str((item.get("appProperties") or {}).get("geckoScoutId") or "")
            if scout_id is not None and stored_scout and stored_scout != str(scout_id):
                raise RuntimeError(
                    f"Google Drive resume for job {stable_job} belongs to Scout ID {stored_scout}; "
                    "refusing to attach it to a different job"
                )
            return ResumeUpload(str(item["id"]), _web_url(item), True)

        try:
            from googleapiclient.http import MediaIoBaseUpload
            media = MediaIoBaseUpload(
                io.BytesIO(resume.read_bytes()), mimetype=DOCX_MIME, resumable=False
            )
            item = self.service.files().create(
                body={
                    "name": resume.name,
                    "parents": [self.folder_id],
                    "mimeType": DOCX_MIME,
                    "appProperties": properties,
                },
                media_body=media,
                fields="id,name,webViewLink,appProperties",
                supportsAllDrives=True,
            ).execute()
        except Exception as error:
            raise RuntimeError(
                f"Resume created but Google Drive upload failed; Resume Link was not updated: {error}"
            ) from error
        return ResumeUpload(str(item.get("id") or ""), _web_url(item), False)
