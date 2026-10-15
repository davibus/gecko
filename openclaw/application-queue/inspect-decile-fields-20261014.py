from current_batch_ui import UI
from pathlib import Path
import json
Q=Path('/mnt/c/gecko_main/openclaw/application-queue');e=json.loads((Q/'721/submission-result.json').read_text());u=UI(e['targetId']);s=u.snap();print(json.dumps(s),flush=True)
