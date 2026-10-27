from recover_gecko_pending import *
from sources.http import get_json
scout.load_local_environment()
balance=get_json('https://api.firecrawl.dev/v2/team/credit-usage',{'Authorization':'Bearer '+os.environ['FIRECRAWL_API_KEY']})
if balance.get('success') is not True:raise RuntimeError('Provider balance unavailable')
with run_lock():
    history=History()
    with history.connect() as con:settled=con.execute('SELECT COALESCE(SUM(confirmed),0) FROM requests').fetchone()[0]
    history.record_balance(balance['data'],settled_before=settled)
    final=json.loads((OUT/'final-verification.json').read_text());final.update(firecrawl_balance=balance,balance_verified_at=datetime.now(timezone.utc).isoformat(),ledger_after=history.usage())
    save('final-verification.json',final);save('firecrawl-balance-final.json',balance)
    live=json.loads((OUT/'live.json').read_text());live['firecrawl_usage']=history.usage();save('live.json',live)
    (ROOT/'reports/discovery/live-status.json').write_text(json.dumps(live,indent=2),encoding='utf-8')
print(json.dumps({'remaining_credits':balance['data']['remainingCredits'],'prior_unresolved_credits':history.usage()['estimated_or_reserved_credits']}))
