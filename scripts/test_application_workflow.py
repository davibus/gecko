"""Isolated source/scoping, non-submitting DOM, recovery and mocked Sheet tests."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from playwright.sync_api import sync_playwright
from application_runtime import BatchSources, Timings, Checkpoints, claim_attempt, prior_attempt, batch_lock
from application_forms import answer_for, platform, verify_answer_action
import playwright_batch as batch
from playwright_fast import run_packets
from playwright_tracker import PrimaryTracker, check_row, local_resume
from tracker_schema import resolve_headers


def fixture_sources(root):
    master = root/'input/master-resume/master-resume-v4.docx'
    master.parent.mkdir(parents=True)
    with ZipFile(master, 'w') as z:
        z.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Dave Call</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>mdavidcall@gmail.com</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>')
    bank = root/'openclaw/application-answers.md'
    bank.parent.mkdir()
    bank.write_text('Confirmed scoped response: Yes\nConfirmed general response: Yes\nProposed response: Yes', encoding='utf-8')
    def record(ident, question, answer, quote, *, kind='answers', scope=None, status='confirmed'):
        return {'id': ident, 'meaning': ident, 'questions': [question], 'answer': answer,
                'status': status, 'confirmed_on': '2026-10-23', 'scope': scope or {},
                'source': {'kind': kind, 'quote': quote, 'path': str(bank)}}
    records = [record('name', 'Full name', 'Dave Call', 'Dave Call', kind='master'),
               record('email', 'Email', 'mdavidcall@gmail.com', 'mdavidcall@gmail.com', kind='master'),
               record('scoped', 'Do you have eight years of this experience?', 'Yes', 'Confirmed scoped response: Yes', scope={'employer':'Example', 'jobs':[101]}),
               record('proposal', 'Proposed answer?', 'Yes', 'Proposed response: Yes', status='proposed'),
               record('general', 'Are you authorized?', 'Yes', 'Confirmed general response: Yes')]
    return BatchSources(root, records=records).refresh()


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sources = fixture_sources(self.root)
        self.packet = {'id':101, 'company':'Example'}

    def test_scope_confirmation_and_equivalent_meaning(self):
        self.assertEqual(self.sources.resolve('Do you have eight years of this experience? *', self.packet)['answer'], 'Yes')
        self.assertIsNone(self.sources.resolve('Do you have eight years of this experience?', {'id':102,'company':'Example'}))
        self.assertIsNone(self.sources.resolve('Do you have eight years of this experience?', {'id':101,'company':'Other'}))
        self.assertIsNone(self.sources.resolve('Proposed answer?', self.packet))
        self.assertIsNone(self.sources.resolve('Have you applied before?', self.packet))
        self.assertIsNone(self.sources.resolve('Are you authorized and willing to relocate?', self.packet))

    def test_source_loaded_once_and_refreshes_when_changed(self):
        self.sources.refresh(); self.sources.refresh()
        self.assertEqual(self.sources.parse_counts['master'],1)
        self.assertEqual(self.sources.parse_counts['answers'],1)
        self.assertIn('mdavidcall@gmail.com',self.sources.content['master'])
        bank=self.sources.paths['answers'];bank.write_text('Changed confirmation; old answer removed',encoding='utf-8')
        self.sources.refresh()
        self.assertEqual(self.sources.parse_counts['answers'],2)
        self.assertIsNone(self.sources.resolve('Are you authorized?',self.packet))
        with ZipFile(self.sources.paths['master'],'w') as z:
            z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body/></w:document>')
        self.sources.refresh()
        self.assertEqual(self.sources.parse_counts['master'],2)
        self.assertIsNone(self.sources.resolve('Full name',self.packet))

    def test_platform_hints_do_not_override_unknown_questions(self):
        self.assertEqual(platform('https://jobs.lever.co/example/123'), 'lever')
        self.assertEqual(platform('https://example.com/apply'), 'generic')
        f={'label':'Unrelated name of client?', 'question':'Unrelated name of client?', 'name':'name'}
        self.assertIsNone(answer_for(f,self.packet,self.sources,'https://jobs.lever.co/x'))

    def test_conflicting_confirmations_fail_closed(self):
        one=deepcopy(self.sources.content['index'][-1]);one['answer']='No'
        self.sources.content['index'].append(one)
        self.assertIsNone(self.sources.resolve('Are you authorized?',self.packet))

    def test_repository_index_quotes_still_exist(self):
        sources=BatchSources().refresh()
        self.assertGreater(len(sources.content['index']),30)
        for record in sources.content['index']:
            with self.subTest(answer=record['id']):
                self.assertTrue(record['source']['quote'] in sources.content[record['source']['kind']], record['id'])


class LedgerTests(unittest.TestCase):
    def test_interrupted_batch_lock_is_reusable(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'batch.lock'
            with self.assertRaisesRegex(RuntimeError,'interrupted'):
                with batch_lock(p):raise RuntimeError('interrupted')
            with batch_lock(p):
                with self.assertRaisesRegex(RuntimeError,'already running'):
                    with batch_lock(p):pass
            with batch_lock(p):pass

    def test_cross_batch_and_url_alias_prevention(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);p={'id':101,'url':'https://jobs.example/123?utm_source=a'}
            out=base/'one'/'101';out.mkdir(parents=True)
            with patch('application_runtime.ledger_root',return_value=base):
                claim_attempt(p,out,{'id':101})
                self.assertTrue(prior_attempt(p,base/'two'/'101'))
                alias={'id':999,'url':'https://jobs.example/123?utm_source=b'}
                self.assertTrue(prior_attempt(alias,base/'two'/'999'))
                with self.assertRaisesRegex(RuntimeError,'Prior submission'):
                    claim_attempt(alias,base/'two'/'999',{})


class FakeBatchTracker:
    def __init__(self,packets):
        self.packets={p['id']:p for p in packets};self.events=[]
    def call(self,action,**kw):
        if action=='check':
            self.events.append(('check',kw['id']))
            return deepcopy(self.packets[kw['id']]['row'])
        if action=='prepare':
            self.events.append(('prepare',kw['id']))
            return deepcopy(self.packets[kw['id']])
        if action=='receipt':
            self.events.append(('receipt',kw['receipt']['id']))
            return {'verified':True,'id':kw['receipt']['id'],'Applied':'X','Applied Date':'2026-10-26'}
        raise AssertionError(action)
    def close(self):self.events.append(('close',None))


class BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw=sync_playwright().start();cls.browser=cls.pw.chromium.launch(channel='chrome',headless=True)
    @classmethod
    def tearDownClass(cls):
        cls.browser.close();cls.pw.stop()
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.sources=fixture_sources(self.root)
        self.context=self.browser.new_context();self.addCleanup(self.context.close)
        self.network=[]
        self.context.route('**/*',lambda r:(self.network.append(r.request.url),r.abort())[-1])
        self.base=self.root/'evidence';self.base.mkdir()

    def packet(self,ident,extra=''):
        resume=self.root/f'resume-{ident}.docx';resume.write_bytes(b'Synthetic resume fixture')
        row={'Company':'Example','Job Title':'Example role','Job URL':f'https://jobs.example/{ident}','Resume Link':resume.as_uri()}
        p={'id':ident,'company':'Example','title':'Example role','url':row['Job URL'],'row':row,
           'resume':str(resume),'resume_sha256':hashlib.sha256(resume.read_bytes()).hexdigest()}
        page=self.context.new_page();page.evaluate('(n)=>window.name=n',f'gecko-{ident}')
        page.set_content('<h1>Example - Example role</h1><label>Full name<input name="name" required></label>'
                         '<label>Email<input name="email" type="email" required></label>'
                         f'<label>Resume<input name="resume" type="file" required></label>{extra}'
                         '<button type="button" id="send" onclick="document.body.innerHTML=\'<h1>Application received!</h1>\'">Submit application</button>')
        return p,page

    def run_batch(self,packets,**kw):
        tracker=FakeBatchTracker(packets)
        result=run_packets(self.context,packets,tracker,self.sources,self.base,**kw)
        self.assertEqual(self.network,[])
        return result,tracker

    def test_unknown_required_preserves_draft_and_continues(self):
        one,page=self.packet(101,'<label>Exact unfamiliar required question?<input required name="unknown"></label>')
        two,_=self.packet(102)
        reports,tracker=self.run_batch([one,two],allow_submit=True)
        self.assertEqual(reports[0]['status'],'Needs attention')
        self.assertEqual(reports[0]['missing_required'][0]['question'],'Exact unfamiliar required question?')
        self.assertFalse(page.is_closed());self.assertEqual(page.locator('[name=unknown]').input_value(),'')
        self.assertTrue(reports[0]['resume']['upload_verified'])
        self.assertEqual([x for x in tracker.events if x[0]=='receipt'],[('receipt',102)])
        self.assertTrue(reports[1]['tracker']['verified'])

    def test_each_receipt_updates_tracker_before_next_job(self):
        one,_=self.packet(101);two,_=self.packet(102)
        reports,tracker=self.run_batch([one,two],allow_submit=True)
        self.assertEqual(tracker.events,[('check',101),('check',101),('receipt',101),('check',102),('check',102),('receipt',102)])
        self.assertTrue(all(r['tracker']['verified'] for r in reports))

    def test_draft_only_does_not_dispatch_or_write_tracker(self):
        p,page=self.packet(101)
        reports,tracker=self.run_batch([p],allow_submit=False)
        self.assertEqual(reports[0]['status'],'Draft prepared - submission disabled')
        self.assertTrue(page.locator('#send').is_visible())
        self.assertFalse((self.base/'101/submission-attempt.json').exists())
        self.assertFalse(any(e[0]=='receipt' for e in tracker.events))

    def test_duplicate_application_links_use_one_destination(self):
        p, page = self.packet(101)
        form = page.content()
        page.set_content('<h1>Example - Example role</h1><input hidden name="tracking"><input type="checkbox" name="cookie_preference">'
                         '<a href="https://jobs.example/101/apply">Application</a>'
                         '<a href="https://jobs.example/101/apply">Apply for this job</a>')
        with patch.object(page, 'goto', side_effect=lambda *a, **kw: page.set_content(form)) as navigate:
            reports, tracker = self.run_batch([p], allow_submit=False)
        self.assertEqual(navigate.call_count, 1)
        self.assertEqual(reports[0]['status'], 'Draft prepared - submission disabled')

    def test_required_label_marker_without_native_required_blocks_submission(self):
        p, page = self.packet(101, '<label>Required employer screening answer*<input name="screening"></label>')
        reports, tracker = self.run_batch([p], allow_submit=True)
        self.assertEqual(reports[0]['status'], 'Needs attention')
        self.assertTrue(any('Required employer screening answer' in x['question'] for x in reports[0]['missing_required']))
        self.assertFalse(any(e[0] == 'receipt' for e in tracker.events))

    def test_label_on_line_after_required_marker_is_resolved(self):
        p, page = self.packet(101)
        page.locator('[name=name]').evaluate("e=>e.parentElement.firstChild.textContent='*\\nFull name'")
        reports, tracker = self.run_batch([p], allow_submit=False)
        self.assertEqual(page.locator('[name=name]').input_value(), 'Dave Call')
        self.assertEqual(reports[0]['status'], 'Draft prepared - submission disabled')

    def test_fieldset_section_heading_does_not_override_contact_labels(self):
        p, page = self.packet(101)
        page.locator('body').evaluate("e=>e.innerHTML='<fieldset><legend>Personal Details</legend>'+e.innerHTML+'</fieldset>'")
        reports, tracker = self.run_batch([p], allow_submit=False)
        self.assertEqual(page.locator('[name=name]').input_value(), 'Dave Call')
        self.assertEqual(page.locator('[name=email]').input_value(), 'mdavidcall@gmail.com')
        self.assertEqual(reports[0]['status'], 'Draft prepared - submission disabled')

    def test_unknown_prefilled_required_and_agreement_are_not_confirmed(self):
        p,page=self.packet(101,'<label>Unknown answer<input name="x" required value="Proposed wording"></label><label><input type="checkbox" required checked>New agreement</label>')
        reports,tracker=self.run_batch([p],allow_submit=True)
        self.assertEqual(reports[0]['status'],'Needs attention')
        self.assertEqual(len(reports[0]['unverified_required']),2)
        self.assertEqual(page.locator('[name=x]').input_value(),'Proposed wording')
        self.assertFalse(any(e[0]=='receipt' for e in tracker.events))

    def test_interruption_after_claim_never_repeats_click(self):
        p,page=self.packet(101)
        original=batch.claim_attempt
        def interrupted(*a,**kw):
            original(*a,**kw)
            raise RuntimeError('Interrupted after durable claim')
        with patch.object(batch,'claim_attempt',side_effect=interrupted):
            first,_=self.run_batch([p],allow_submit=True)
        self.assertIn('Interrupted',first[0]['blocker'])
        second,tracker=self.run_batch([p],allow_submit=True)
        self.assertIn('Prior submission attempt',second[0]['blocker'])
        self.assertTrue(page.locator('#send').is_visible())
        self.assertFalse(any(e[0]=='receipt' for e in tracker.events))

    def test_receipt_survives_tracker_failure_and_recovers_without_refill(self):
        p,page=self.packet(101);tracker=FakeBatchTracker([p]);original=tracker.call
        def fail(action,**kw):
            if action=='receipt':raise RuntimeError('Mock tracker unavailable')
            return original(action,**kw)
        with patch.object(tracker,'call',side_effect=fail):
            run_packets(self.context,[p],tracker,self.sources,self.base,allow_submit=True)
        self.assertTrue((self.base/'101/receipt.json').exists())
        page.close()
        recovered,tracker=self.run_batch([p],allow_submit=True)
        self.assertTrue(recovered[0]['tracker']['verified'])
        self.assertEqual(tracker.events,[('receipt',101)])

    def test_missing_draft_tab_does_not_create_another(self):
        p,page=self.packet(101);cp=Checkpoints(self.base)
        cp.write(p,cp.read(p),draft_opened=True);page.close()
        reports,_=self.run_batch([p],allow_submit=False)
        self.assertIn('draft tab missing',reports[0]['blocker'])
        self.assertEqual(len(self.context.pages),0)

    def test_lost_window_name_recovers_only_exact_visible_saved_draft(self):
        p,page=self.packet(101);cp=Checkpoints(self.base)
        cp.write(p,cp.read(p),draft_opened=True,url=page.url)
        page.evaluate("window.name=''")
        reports,_=self.run_batch([p],allow_submit=False)
        self.assertEqual(reports[0]['status'],'Draft prepared - submission disabled')
        self.assertEqual(page.evaluate('window.name'),'gecko-101')
        self.assertEqual(len(self.context.pages),1)

    def test_wrong_existing_file_is_preserved_and_blocked(self):
        p,page=self.packet(101);wrong=self.root/'wrong.docx';wrong.write_bytes(b'Other file')
        page.locator('[type=file]').set_input_files(str(wrong))
        reports,_=self.run_batch([p],allow_submit=True)
        self.assertIn('Existing attachment differs',reports[0]['blocker'])
        self.assertEqual(page.locator('[type=file]').evaluate('(e)=>e.files[0].name'),'wrong.docx')

    def test_conditional_required_question_gets_a_fresh_step(self):
        p,page=self.packet(101,'<div id="conditional" style="display:none"><label>Exact conditional question?<input required name="conditional"></label></div>')
        page.locator('[name=name]').evaluate("e=>e.addEventListener('input',()=>document.getElementById('conditional').style.display='block')")
        reports,_=self.run_batch([p],allow_submit=True)
        self.assertEqual(reports[0]['status'],'Needs attention')
        self.assertEqual(reports[0]['missing_required'][0]['question'],'Exact conditional question?')
        # Inspect again after filling: same-size rerenders can replace controls.
        self.assertGreaterEqual(reports[0]['timings']['counts']['inspection'],2)

    def test_radio_group_uses_question_meaning(self):
        p,page=self.packet(101,'<fieldset><legend>Are you authorized?</legend><label><input required type="radio" name="auth" value="yes">Yes</label><label><input required type="radio" name="auth" value="no">No</label></fieldset>')
        reports,_=self.run_batch([p],allow_submit=False)
        self.assertEqual(reports[0]['status'],'Draft prepared - submission disabled')
        self.assertTrue(page.locator('[value=yes]').is_checked())
        self.assertFalse(page.locator('[value=no]').is_checked())

    def test_actual_upload_completion_and_error_conditions(self):
        p,page=self.packet(101)
        page.locator('[type=file]').evaluate("e=>e.addEventListener('change',()=>{document.body.setAttribute('aria-busy','true');setTimeout(()=>{document.body.removeAttribute('aria-busy');window.uploadFinished=true},100)})")
        reports,_=self.run_batch([p],allow_submit=False)
        self.assertTrue(page.evaluate('window.uploadFinished'))
        self.assertTrue(reports[0]['resume']['upload_verified'])
        other,other_page=self.packet(102)
        other_page.locator('[type=file]').evaluate("e=>e.addEventListener('change',()=>{document.body.append('Upload failed')})")
        blocked,tracker=self.run_batch([other],allow_submit=True)
        self.assertIn('Resume upload failed',blocked[0]['blocker'])
        self.assertFalse(any(e[0]=='receipt' for e in tracker.events))

    def test_saved_receipt_from_another_job_never_updates_tracker(self):
        p,_=self.packet(101);out=self.base/'101';out.mkdir()
        (out/'receipt.json').write_text(json.dumps({'id':999,'company':'Other','title':'Other role'}))
        reports,tracker=self.run_batch([p],allow_submit=True)
        self.assertIn('does not belong',reports[0]['blocker'])
        self.assertFalse(tracker.events)

    def test_screenshot_failure_does_not_delay_tracker(self):
        p,page=self.packet(101);events=[]
        tracker=FakeBatchTracker([p]);original=tracker.call
        def call(action,**kw):
            events.append(action);return original(action,**kw)
        def screenshot(*args,**kw):
            self.assertIn('receipt',events)
            raise RuntimeError('Mock screenshot failure')
        with patch.object(tracker,'call',side_effect=call),patch.object(page,'screenshot',side_effect=screenshot):
            reports=run_packets(self.context,[p],tracker,self.sources,self.base,allow_submit=True)
        self.assertTrue(reports[0]['tracker']['verified'])
        self.assertIn('confirmation_screenshot_error',reports[0])

    def test_default_cli_prepares_without_browser_or_tracker_writes(self):
        import playwright_fast as fast
        from contextlib import redirect_stdout
        import io
        p,_=self.packet(101);tracker=FakeBatchTracker([p]);base=self.root/'reports/playwright-pilot/new-batch'
        args=['playwright_direct.py','--ids','101','--evidence-dir',str(base)]
        with patch.object(fast,'ROOT',self.root),patch.object(fast,'BatchSources',return_value=self.sources),patch.object(fast,'TrackerClient',return_value=tracker),patch.object(fast,'sync_playwright',side_effect=AssertionError('Browser must remain closed')),patch('sys.argv',args),redirect_stdout(io.StringIO()):
            fast.main()
        self.assertEqual(tracker.events,[('prepare',101),('close',None)])
        prep=json.loads((base/'preparation.json').read_text())
        self.assertGreater(prep['timings']['seconds']['preparation'],0)
        self.assertTrue((base/'packets.json').exists())

    def test_unfamiliar_form_fallback_requires_confirmed_value(self):
        p,page=self.packet(101);element=page.locator('[name=name]')
        record=verify_answer_action(element,{'value':'Dave Call'},p,self.sources)
        self.assertEqual(record['id'],'name')
        with self.assertRaisesRegex(RuntimeError,'proposed wording'):
            verify_answer_action(element,{'value':'Proposed wording'},p,self.sources)
        element.fill('User-entered answer')
        with self.assertRaisesRegex(RuntimeError,'Preserve existing answer'):
            verify_answer_action(element,{'value':'Dave Call'},p,self.sources)

    def test_submission_state_never_accepts_incomplete_wording_as_receipt(self):
        p,page=self.packet(101)
        page.locator('#send').evaluate("e=>e.onclick=()=>document.body.innerHTML='<h1>Your application is incomplete</h1>'")
        original=page.wait_for_function
        def wait(expression,**kwargs):
            if 'new RegExp' in expression:
                self.assertFalse(page.evaluate('(pattern)=>new RegExp(pattern,"i").test(document.body.innerText)',kwargs['arg']))
                raise RuntimeError('No positive employer confirmation')
            return original(expression,**kwargs)
        with patch.object(page,'wait_for_function',side_effect=wait):
            reports,tracker=self.run_batch([p],allow_submit=True)
        self.assertIn('No positive employer confirmation',reports[0]['blocker'])
        self.assertFalse((self.base/'101/receipt.json').exists())
        self.assertFalse(any(e[0]=='receipt' for e in tracker.events))


class MockSheets:
    def __init__(self,rows,headers):
        self.rows=deepcopy(rows);self.header_values=tuple(headers);self.headers=resolve_headers(headers)
        self.api=self;self.calls=[];self.frozen_count=2;self.formulas={};self.move_on_call=None;self.reads=0;self.rejected=False
    def _assert_scout_row_not_rejected(self,row):
        if self.rejected:raise ValueError('Permanently rejected')
    def scout(self,**kw):
        self.reads+=1
        if self.reads==self.move_on_call:self.header_values=tuple(reversed(self.header_values));self.headers=resolve_headers(self.header_values)
        rows=deepcopy(self.rows)
        if kw.get('value_render_option')=='FORMULA':
            for _,r in rows:r.update(self.formulas)
        return SimpleNamespace(title='Job List',sheet_id=7,header_values=self.header_values,headers=self.headers,rows=rows)
    def get(self,**kw):
        return SimpleNamespace(execute=lambda:{'sheets':[{'properties':{'sheetId':7,'gridProperties':{'frozenRowCount':self.frozen_count}}}]})
    def values(self):return self
    def batchUpdate(self,**kw):
        self.calls.append(kw['body'])
        def execute():
            import re
            for e in kw['body']['data']:
                cell=e['range'].split('!')[-1];letters=re.match('[A-Z]+',cell).group();number=int(re.search(r'\d+',cell).group())
                col=0
                for c in letters:col=col*26+ord(c)-64
                field=self.header_values[col-1]
                dict(self.rows)[number][field]=e['values'][0][0]
            return {}
        return SimpleNamespace(execute=execute)


class TrackerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Production tracker operations run in dashboard-Python, which owns tzdata.
        # Browser tests use Playwright-Python; use that same installed IANA data.
        import zoneinfo
        cls.old_tzpath=zoneinfo.TZPATH
        zoneinfo.reset_tzpath([str(Path(__file__).resolve().parents[1]/'.tools/dashboard-python/Lib/site-packages/tzdata/zoneinfo')])
    @classmethod
    def tearDownClass(cls):
        import zoneinfo
        zoneinfo.reset_tzpath(cls.old_tzpath)
    def setUp(self):
        self.row={'Scout ID':'101','Company':'Example','Job Title':'Role','Job URL':'https://example.com/jobs/1',
                  'Source':'Company','Cost':'','Apply?':'Yes','Resume Created':'X','Resume Link':'file:///fixture.docx',
                  'Applied':'','Applied Date':'','Previous Applied Date':'2025-01-01','Notes':'manual note','Custom':'manual value'}
        self.headers=['Custom','Applied Date','Company','ID','Resume Link','Applied','Job Title','Job URL','Source','Cost','Qualifies to Apply?','Resume Created','Previous Applied Date','Notes']
        remote_row={**self.row,'ID':'101','Qualifies to Apply?':'Yes'}
        self.remote=MockSheets([(9,remote_row)],self.headers)
        self.client=PrimaryTracker(SimpleNamespace(spreadsheet_id='mock'),self.remote)
        self.receipt={'id':101,'company':'Example','title':'Role','job_url':'https://example.com/jobs/1','submitted_at':'2026-10-27T02:00:00+00:00',
                      'confirmation_verified':True,'confirmation_text':'Application received!'}
    def test_only_two_named_cells_denver_date_readback_and_idempotence(self):
        result=self.client.receipt(self.receipt)
        self.assertEqual(result['Applied Date'],'2026-10-26')
        entries=self.remote.calls[0]['data']
        self.assertEqual({e['range'] for e in entries},{"'Job List'!F9","'Job List'!B9"})
        after=dict(self.remote.rows)[9]
        self.assertEqual(after['Previous Applied Date'],'2025-01-01');self.assertEqual(after['Notes'],'manual note')
        self.assertEqual(after['Custom'],'manual value');self.assertEqual(self.remote.frozen_count,2)
        self.assertEqual(self.client.receipt(self.receipt)['cells_written'],0)
        self.assertEqual(len(self.remote.calls),1)
    def test_formula_protection_and_column_movement_fail_closed(self):
        self.remote.formulas={'Applied Date':'=TODAY()'}
        with self.assertRaisesRegex(ValueError,'formula protected'):self.client.receipt(self.receipt)
        self.assertFalse(self.remote.calls)
        self.remote.formulas={};self.remote.reads=0;self.remote.move_on_call=3
        with self.assertRaisesRegex(ValueError,'Sheet changed'):self.client.receipt(self.receipt)
        self.assertFalse(self.remote.calls)
    def test_ambiguous_headers_unknown_date_and_unfrozen_block(self):
        bad={**self.receipt,'submitted_at':'2026-10-26T10:00:00'}
        with self.assertRaisesRegex(ValueError,'timezone-aware'):self.client.receipt(bad)
        self.remote.frozen_count=0
        with self.assertRaisesRegex(ValueError,'Frozen header'):self.client.receipt(self.receipt)
        self.remote.frozen_count=2;self.remote.header_values+=('Applied',)
        with self.assertRaisesRegex(RuntimeError,'ambiguous'):self.client.receipt(self.receipt)
        self.assertFalse(self.remote.calls)
    def test_applied_fee_and_location_preflight_guards(self):
        for change,error in [({'Applied':'X'},'Already Applied'),({'Cost':'x'},'Cost'),({'Location':'Unknown'},'Location')]:
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,error):
                check_row({**self.row,**change})

    def test_preparation_exact_completed_resume_and_job_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);resumes=root/'output/resumes';resumes.mkdir(parents=True)
            resume=resumes/'Dave-Call+Example+Role+source-job-1.docx';resume.write_bytes(b'Synthetic fixture')
            descriptions=root/'input/job-descriptions';descriptions.mkdir(parents=True)
            (descriptions/'example.md').write_text('# Role at Example\n- **Scout ID:** 101\n- **Job Number:** `source-job-1`\n',encoding='utf-8')
            row=dict(self.remote.rows)[9];row.update({'Resume Link':resume.as_uri(),'Location':'United States','Work Arrangement':'Remote'})
            client=PrimaryTracker(SimpleNamespace(spreadsheet_id='mock'),self.remote,root)
            packet=client.prepare(101)
            self.assertEqual(packet['resume'],str(resume));self.assertEqual(packet['resume_sha256'],hashlib.sha256(resume.read_bytes()).hexdigest())
            self.assertFalse(self.remote.calls)
            wrong=resume.with_name('Dave-Call+Other+Role+source-job-1.docx');resume.rename(wrong);row['Resume Link']=wrong.as_uri()
            with self.assertRaisesRegex(RuntimeError,'resume_job_identity_mismatch'):client.prepare(101)
            wrong.unlink()
            with self.assertRaisesRegex(ValueError,'Missing exact completed resume'):client.prepare(101)
            self.assertFalse(self.remote.calls)

    def test_rejections_duplicate_postings_and_applied_never_prepare(self):
        row=dict(self.remote.rows)[9]
        with patch('playwright_tracker.check_row'):
            self.remote.rejected=True
            with self.assertRaisesRegex(ValueError,'Permanently rejected'):self.client.check(101)
            self.remote.rejected=False
            self.remote.rows.append((10,{**row,'Scout ID':'102','ID':'102'}))
            with self.assertRaisesRegex(ValueError,'Duplicate posting'):self.client.check(101)
        row['Applied']='X'
        with self.assertRaisesRegex(ValueError,'Already Applied'):self.client.prepare(101)
        self.assertFalse(self.remote.calls)

    def test_private_drive_links_resolve_only_unchanged_registered_local_file(self):
        import resume_delivery as delivery
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);resume=root/'output/resumes/exact.docx';resume.parent.mkdir(parents=True);resume.write_bytes(b'Private local fixture')
            digest=hashlib.sha256(resume.read_bytes()).hexdigest();url='https://drive.google.com/file/d/fixture/view'
            manifest=root/'manifest.json';manifest.write_text(json.dumps({'files':{str(resume):{'path':str(resume),'url':url,'private':True,'sha256':digest,'downloaded_sha256':digest}}}))
            with patch.object(delivery,'ROOT',root),patch.object(delivery,'MANIFEST',manifest):
                self.assertEqual(local_resume({'Resume Link':url},root),resume)
                with self.assertRaisesRegex(ValueError,'verified local receipt'):
                    local_resume({'Resume Link':'https://drive.google.com/file/d/other/view'},root)
                resume.write_bytes(b'Changed bytes')
                with self.assertRaisesRegex(ValueError,'verified local receipt'):
                    local_resume({'Resume Link':url},root)
            self.assertFalse(self.remote.calls)


if __name__=='__main__':
    unittest.main()
