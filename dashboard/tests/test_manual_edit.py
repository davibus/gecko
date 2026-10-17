import json,sys,unittest
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[2]),str(Path(__file__).resolve().parents[2]/'scripts')]
from test_sqlite_tracker import SQLiteTrackerTests
from dashboard import manual,server

class ManualEditTests(unittest.TestCase):
    def setUp(self):
        SQLiteTrackerTests.setUp(self)
        from storage import JobStore
        JobStore(self.db).close()
        self.saved=manual.save(self.tracker,{'url':'https://example.com/manual-role','Company':'Mira Home','Job Title':'Senior Google Ads Specialist','Location':'Lindon, UT 84042','Notes':'Unfinished application','description':'Original posting'},'2026-10-17')

    def payload(self):
        job=server.Workspace(lambda:self.tracker).detail(self.saved['id'])
        return {'id':job['id'],'version':job['version'],'url':job['url'],**{k:job['fields'].get(k,'') for k in manual.FIELDS},'Notes':job['notes'],'description':job['description'],'applied':job['applied'],'applied_date':'2026-10-17'}

    def test_reopen_save_updates_same_id_and_description(self):
        p=self.payload();p.update({'Salary':'$100,000','description':'Updated posting','Notes':'Still working'})
        result=manual.save(self.tracker,p,'2026-10-17T06:00:00-06:00')
        self.assertEqual(result['id'],self.saved['id']);self.assertTrue(result['updated']);self.assertFalse(result['applied'])
        snapshot=server.Workspace(lambda:self.tracker).snapshot()
        self.assertEqual(len(snapshot['jobs']),2)
        job=server.Workspace(lambda:self.tracker).detail(result['id'])
        with self.tracker.connection() as con:
            self.assertEqual(con.execute('SELECT description FROM jobs WHERE id=?',(result['id'],)).fetchone()[0],'Updated posting')
        self.assertEqual(job['fields']['Salary'],'$100,000')
        self.assertEqual(job['notes'],'Still working');self.assertFalse(job['fields']['Applied Date'])

    def test_save_and_applied_preserves_resume_custom_fields_and_history(self):
        with self.tracker.connection() as con,con:
            row=con.execute("SELECT slot,values_json FROM workspace_records WHERE json_extract(values_json,'$.ID')=?",(int(self.saved['id']),)).fetchone()
            raw=json.loads(row['values_json']);raw.update({'Resume Created':'X','Resume Link':'file:///keep.docx','My custom column':'keep','Response':'keep response'})
            con.execute("UPDATE workspace_records SET values_json=? WHERE dataset='Job List' AND slot=?",(json.dumps(raw),row['slot']))
        p=self.payload();p['applied']=True
        manual.save(self.tracker,p,'2026-10-17T06:00:00-06:00')
        job=server.Workspace(lambda:self.tracker).detail(self.saved['id'])
        self.assertTrue(job['applied']);self.assertEqual(job['fields']['Applied Date'],'2026-10-17')
        for k in ('Resume Created','Resume Link','My custom column','Response'):self.assertEqual(job['fields'][k],raw[k])
        p=self.payload();p['applied']=False
        manual.save(self.tracker,p,'2026-10-17T06:01:00-06:00')
        job=server.Workspace(lambda:self.tracker).detail(self.saved['id'])
        self.assertTrue(job['applied']);self.assertEqual(job['meta']['applied_at'],'2026-10-17')
        self.assertEqual(len(job['history']),2)

    def test_stale_identity_and_nonmanual_edits_rejected(self):
        p=self.payload();manual.save(self.tracker,p,'2026-10-17')
        with self.assertRaisesRegex(ValueError,'changed'):manual.save(self.tracker,p,'2026-10-17')
        p=self.payload();p['url']='https://example.com/different-job'
        with self.assertRaisesRegex(ValueError,'original posting'):manual.save(self.tracker,p,'2026-10-17')
        row,data=self.tracker.scout().rows[0]
        p={'id':'10','version':server.version(data),'url':data['Job URL'],'Company':data['Company'],'Job Title':data['Job Title']}
        with self.assertRaisesRegex(ValueError,'individually added'):manual.save(self.tracker,p,'2026-10-17')

    def test_formula_edit_fails_without_partial_changes(self):
        with self.tracker.connection() as con,con:
            con.execute("UPDATE workspace_records SET formulas_json=? WHERE json_extract(values_json,'$.ID')=?",(json.dumps({'Salary':'=protected'}),int(self.saved['id'])))
        p=self.payload();p['Salary']='$200,000';p['applied']=True
        with self.assertRaisesRegex(ValueError,'formula-protected'):manual.save(self.tracker,p,'2026-10-17')
        self.assertFalse(server.Workspace(lambda:self.tracker).detail(self.saved['id'])['applied'])

if __name__=='__main__':unittest.main()
