"""Prepare the audited guard without changing an active workflow."""
import ast
from pathlib import Path
root=Path(__file__).resolve().parents[1]
source=(root/'work/recover_gecko_pending.py').read_text(encoding='utf-8')
tree=ast.parse(source)
functions=[ast.get_source_segment(source,node) for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in ('source_location_blocker','location_blocker')]
text='"""Eligibility from explicit source evidence; unknown facts stay unknown."""\nimport json\nimport re\nfrom pathlib import Path\n\n'+'\n\n'.join(functions)
text=text.replace("(OUT/'country-regions.json')","(Path(__file__).with_name('country-regions.json'))")
(root/'work/prepared_location_evidence.py').write_text(text,encoding='utf-8')
print('Prepared audited guard; active workflow unchanged')
