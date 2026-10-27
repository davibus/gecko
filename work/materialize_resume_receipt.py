"""Download a connector-provided raw file reference and prove exact DOCX delivery."""
import hashlib
import json
from pathlib import Path
import sys
import os
import urllib.request

ROOT=Path('C:/gecko_main')
ident=int(sys.argv[1]);out=Path(os.environ.get('GECKO_CONNECTED_REPORT',str(ROOT/'reports/resume-connected-2985-2991')))
private=out/f'download-{ident}.private.json'
data=json.loads(private.read_text(encoding='utf-8'))
local=Path(data['path']).read_bytes()
with urllib.request.urlopen(data['download_reference']['download_url'],timeout=60) as response:
    raw=response.read(len(local)+1)
if raw!=local:raise ValueError('Drive download does not exactly match the final local DOCX')
(out/f'downloaded-{ident}.docx').write_bytes(raw)
receipt={'path':data['path'],'metadata':data['metadata'],
         'download':{'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}}
(out/f'drive-receipt-{ident}.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
private.unlink()
print(json.dumps({'id':ident,'downloaded_sha256':receipt['download']['sha256'],'bytes':len(raw),'exact_match':True}))
