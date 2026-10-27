from recover_gecko_pending import *
from sources.http import get_document
for name in ('api-DU04QWhP.js','index-BVahkhax.js'):
    path=OUT/name
    if not path.exists():path.write_text(get_document('https://apply.remote.com/assets/'+name).body.decode('utf-8'),encoding='utf-8')
    text=path.read_text(encoding='utf-8')
    print(name,len(text))
    for match in re.finditer(r'https?://[^\s"\x27`]+|.{0,90}(?:/jobs/|graphql|job_postings|jobPostings|baseURL).{0,130}',text):
        print(match.group()[:240])
