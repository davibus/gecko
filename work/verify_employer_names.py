"""Read-only free hosted-board evidence for tenant-name fallbacks."""
from recover_gecko_pending import *
from sources.http import get_document
import html
receipts=json.loads((OUT/'verified-jobs.json').read_text())
fresh={(b['platform'],b['identifier'].casefold()):b for b in json.loads((OUT/'additional-boards.json').read_text()) if b['origin']=='fresh authorized index'}
results=[];seen=set()
for receipt in receipts:
    url=receipt['url']
    if not any(receipt['employer'].casefold()==b['identifier'].casefold() for b in fresh.values()):continue
    if receipt['employer'].casefold() in seen:continue
    seen.add(receipt['employer'].casefold())
    path=OUT/('employer-evidence-'+str(receipt['id'])+'.html')
    try:
        if not path.exists():path.write_text(get_document(url).body.decode('utf-8',errors='replace'),encoding='utf-8')
        page=path.read_text(encoding='utf-8')
        titles=re.findall(r'<title[^>]*>(.*?)</title>',page,re.S|re.I)
        names=re.findall(r'"(?:hiringOrganization|companyName)"\s*:\s*(.{0,250})',page)
        company_names=re.findall(r'"hiringOrganization"\s*:\s*\{[^}]*?"name"\s*:\s*"([^"\\]+)"',page)
        resolved=company_names[0] if len(set(company_names))==1 else ''
        if not resolved:
            for title in [html.unescape(v) for v in titles]:
                for prefix in (receipt['title']+' - ',receipt['title']+' | ','Job Application for '+receipt['title']+' at '):
                    if title.startswith(prefix):resolved=title[len(prefix):].strip()
        results.append({'id':receipt['id'],'saved_employer':receipt['employer'],'title_evidence':[html.unescape(v) for v in titles],
            'structured_evidence':names[:2],'verified_employer_names':sorted(set(company_names)),
            'resolved_employer_name':resolved,'source_url':url})
    except Exception as exc:results.append({'id':receipt['id'],'error':str(exc)})
save('employer-name-audit.json',results);print(json.dumps(results,indent=2))
