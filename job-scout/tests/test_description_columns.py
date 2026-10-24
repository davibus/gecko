import sys
from pathlib import Path
import unittest
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from description_columns import description_column,description_value,adopt_split_schema
from google_tracker import Config,GoogleTracker
from tests.test_google_tracker import FakeSheets
from models import RawListing
from normalize import normalize


class DescriptionColumnsTests(unittest.TestCase):
    def test_gecko_and_firecrawl_publish_to_separate_reordered_columns(self):
        for backend in ('Gecko','Firecrawl'):
            for position in (0,7):
                fake=FakeSheets()
                for i,row in enumerate(fake.data['Job Scout']):
                    row.insert(position,'Gecko Job Description' if i==0 else '')
                    row.insert(position+2,'FireCrawl Job Description' if i==0 else '')
                tracker=GoogleTracker(Config('test',Path('unused'),'Job Tracker','Job Scout'),fake)
                job=normalize(RawListing('test','new','https://example.test/new','Digital Marketing Manager','Example',
                    location='Remote',description='Full original posting. '*50))
                job.id=100;job.found_using=backend
                tracker.upsert_scout([job])
                saved=tracker.scout().rows[-1][1]
                target='Gecko Job Description' if backend=='Gecko' else 'Firecrawl Job Description'
                other='Firecrawl Job Description' if backend=='Gecko' else 'Gecko Job Description'
                self.assertEqual(saved[target],job.description)
                self.assertEqual(saved[other],'')
                self.assertEqual(saved['Job Description'],job.description) # read alias, not a new column
                self.assertNotIn('Job Description',tracker.scout().header_values)

    def test_missing_tool_column_does_not_route_to_other_tool(self):
        with self.assertRaisesRegex(RuntimeError,'Firecrawl'):
            description_column({'Gecko Job Description':1},'Firecrawl')

    def test_old_single_column_remains_supported(self):
        self.assertEqual(description_column({'Job Description':1},'Firecrawl'),'Job Description')

    def test_reader_uses_complete_available_description(self):
        self.assertEqual(description_value({'Gecko Job Description':'Short snippet',
                         'FireCrawl Job Description':'Complete saved employer posting'}),'Complete saved employer posting')

    def test_adopting_renamed_columns_preserves_live_sheet_and_other_edits(self):
        base={'1':{'Job Description':'old','Notes':'old note'}}
        local={'1':{'Job Description':'old','Notes':'local edited note'}}
        remote={'1':{'Gecko Job Description':'','FireCrawl Job Description':'user edited description'}}
        new_base,new_local,headers=adopt_split_schema(base,local,remote,['Job Description','Notes'],
                    ['Gecko Job Description','FireCrawl Job Description','Notes'])
        self.assertNotIn('Job Description',headers)
        self.assertEqual(new_local['1']['Notes'],'local edited note')
        self.assertEqual(new_local['1']['FireCrawl Job Description'],'user edited description')
        self.assertEqual(new_base['1']['FireCrawl Job Description'],'user edited description')
        self.assertEqual(base['1']['Job Description'],'old')

    def test_unsynced_local_description_is_never_discarded(self):
        with self.assertRaisesRegex(ValueError,'unsynchronized'):
            adopt_split_schema({'1':{'Job Description':'old'}},{'1':{'Job Description':'local new'}},
                {'1':{'Gecko Job Description':'','FireCrawl Job Description':'old'}},['Job Description'],
                ['Gecko Job Description','FireCrawl Job Description'])

    def test_pending_new_job_routes_old_field_by_search_tool(self):
        _,local,_=adopt_split_schema({}, {'2':{'Job Description':'New posting','Found Using':'Firecrawl'}},{},
            ['Job Description','Found Using'],['Gecko Job Description','FireCrawl Job Description','Found Using'])
        self.assertEqual(local['2']['FireCrawl Job Description'],'New posting')

    def test_new_row_word_count_reads_both_description_columns(self):
        from sheet_ranges import plan_ranges
        headers=['ID','Gecko Job Description','FireCrawl Job Description','# Job Desc Words']
        rows=[(2,{'ID':1,'# Job Desc Words':'=COUNTA(SPLIT(C2," "))'}),(3,{'ID':2})]
        _,cells=plan_ranges({'properties':{'sheetId':1}},headers,rows,{})
        formula=cells[3,3]['userEnteredValue']['formulaValue']
        self.assertIn('Gecko Job Description',formula)
        self.assertIn('Firecrawl Job Description',formula)
        self.assertIn('INDEX(3:3',formula)


if __name__=='__main__':unittest.main()
