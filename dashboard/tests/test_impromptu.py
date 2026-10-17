import copy
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'job-scout'))
from impromptu_filters import options,validate,matches
from hard_filters import deterministic_filter

class ImpromptuTests(unittest.TestCase):
    def setUp(self):
        o=options()
        self.f=validate({**o,'priorities':['Unassigned','High'],'salary_min':None,'salary_max':None,'salary_unknown':True})
        self.j=SimpleNamespace(source='adzuna',title='Paid Search Manager',work_arrangement='remote',location='Remote US',salary='$90,000 - $110,000',url='https://example.com/job',employment_type='full-time',category='')
    def test_unknown_new_jobs_can_be_included(self):
        self.assertTrue(matches(self.j,self.f,{}))
    def test_source_title_and_arrangement_exclusions(self):
        for key,value in [('sources',['lever']),('titles',['Analytics Director']),('arrangements',['on-site'])]:
            f={**self.f,key:value};self.assertFalse(matches(self.j,f,{}),key)
    def test_salary_range_overlap_and_unknown(self):
        self.assertTrue(matches(self.j,{**self.f,'salary_min':100000},{}))
        self.assertFalse(matches(self.j,{**self.f,'salary_min':120000},{}))
        self.j.salary='CAD 150000';self.assertFalse(matches(self.j,{**self.f,'salary_unknown':False},{}))
    def test_utah_specific_location(self):
        self.j.work_arrangement='hybrid';self.j.location='Lehi, UT'
        self.assertTrue(matches(self.j,{**self.f,'locations':['Lehi']},{}))
        self.assertFalse(matches(self.j,{**self.f,'locations':['Provo']},{}))
    def test_saved_priority_score_and_cost(self):
        known={('adzuna',self.j.url):{'priority':'High','score':85,'cost':'x'}}
        f={**self.f,'priorities':['High'],'matches':['Strong (80–100)'],'costs':['Fee required']}
        self.assertTrue(matches(self.j,f,known))
        self.assertFalse(matches(self.j,f,{}))
        self.assertFalse(matches(self.j,{**f,'costs':['Unknown']},known))
    def test_all_groups_and_salary_validation(self):
        for key in ['sources','titles','arrangements','matches','costs','locations','priorities']:
            with self.assertRaises(ValueError):validate({**self.f,key:[]})
        with self.assertRaises(ValueError):validate({**self.f,'sources':['arbitrary']})
        with self.assertRaises(ValueError):validate({**self.f,'salary_min':100,'salary_max':50})
        with self.assertRaises(ValueError):validate({**self.f,'salary_min':float('nan')})
    def test_default_filters_unchanged_and_manual_narrowing(self):
        p={'target_roles':['Paid Search Manager'],'preferred_locations':['Utah'],'excluded_seniority':[]}
        original=copy.deepcopy(p)
        self.assertTrue(deterministic_filter(self.j,p)[0]);self.assertEqual(original,p)
        p['_impromptu']={**self.f,'sources':['lever']}
        self.assertFalse(deterministic_filter(self.j,p)[0])

class DispatchTests(unittest.TestCase):
    def test_manual_request_saves_immutable_settings_without_starting_daily(self):
        import tempfile
        import json
        sys.path.insert(0,str(ROOT/'dashboard'))
        import server
        settings={**options(),'priorities':['Unassigned'],'salary_min':None,'salary_max':None,'salary_unknown':True}
        with tempfile.TemporaryDirectory() as folder, patch.object(server,'ROOT',Path(folder)), patch.object(server,'STATE',Path(folder)), patch.object(server.Workspace,'activity',return_value={'busy':False}), patch.object(server.threading,'Thread') as thread:
            app=server.Workspace(lambda:SimpleNamespace(backend='sqlite'))
            result=app.start({'kind':'impromptu','filters':settings})
            self.assertEqual(result['kind'],'impromptu')
            self.assertNotIn('job_ids',result)
            self.assertEqual(json.loads(Path(result['filters_path']).read_text()),validate(settings))
            self.assertEqual(thread.call_args.kwargs['args'],('impromptu',None))
            with patch.object(server.subprocess,'run',return_value=SimpleNamespace(returncode=0)) as run:
                app.worker('impromptu',None)
            self.assertIn('run_impromptu.py',' '.join(run.call_args.args[0]))
            self.assertNotIn('run_gecko.py',' '.join(run.call_args.args[0]))
            self.assertEqual(app.operation['status'],'complete')

if __name__=='__main__':unittest.main()
