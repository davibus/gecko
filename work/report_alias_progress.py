from recover_gecko_pending import *
from watch_gecko_search import LABELS
scout.load_local_environment();scout.load_local_environment(ROOT/'.env.google-sheets.local')
remote=GoogleTracker(config=Config.from_environment());stamp=datetime.now(ZONE)
activity='Reconciling verified employer requisition aliases; recounting unique additions'
remote.api.values().update(spreadsheetId=remote.config.spreadsheet_id,range="'Daily Run'!H1:L2",valueInputOption='RAW',
    body={'values':[LABELS,['running','Recounting unique requisitions',activity,stamp.strftime('%m-%d-%Y | %I:%M %p %Z'),stamp.strftime('%m-%d-%Y | %I:%M %p %Z')]]}).execute()
value=json.loads((OUT/'live.json').read_text());value.update(status='running',stage='verified requisition alias reconciliation',activity=activity,checked_at=stamp.isoformat())
save('live.json',value);(ROOT/'reports/discovery/live-status.json').write_text(json.dumps(value,indent=2),encoding='utf-8')
print('Status panel updated')
