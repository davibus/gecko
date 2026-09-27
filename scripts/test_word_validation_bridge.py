from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
POWERSHELL = "powershell.exe"


def run_powershell(script: Path, *args: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            POWERSHELL,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            *args,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


class WordValidationBridgeTests(unittest.TestCase):
    def test_powershell_files_parse(self):
        files = sorted(SCRIPTS.glob("*.ps1"))
        quoted = ",".join("'" + str(path).replace("'", "''") + "'" for path in files)
        command = textwrap.dedent(
            f"""
            $failed = $false
            foreach ($path in @({quoted})) {{
                $tokens = $null
                $errors = $null
                [void][System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$errors)
                if ($errors.Count -gt 0) {{
                    $failed = $true
                    $errors | ForEach-Object {{ Write-Error "${{path}}: $($_.Message)" }}
                }}
            }}
            if ($failed) {{ exit 1 }}
            """
        )
        completed = subprocess.run(
            [POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", command],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)

    def test_only_authoritative_validator_implements_pagination(self):
        implementations = []
        for path in SCRIPTS.iterdir():
            if path.suffix.lower() not in {".py", ".ps1"}:
                continue
            if path.name.startswith("test_"):
                continue
            text = path.read_text(encoding="utf-8-sig", errors="replace")
            if "ComputeStatistics(2)" in text or "ExportAsFixedFormat" in text:
                implementations.append(path.name)
        self.assertEqual(implementations, ["validate_word_native.ps1"])

    def test_installer_is_hidden_durable_and_self_healing(self):
        installer = (SCRIPTS / "install_word_validation_bridge.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("-AtLogOn", installer)
        self.assertIn("-WindowStyle Hidden", installer)
        self.assertIn("-RestartCount 999", installer)
        self.assertIn("-StartWhenAvailable", installer)
        self.assertIn("word_validation_bridge_watchdog.ps1", installer)
        for command in ("Install-Gecko-Word-Bridge.cmd", "Restart-Gecko-Word-Bridge.cmd"):
            content = (SCRIPTS / command).read_text(encoding="utf-8-sig").lower()
            self.assertNotIn("pause", content)
            self.assertNotIn("start powershell", content)

    def test_validator_never_controls_the_scheduled_task(self):
        validator = (SCRIPTS / "validate_word_native.ps1").read_text(encoding="utf-8-sig")
        self.assertNotIn("Start-ScheduledTask", validator)
        self.assertNotIn("Stop-ScheduledTask", validator)
        self.assertIn("Test-Gecko-Word-Bridge.ps1", validator)
        self.assertIn("300", validator)

    def test_fresh_and_stale_heartbeat_detection(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "scratch") as raw:
            directory = Path(raw)
            probe = directory / "probe.ps1"
            heartbeat = directory / "heartbeat.json"
            common = SCRIPTS / "word_bridge_common.ps1"
            probe.write_text(
                textwrap.dedent(
                    f"""
                    . '{str(common).replace("'", "''")}'
                    $process = Get-Process -Id $PID
                    $value = [ordered]@{{
                        status = 'running'
                        process_id = $PID
                        process_started_at = ([DateTimeOffset]$process.StartTime).ToString('o')
                        user = 'TEST\\InteractiveUser'
                        updated_at = (Get-Date).ToString('o')
                    }}
                    Write-GeckoJsonAtomic -Value $value -Path '{str(heartbeat).replace("'", "''")}'
                    if (-not (Test-GeckoBridgeHeartbeatHealthy -Path '{str(heartbeat).replace("'", "''")}' -RequireLiveProcess)) {{ exit 2 }}
                    $value.updated_at = (Get-Date).AddMinutes(-10).ToString('o')
                    Write-GeckoJsonAtomic -Value $value -Path '{str(heartbeat).replace("'", "''")}'
                    if (Test-GeckoBridgeHeartbeatHealthy -Path '{str(heartbeat).replace("'", "''")}' -RequireLiveProcess) {{ exit 3 }}
                    """
                ),
                encoding="utf-8",
            )
            completed = run_powershell(probe)
            self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)

    def test_request_response_handoff_and_cleanup(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "scratch") as raw:
            scratch = Path(raw)
            request_dir = scratch / "job"
            request_dir.mkdir()
            fake_validator = scratch / "fake-validator.ps1"
            fake_validator.write_text(
                textwrap.dedent(
                    """
                    param(
                        [string]$DocxPath,
                        [string]$PdfPath,
                        [string]$ResultPath,
                        [string]$RequestId,
                        [switch]$InteractiveWorker
                    )
                    [ordered]@{
                        status = 'native-valid'
                        docx = $DocxPath
                        pdf = $PdfPath
                        word_pages = 2
                        pdf_pages = 2
                        request_id = $RequestId
                    } | ConvertTo-Json | Set-Content -LiteralPath $ResultPath -Encoding UTF8
                    """
                ),
                encoding="utf-8",
            )
            result = request_dir / "validation-status.json"
            response = request_dir / "interactive-word-validation-response.json"
            request = request_dir / "interactive-word-validation-request.json"
            request.write_text(
                json.dumps(
                    {
                        "request_id": "handoff-test",
                        "docx": str(request_dir / "resume.docx"),
                        "pdf": str(request_dir / "resume.pdf"),
                        "result": str(result),
                        "response": str(response),
                    }
                ),
                encoding="utf-8",
            )
            completed = run_powershell(
                SCRIPTS / "word_validation_bridge.ps1",
                "-ScratchRoot",
                str(scratch),
                "-ValidatorPath",
                str(fake_validator),
                "-MaximumRequests",
                "1",
                "-PollSeconds",
                "1",
                "-SkipWordComProbe",
                timeout=30,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
            self.assertEqual(json.loads(result.read_text(encoding="utf-8-sig"))["request_id"], "handoff-test")
            self.assertEqual(json.loads(response.read_text(encoding="utf-8-sig"))["status"], "complete")
            self.assertFalse(request.exists())
            self.assertFalse((request_dir / "interactive-word-validation-processing.json").exists())


if __name__ == "__main__":
    unittest.main()
