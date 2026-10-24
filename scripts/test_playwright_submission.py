"""Exercise irreversible-send guards against a local browser form, never an employer."""
import pathlib
import hashlib
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from playwright.sync_api import sync_playwright
import playwright_batch as batch


class SubmissionTests(unittest.TestCase):
    def test_guards_receipt_and_no_resend(self):
        with tempfile.TemporaryDirectory() as folder, sync_playwright() as pw:
            browser=pw.chromium.launch(channel='chrome',headless=True)
            page=browser.new_page()
            resume=pathlib.Path(folder)/'example.docx';resume.write_bytes(b'Synthetic fixture')
            page.set_content('''<h1>Example role</h1><input required id="answer"><input type="file" id="resume">
                <p>example.docx Success!</p>
                <button id="send" onclick="document.body.innerHTML='<h1>Application received!</h1>'">Submit application</button>''')
            page.locator('#resume').set_input_files(str(resume))
            packet={'id':999999,'company':'Example','title':'Example role','resume':str(resume),'row':{'Resume Link':'file:///example.docx'}}
            command={'expected_url':'about:blank','selector':'#send','confirmation_text':'Application received!',
                     'all_required_answers_verified':True,'attachment_verified':False}
            out=pathlib.Path(folder);state={'resume':{'filename':resume.name,'bytes':resume.stat().st_size,'sha256':hashlib.sha256(resume.read_bytes()).hexdigest()}}
            with self.assertRaisesRegex(RuntimeError,'attachment'):
                batch.submit(page,packet,state,command,out)
            self.assertFalse((out/'submission-attempt.json').exists())
            command['attachment_verified']=True
            row={'Company':'Example','Job Title':'Example role','Resume Link':'file:///example.docx'}
            with patch.object(batch,'fresh_row',return_value=row):
                with self.assertRaisesRegex(AssertionError,'validation incomplete'):
                    batch.submit(page,packet,state,command,out)
                self.assertFalse((out/'submission-attempt.json').exists())
                page.locator('#answer').fill('Confirmed answer')
                with patch.object(batch.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='{"verified":true}',stderr='')):
                    batch.submit(page,packet,state,command,out)
                self.assertTrue((out/'receipt.json').exists())
                self.assertEqual(state['status'],'Applied — employer confirmed')
                with self.assertRaisesRegex(RuntimeError,'Prior submission attempt'):
                    batch.submit(page,packet,state,command,out)
            browser.close()


if __name__=='__main__': unittest.main()
