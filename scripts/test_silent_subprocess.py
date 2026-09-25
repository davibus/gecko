"""Platform behavior for background child processes."""

import unittest
from unittest.mock import patch

import silent_subprocess


class SilentSubprocessTests(unittest.TestCase):
    def test_windows_uses_no_window_flag(self):
        with patch.object(silent_subprocess.os, "name", "nt"), patch.object(
            silent_subprocess.subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True
        ):
            self.assertEqual(silent_subprocess.windows_creationflags(), 0x08000000)

    def test_other_platforms_use_default_flags(self):
        with patch.object(silent_subprocess.os, "name", "posix"):
            self.assertEqual(silent_subprocess.windows_creationflags(), 0)


if __name__ == "__main__":
    unittest.main()
