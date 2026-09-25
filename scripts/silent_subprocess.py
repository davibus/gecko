"""Process flags for Gecko commands that run without user interaction."""

import os
import subprocess


def windows_creationflags() -> int:
    """Hide a new Windows console; use normal process behavior elsewhere."""
    return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
