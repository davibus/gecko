"""Read eligible native Windows Chrome tabs through Gecko Main's browser node."""

import json
from pathlib import Path
import subprocess
import sys


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    settings = json.loads((root / "openclaw/windows-browser-node.json").read_text())
    request = {"method": "GET", "path": "/tabs", "profile": settings["browser_profile"]}
    completed = subprocess.run(
        [
            "/home/dcall/.openclaw/bin/openclaw", "nodes", "invoke",
            "--node", settings["node_id"], "--command", "browser.proxy",
            "--params", json.dumps(request), "--invoke-timeout", "60000",
            "--timeout", "70000", "--json",
        ],
        capture_output=True, text=True,
    )
    if completed.returncode:
        print("Windows Chrome tab request failed; inspect the Gateway and browser node connection.", file=sys.stderr)
        return completed.returncode
    try:
        response = json.loads(completed.stdout)
        if not response.get("ok") or response.get("nodeId") != settings["node_id"]:
            raise ValueError("Unexpected node response")
        result = response["payload"]["result"]
        if not isinstance(result.get("tabs"), list):
            raise ValueError("Tab result is incomplete")
    except (ValueError, KeyError, TypeError):
        print("Windows Chrome returned an incomplete or mismatched tab response.", file=sys.stderr)
        return 1
    print(json.dumps({"nodeId": settings["node_id"], "profile": settings["browser_profile"], "tabs": result["tabs"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
