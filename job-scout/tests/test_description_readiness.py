import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from description_readiness import assess

class ReadinessTests(TestCase):
    def record(self,text):
        return {'id':'1','company':'Acme','title':'Paid Search Manager','description':text}

    def test_empty_description_is_no_without_inference(self):
        c=Mock()
        result=assess([self.record('')],client=c)
        self.assertEqual(result['1']['value'],'No');c.complete.assert_not_called()

    def test_content_review_is_cached_and_not_a_word_threshold(self):
        c=Mock();c.complete.return_value={'reviews':[{'id':'1','enough':True,'reason':'Specific duties and required skill are stated.',
            'evidence':['Own paid search campaigns','Google Ads experience required']}]}
        text='Own paid search campaigns. Google Ads experience required.'
        with TemporaryDirectory() as root:
            result=assess([self.record(text)],client=c,cache_dir=root)
            again=assess([self.record(text)],client=c,cache_dir=root)
        self.assertEqual(result['1']['value'],'Yes');self.assertTrue(again['1']['cached']);self.assertEqual(c.complete.call_count,1)

    def test_random_long_text_is_no(self):
        c=Mock();c.complete.return_value={'reviews':[{'id':'1','enough':False,'reason':'Random unrelated text has no job duties.','evidence':[]}]}
        with TemporaryDirectory() as root:
            self.assertEqual(assess([self.record('Banana mountain lorem ipsum. '*1000)],client=c,cache_dir=root)['1']['value'],'No')

    def test_unsupported_affirmative_is_not_published(self):
        c=Mock();c.complete.return_value={'reviews':[{'id':'1','enough':True,'reason':'Looks good','evidence':['Invented duty','Invented skill']}]}
        with TemporaryDirectory() as root:
            result=assess([self.record('Unrelated text')],client=c,cache_dir=root)
            self.assertEqual(result['1']['value'],'No');self.assertEqual(result['1']['status'],'pending')
            self.assertEqual(list(Path(root).glob('*.json')),[])

    def test_runtime_failure_fails_closed_without_caching(self):
        c=Mock();c.complete.side_effect=RuntimeError('connection unavailable')
        with TemporaryDirectory() as root:
            result=assess([self.record('Actual job text')],client=c,cache_dir=root)
        self.assertEqual(result['1']['value'],'No');self.assertEqual(result['1']['status'],'pending')
