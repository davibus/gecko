"""Discover and save only a one-off selection; no daily settings or resume runs."""
import argparse
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'job-scout'))
from impromptu_filters import validate
from run_gecko import run_lock

def main(path):
    import scout
    from preferences import load_preferences
    from google_tracker import GoogleTracker
    import sqlite3
    from storage import JobStore, DEFAULT_DB
    settings=validate(json.loads(path.read_text(encoding='utf-8')))
    scout.load_local_environment()
    scout.load_local_environment(ROOT/'.env.google-sheets.local')
    preferences=load_preferences()
    preferences['_impromptu']=settings
    preferences['_impromptu_known']={}
    with run_lock():
        tracker=GoogleTracker()
        if getattr(tracker,'backend','')!='sqlite':raise ValueError('Impromptu runs require SQLite.')
        with sqlite3.connect((ROOT/'job-scout/data/jobs.sqlite3').as_uri()+'?mode=ro',uri=True) as connection:
            scores={(str(source).casefold(),url):score for source,url,score in connection.execute('SELECT j.source,j.url,e.match_score FROM jobs j JOIN job_evaluations e ON j.id=e.job_id')}
        before_ids = {str(row.get("ID", "")) for _, row in tracker.scout().rows}
        for _,row in tracker.scout().rows:
            score=scores.get((str(row.get('Source','')).casefold(),row.get('Job URL','')))
            preferences['_impromptu_known'][(str(row.get('Source','')).casefold(),row.get('Job URL',''))]={
                'priority':row.get('Personal priority',''),'cost':row.get('Cost',''),'score':score}
        locations=['Remote' if p=='Remote / anywhere' else 'Utah' if p in ('Utah (statewide)','Other / unknown') else p for p in settings['locations']]
        args=scout.build_parser().parse_args(['search','--source','core','--audit-dir',str(path.parent)])
        args.selected_sources=settings['sources'];args.query=settings['titles'];args.location=locations
        with JobStore(DEFAULT_DB) as store:
            result = scout.search(args,store,preferences)
        if settings['create_resumes'] and result == 0:
            new_ids = [str(row.get('ID', '')) for _, row in tracker.scout().rows
                       if str(row.get('ID', '')) not in before_ids and str(row.get('ID', '')).isdigit()]
            if new_ids:
                import subprocess
                result = subprocess.run([sys.executable, str(ROOT/'scripts/generate_apply_queue.py'), '--ids', *new_ids], cwd=ROOT).returncode
        return result

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--filters',type=Path,required=True)
    raise SystemExit(main(parser.parse_args().filters))
