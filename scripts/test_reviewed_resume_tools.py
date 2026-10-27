import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import gecko_v2 as v2

class ReviewedToolTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.listing=Path(self.temp.name)/'job.md';self.listing.write_text('Marketing operations, CRM, analytics and automation')
        self.tools=['Python','SQL','Funnel.io','Tableau','Power BI','Google Analytics 4','HubSpot','Salesforce']
        self.source=' '.join(self.tools)
        self.plan={'listing':str(self.listing),'resume':{}}
        for patcher in (patch.object(v2,'source_text',return_value=self.source),patch.object(v2,'source_fingerprint',return_value='current')):
            patcher.start();self.addCleanup(patcher.stop)
    def test_supported_reviewed_selection_survives_normal_validation(self):
        v2.set_reviewed_tools(self.plan,self.tools,'These master-supported products match CRM, data and automation responsibilities.')
        self.assertEqual(v2.tools_for_plan(self.plan,self.listing.read_text(),self.source),self.tools)
    def test_source_change_invalidates_review(self):
        v2.set_reviewed_tools(self.plan,self.tools,'Relevant supported stack')
        with patch.object(v2,'source_fingerprint',return_value='changed'),self.assertRaisesRegex(ValueError,'stale'):
            v2.tools_for_plan(self.plan,self.listing.read_text(),self.source)
    def test_listing_change_invalidates_review(self):
        v2.set_reviewed_tools(self.plan,self.tools,'Relevant supported stack');self.listing.write_text('Different posting')
        with self.assertRaisesRegex(ValueError,'stale'):v2.tools_for_plan(self.plan,self.listing.read_text(),self.source)
    def test_changed_selection_invalidates_review(self):
        v2.set_reviewed_tools(self.plan,self.tools,'Relevant supported stack');self.plan['resume']['tools_platforms']=list(reversed(self.tools))
        with self.assertRaisesRegex(ValueError,'stale'):v2.tools_for_plan(self.plan,self.listing.read_text(),self.source)
    def test_unsupported_product_is_rejected(self):
        with self.assertRaises(ValueError):v2.set_reviewed_tools(self.plan,self.tools[:-1]+['Fiction BI'],'Relevant')
    def test_canonical_product_absent_from_master_is_rejected(self):
        with patch.object(v2,'source_text',return_value=' '.join(self.tools[1:])),self.assertRaises(ValueError):
            v2.set_reviewed_tools(self.plan,self.tools,'Relevant')
    def test_minimum_count_and_duplicate_guards_remain(self):
        for tools in (self.tools[:7],self.tools[:-1]+[self.tools[0]]):
            with self.subTest(tools=tools),self.assertRaises(ValueError):v2.set_reviewed_tools(self.plan,tools,'Relevant')

if __name__=='__main__':unittest.main()
