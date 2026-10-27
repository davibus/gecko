"""Regression cases from the October 26 failures. All forms and traffic are local."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from playwright.sync_api import sync_playwright
import playwright_batch as batch
from application_forms import captcha_visible
from application_runtime import Timings, BatchSources
from test_application_workflow import fixture_sources


class ApplicationRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(channel='chrome', headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sources = fixture_sources(self.root)
        self.context = self.browser.new_context()
        self.addCleanup(self.context.close)
        self.requests = []
        self.context.route('**/*', lambda r: (self.requests.append(r.request.url), r.abort())[-1])
        self.page = self.context.new_page()
        self.resume = self.root/'resume.docx'
        self.resume.write_bytes(b'Isolated synthetic resume')
        self.packet = dict(id=101, company='Example', title='Example role',
                           url='https://jobs.example/101', resume=str(self.resume),
                           resume_sha256=hashlib.sha256(self.resume.read_bytes()).hexdigest())
        self.state = {}
        self.addCleanup(setattr, batch, 'SOURCES', batch.SOURCES)
        batch.SOURCES = self.sources

    def fill(self, html):
        self.page.set_content('<h1>Example - Example role</h1>'+html)
        snap = batch.snapshot(self.page)
        batch.fill_supported(self.page, self.packet, self.state, snap)
        return batch.snapshot(self.page)

    def test_invisible_badge_is_not_a_blocking_captcha(self):
        self.page.set_content('<div class="grecaptcha-badge"><iframe title="reCAPTCHA" '
                              'src="https://www.google.com/recaptcha/api2/anchor?size=invisible"></iframe></div>')
        self.assertFalse(captcha_visible(self.page, batch.snapshot(self.page)))

    def test_empty_captcha_integration_container_is_not_a_challenge(self):
        self.page.set_content('<div class="g-recaptcha" style="width:300px;height:80px"></div>')
        self.assertFalse(captcha_visible(self.page, batch.snapshot(self.page)))

    def test_hidden_challenge_frame_text_is_ignored(self):
        self.page.set_content('<div style="opacity:0"><iframe srcdoc="<p>Verify you are human</p>"></iframe></div>')
        self.page.frames[1].locator('p').wait_for(state='attached')
        self.assertFalse(captcha_visible(self.page, batch.snapshot(self.page)))

    def test_nested_hidden_challenge_is_ignored(self):
        self.page.set_content('<div style="display:none"><iframe srcdoc="&lt;iframe srcdoc=&quot;&amp;lt;p&amp;gt;Verify you are human&amp;lt;/p&amp;gt;&quot;&gt;&lt;/iframe&gt;"></iframe></div>')
        self.assertFalse(captcha_visible(self.page, batch.snapshot(self.page)))

    def test_visible_challenge_is_still_blocked(self):
        self.page.set_content('<iframe srcdoc="<p>Verify you are human</p>"></iframe>')
        self.page.frames[1].locator('p').wait_for(state='attached')
        self.assertTrue(captcha_visible(self.page, batch.snapshot(self.page)))

    def test_visible_checkbox_captcha_is_still_blocked(self):
        self.page.set_content('<iframe title="reCAPTCHA" '
                              'src="https://www.google.com/recaptcha/api2/anchor?size=normal"></iframe>')
        self.assertTrue(captcha_visible(self.page, batch.snapshot(self.page)))

    def test_global_jobicy_resume_uploader_never_receives_a_file(self):
        self.page.set_content('<h1>Example - Example role</h1><div>Upload your resume now '
             'To unlock remote work opportunities and be discovered by global employers.'
             '<input id="global_resume_upload_input" type="file" hidden '
             'onchange="window.wrongUpload=true"></div><button>Apply Now</button>')
        batch.fill_supported(self.page, self.packet, self.state, batch.snapshot(self.page))
        self.assertFalse(self.page.evaluate('!!window.wrongUpload'))
        self.assertNotIn('resume', self.state)
        self.assertEqual(self.page.locator('[type=file]').evaluate('e=>e.files.length'), 0)

    def test_real_hidden_resume_input_is_uploaded_and_verified(self):
        self.fill('<form id="application"><label for="cv">Resume/CV</label>'
                  '<input id="cv" name="resume" type="file" hidden></form>')
        self.assertTrue(self.state['resume']['upload_verified'])

    def test_upload_survives_input_replaced_after_acknowledgement(self):
        self.fill('<form><label>Resume<input name="resume" type="file" onchange="'
                  'const n=this.files[0].name;this.parentElement.innerHTML=n+\' File uploaded <button type=button>Remove resume</button>\';'
                  '"></label></form>')
        self.assertTrue(self.state['resume']['upload_verified'])

    def test_rerendered_empty_field_is_not_reported_filled(self):
        self.fill('<label>Full name<input name="name" onchange="'
                  'const c=this.cloneNode();c.value=\'\';c.removeAttribute(\'onchange\');this.replaceWith(c)'
                  '"></label>')
        self.assertEqual(self.page.locator('[name=name]').input_value(), '')
        self.assertFalse(any(x['question']=='Full name' for x in self.state.get('filled', [])))
        self.assertTrue(self.state.get('field_errors'))

    def test_custom_combobox_selects_option_instead_of_only_typing(self):
        self.fill('''<div class="field"><label for="auth">Are you authorized?</label>
            <input id="auth" role="combobox" aria-controls="choices" aria-expanded="false"
             onfocus="this.setAttribute('aria-expanded','true');document.getElementById('choices').hidden=false">
            <input type="hidden" id="committed"><div id="choices" role="listbox" hidden>
            <div role="option" onclick="document.getElementById('auth').value='Yes';
            document.getElementById('auth').setAttribute('aria-expanded','false');
            document.getElementById('committed').value='yes';this.parentElement.hidden=true">Yes</div>
            <div role="option">No</div></div></div>''')
        self.assertEqual(self.page.locator('#committed').input_value(), 'yes')

    def test_unavailable_combobox_option_stays_unconfirmed(self):
        self.fill('''<div class="field"><label for="auth">Are you authorized?</label>
            <input id="auth" role="combobox" aria-controls="choices" aria-expanded="false"
             onfocus="this.setAttribute('aria-expanded','true');document.getElementById('choices').hidden=false">
            <div id="choices" role="listbox" hidden><div role="option">Unknown</div></div></div>''')
        self.assertFalse(self.state.get('filled'))
        self.assertTrue(self.state.get('field_errors'))

    def test_navigation_during_fill_does_not_reuse_stale_fields(self):
        self.page.route('https://jobs.example/next', lambda r:r.fulfill(body='<h1>Next application step</h1>'))
        self.page.set_content('<label>Full name<input name="name" onchange="location.href=\'https://jobs.example/next\'"></label>'
                              '<label>Email<input name="email"></label>')
        snap = batch.snapshot(self.page)
        try:
            batch.fill_supported(self.page, self.packet, self.state, snap)
        except RuntimeError as exc:
            self.assertIn('navigation', str(exc).lower())
        self.assertFalse(any(f.get('question')=='Email' for f in self.state.get('filled', [])))

    def test_live_validation_rejects_uncommitted_typed_dropdown(self):
        from playwright_fast import unverified_required
        self.page.set_content('<label>Are you authorized?<input required role="combobox" value="Yes" aria-expanded="true"></label>')
        missing = unverified_required(batch.snapshot(self.page),self.packet,self.sources,{})
        self.assertEqual(len(missing),1)
        self.assertIn('not been selected',missing[0]['reason'])

    def test_aria_labelled_dropdown_and_persisted_selected_label(self):
        self.fill('''<div class="field"><span id="label">Are you authorized?</span>
            <input id="auth" role="combobox" aria-labelledby="label" aria-controls="choices" aria-expanded="false"
             onfocus="this.setAttribute('aria-expanded','true');document.getElementById('choices').hidden=false">
            <span class="select__single-value"></span><div id="choices" role="listbox" hidden>
            <div role="option" onclick="document.getElementById('auth').value='';
            document.querySelector('.select__single-value').textContent='Yes';
            document.getElementById('auth').setAttribute('aria-expanded','false');this.parentElement.hidden=true">Yes</div>
            </div></div>''')
        from playwright_fast import unverified_required
        snap=batch.snapshot(self.page)
        self.assertTrue(any(x.get('choice_committed') for x in self.state['filled']))
        self.assertFalse(unverified_required(snap,self.packet,self.sources,self.state))

    def test_navigation_during_inspection_retries_without_an_action(self):
        from playwright.sync_api import Locator
        original=Locator.evaluate
        calls=[]
        self.page.set_content('<h1>Example</h1>')
        def interrupted(locator,expression,*args,**kwargs):
            if 'const fields=' in expression and not calls:
                calls.append('navigation')
                raise RuntimeError('Execution context was destroyed, most likely because of a navigation')
            return original(locator,expression,*args,**kwargs)
        with patch.object(Locator,'evaluate',interrupted):
            snap=batch.snapshot(self.page)
        self.assertEqual(snap['frames'][0]['text'],'Example')
        self.assertFalse(self.requests)

    def test_breezy_apply_to_position_navigates_once_to_the_form(self):
        from playwright_fast import run_packets
        from test_application_workflow import FakeBatchTracker
        self.packet['row']={'Company':'Example','Job Title':'Example role','Job URL':self.packet['url'],
                            'Resume Link':self.resume.as_uri()}
        self.page.evaluate("window.name='gecko-101'")
        self.page.set_content('<h1>Example - Example role</h1><a href="https://jobs.example/101/apply">Apply To Position</a>')
        visits=[]
        def form(route):
            visits.append(route.request.url)
            route.fulfill(body='<h1>Example - Example role</h1><label>Full name<input name="name" required></label>'
                '<label>Email<input name="email" required></label><label>Resume<input type="file" name="resume"></label>'
                '<button>Submit application</button>')
        self.page.route('https://jobs.example/101/apply',form)
        reports=run_packets(self.context,[self.packet],FakeBatchTracker([self.packet]),self.sources,
                            self.root/'evidence',allow_submit=False)
        self.assertEqual(reports[0]['status'],'Draft prepared - submission disabled')
        self.assertEqual(visits,['https://jobs.example/101/apply'])
        self.assertEqual(len(self.context.pages),1)


class AgreementRepairTests(unittest.TestCase):
    setUpClass = ApplicationRepairTests.__dict__['setUpClass']
    tearDownClass = ApplicationRepairTests.__dict__['tearDownClass']
    setUp = ApplicationRepairTests.setUp
    fill = ApplicationRepairTests.fill
    # Reuse fixture setup, without rerunning inherited test methods.
    def agreement_source(self):
        record={'id':'APPLICATION-AGREEMENT','meaning':'application_agreement',
            'questions':['I agree to the privacy notice'], 'answer':'Agree',
            'status':'confirmed','confirmed_on':'2026-10-27','scope':{},
            'source':{'kind':'answers','quote':'Confirmed general response: Yes'}}
        self.sources.content['index'].append(record)
        self.sources.lookup_cache.clear()

    def test_styled_required_agreement_is_visible_required_and_selected(self):
        self.agreement_source()
        html='''<fieldset class="ashby-application-form-input-radio-group">
            <label class="ashby-application-form-question-title _required_hash_91">I agree to the privacy notice</label>
            <input type="radio" name="privacy" id="agree" style="display:none"><label for="agree">Agree</label>
            <input type="radio" name="privacy" id="decline" style="display:none"><label for="decline">Disagree</label>
            </fieldset>'''
        self.page.set_content(html)
        from application_forms import missing_questions
        snap=batch.snapshot(self.page)
        self.assertEqual(len(missing_questions(snap)),1)
        self.assertTrue(next(f for f in snap['frames'][0]['fields'] if f['id']=='agree')['visible'])
        batch.fill_supported(self.page,self.packet,self.state,snap)
        self.assertTrue(self.page.locator('#agree').is_checked())
        self.assertFalse(self.page.locator('#decline').is_checked())
        snap=batch.snapshot(self.page)
        self.assertFalse(missing_questions(snap))
        from playwright_fast import unverified_required
        self.assertFalse(unverified_required(snap,self.packet,self.sources,self.state))

    def test_confirmed_checkbox_is_checked_and_verified(self):
        self.agreement_source()
        snap=self.fill('<label for="consent">I agree to the privacy notice</label><input id="consent" type="checkbox" required style="display:none">')
        self.assertTrue(self.page.locator('#consent').is_checked())
        from playwright_fast import unverified_required
        self.assertFalse(unverified_required(snap,self.packet,self.sources,self.state))

    def test_hidden_section_is_not_made_visible_by_its_label(self):
        self.agreement_source()
        self.fill('<div hidden><label>I agree to the privacy notice<input type="checkbox" required></label></div>')
        self.assertFalse(self.state.get('filled'))

    def test_unknown_required_agreement_stays_missing(self):
        from application_forms import missing_questions
        snap=self.fill('<fieldset aria-required="true"><legend>I certify I hold a license</legend>'
            '<input type="radio" name="license" id="yes" style="display:none"><label for="yes">Yes</label></fieldset>')
        self.assertEqual(len(missing_questions(snap)),1)
        self.assertFalse(self.page.locator('#yes').is_checked())

    def test_validation_messages_are_specific_and_ignore_hidden_errors(self):
        from application_forms import validation_messages
        self.page.set_content('<div role="alert">Please agree to the privacy notice.</div>'
            '<div role="alert" hidden>Old error</div>')
        self.assertEqual(validation_messages(self.page),['Please agree to the privacy notice.'])

    def test_agreement_generalization_does_not_answer_experience_or_sms(self):
        from application_forms import answer_for
        self.agreement_source()
        self.assertEqual(answer_for({'type':'checkbox','question':'I accept the terms and conditions'},self.packet,self.sources)['answer'],'Agree')
        for question in ['I agree to receive recruiting text messages under the privacy policy',
                         'I certify I have five years of experience and accept the privacy policy',
                         'Do you agree you have technical SEO experience?']:
            self.assertIsNone(answer_for({'type':'checkbox','question':question},self.packet,self.sources))

    def test_employer_validation_after_click_is_saved_without_retry(self):
        from playwright_fast import run_packets
        from test_application_workflow import FakeBatchTracker
        self.packet['row']={'Company':'Example','Job Title':'Example role','Job URL':self.packet['url'],
                            'Resume Link':self.resume.as_uri()}
        self.page.evaluate("window.name='gecko-101'")
        self.page.set_content('<h1>Example - Example role</h1><label>Full name<input name="name" required></label>'
            '<label>Email<input name="email" required></label><label>Resume<input type="file" name="resume"></label>'
            '<div role="alert" id="validation"></div><button onclick="window.clicks=(window.clicks||0)+1;'
            'document.getElementById(\'validation\').textContent=\'Please agree to the privacy notice\'">Submit application</button>')
        tracker=FakeBatchTracker([self.packet])
        base=self.root/'evidence'
        report=run_packets(self.context,[self.packet],tracker,self.sources,base,allow_submit=True)[0]
        self.assertEqual(report['submission_validation'],['Please agree to the privacy notice'])
        self.assertLess(report['timings']['seconds']['waiting'],5)
        self.assertTrue((base/'101/submission-validation.json').exists())
        self.assertFalse((base/'101/receipt.json').exists())
        run_packets(self.context,[self.packet],tracker,self.sources,base,allow_submit=True)
        self.assertEqual(self.page.evaluate('window.clicks'),1)
        self.assertFalse(any(e[0]=='receipt' for e in tracker.events))

    def test_styled_agreement_reaches_confirmed_fixture_submission(self):
        from playwright_fast import run_packets
        from test_application_workflow import FakeBatchTracker
        self.agreement_source()
        self.packet['row']={'Company':'Example','Job Title':'Example role','Job URL':self.packet['url'],
                            'Resume Link':self.resume.as_uri()}
        self.page.evaluate("window.name='gecko-101'")
        self.page.set_content('<h1>Example - Example role</h1><label>Full name<input name="name" required></label>'
            '<label>Email<input name="email" required></label><label>Resume<input type="file" name="resume"></label>'
            '<fieldset><label class="ashby-application-form-question-title _required_test_1">I agree to the privacy notice</label>'
            '<input type="radio" name="privacy" id="agree" style="display:none"><label for="agree">Agree</label></fieldset>'
            '<button onclick="if(document.getElementById(\'agree\').checked){document.body.remove();setTimeout(()=>{'
            'const b=document.createElement(\'body\');b.innerHTML=\'<h1>Application received</h1>\';document.documentElement.appendChild(b)},150)}">Submit application</button>')
        tracker=FakeBatchTracker([self.packet])
        base=self.root/'evidence'
        report=run_packets(self.context,[self.packet],tracker,self.sources,base,allow_submit=True)[0]
        self.assertTrue(report['tracker']['verified'])
        self.assertTrue((base/'101/receipt.json').exists())
        self.assertTrue(any(e[0]=='receipt' for e in tracker.events))

    def test_breezy_question_labels_and_checkbox_group(self):
        record={'id':'platforms','meaning':'platforms','questions':['Which platforms?'],
            'answer':'Google Ads; Microsoft Ads','choices':['Google Ads','Microsoft Ads'],
            'status':'confirmed','confirmed_on':'2026-10-27','scope':{},
            'source':{'kind':'answers','quote':'Confirmed general response: Yes'}}
        self.sources.content['index'].append(record);self.sources.lookup_cache.clear()
        snap=self.fill('<li class="question"><h3>Which platforms?<span>*</span></h3><ul class="options">'
            '<li class="option"><input name="platform" type="checkbox" required><span>Google Ads</span></li>'
            '<li class="option"><input name="platform" type="checkbox" required><span>Microsoft Ads</span></li>'
            '<li class="option"><input name="platform" type="checkbox" required><span>Unknown Ads</span></li></ul></li>')
        from application_forms import missing_questions
        from playwright_fast import unverified_required
        self.assertEqual(self.page.locator('input:checked').count(),2)
        self.assertFalse(missing_questions(snap))
        self.assertFalse(unverified_required(snap,self.packet,self.sources,self.state))

    def test_breezy_empty_angular_select_option_is_not_an_answer(self):
        snap=self.fill('<li class="question"><h3>Are you authorized?</h3><select name="question" required>'
            '<option value="? undefined:undefined ?"></option><option>Yes</option><option>No</option></select></li>')
        self.assertEqual(self.page.locator('select').input_value(),'Yes')
        self.assertEqual(snap['frames'][0]['fields'][0]['question'],'Are you authorized?')

    def test_breezy_summary_uses_local_heading(self):
        self.page.set_content('<div class="section"><div class="section-header"><h3>Experience Summary*</h3></div>'
            '<textarea name="cSummary" required></textarea></div>')
        from application_forms import missing_questions
        self.assertEqual(missing_questions(batch.snapshot(self.page))[0]['question'],'Experience Summary*')

    def test_breezy_upload_waits_for_employer_processing(self):
        self.fill('<label>Resume<input type="file" name="resume" onchange="document.getElementById(\'send\').disabled=true;'
            'setTimeout(()=>document.getElementById(\'send\').disabled=false,200)"></label>'
            '<button id="send" ng-disabled="uploadingResume || isSubmitting">Submit application</button>')
        self.assertTrue(self.state['resume']['upload_verified'])
        self.assertTrue(self.page.locator('#send').is_enabled())

    def test_disabled_submit_waits_and_reinspects_before_sending(self):
        from playwright_fast import run_packets
        from test_application_workflow import FakeBatchTracker
        self.packet['row']={'Company':'Example','Job Title':'Example role','Job URL':self.packet['url'],
                            'Resume Link':self.resume.as_uri()}
        self.page.evaluate("window.name='gecko-101'")
        self.page.set_content('<h1>Example - Example role</h1><label>Full name<input name="name" required></label>'
            '<label>Email<input name="email" required></label><label>Resume<input type="file" name="resume" '
            'onchange="setTimeout(()=>document.getElementById(\'send\').disabled=false,800)"></label>'
            '<button id="send" disabled onclick="document.body.innerHTML=\'<h1>Application received</h1>\'">Submit application</button>')
        tracker=FakeBatchTracker([self.packet])
        report=run_packets(self.context,[self.packet],tracker,self.sources,self.root/'evidence',allow_submit=True)[0]
        self.assertTrue(report['tracker']['verified'])


class ConfirmationRecoveryTests(unittest.TestCase):
    def test_recovery_requires_current_attempt_identity_time_and_confirmation(self):
        from copy import deepcopy
        from application_runtime import save
        from playwright_fast import receipt_from_recovery
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)
            packet={'id':101,'company':'Example','title':'Example role'}
            attempt=dict(packet,url='https://jobs.example/101/apply',attempted_at='2026-10-27T13:00:00+00:00')
            recovery=dict(packet,url=attempt['url']+'/submitted',captured_at='2026-10-27T13:00:02+00:00',
                snapshot={'frames':[{'text':'Application Submitted\nYour application has been submitted successfully. Good luck!','fields':[]}]})
            self.assertIsNone(receipt_from_recovery(recovery,packet,out))
            save(out/'submission-attempt.json',attempt)
            self.assertTrue(receipt_from_recovery(recovery,packet,out)['confirmation_verified'])
            for changes in ({'id':102},{'url':'https://other.example/101/apply/submitted'},
                            {'url':'https://jobs.example/other/submitted'},
                            {'captured_at':'2026-10-27T12:59:00+00:00'},
                            {'snapshot':{'frames':[{'text':'Please complete your application','fields':[]}]}}):
                candidate=deepcopy(recovery);candidate.update(changes)
                self.assertIsNone(receipt_from_recovery(candidate,packet,out))
            candidate=deepcopy(recovery)
            candidate['snapshot']['frames'][0]['fields']=[{'tag':'INPUT','visible':True}]
            self.assertIsNone(receipt_from_recovery(candidate,packet,out))


class AnswerCoverageTests(unittest.TestCase):
    def test_saved_salary_and_linkedin_exact_wording_variants(self):
        sources=BatchSources().refresh()
        packet={'id':2990,'company':'Graphite'}
        self.assertEqual(sources.resolve('What are your salary expectations? (USD)',packet)['answer'],'70000')
        self.assertEqual(sources.resolve('What is your target annual salary? Please include the currency.',packet)['answer'],'$70,000')
        self.assertIn('linkedin.com',sources.resolve('What is your LinkedIn (URL)?',packet)['answer'])
        self.assertIsNone(sources.resolve('What was your salary at your previous employer?',packet))
        self.assertIsNone(sources.resolve('What is the LinkedIn URL of your manager?',packet))

    def test_confirmed_pearmill_scenario_is_reusable_only_for_pearmill(self):
        sources = BatchSources().refresh()
        question = ('One of your accounts is pacing 25% under budget with three days left in the month. '
            'Impression share lost to budget is close to zero. CPA is on target, but conversions are '
            'tracking about 20% below the monthly goal. What do you do, and what do you tell the client?')
        record = sources.resolve(question, {'id':2981, 'company':'Pearmill'})
        self.assertIsNotNone(record)
        self.assertIn(record['answer'], sources.content['answers'])
        self.assertIsNone(sources.resolve(question, {'id':101, 'company':'Other'}))


if __name__ == '__main__':
    unittest.main()
