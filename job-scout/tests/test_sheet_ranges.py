import sys
from pathlib import Path
from copy import deepcopy
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sheet_ranges import plan_ranges,shift_formula


class RangeExtensionTests(unittest.TestCase):
    def fixture(self):
        area={'sheetId':1,'startRowIndex':0,'endRowIndex':10,'startColumnIndex':0,'endColumnIndex':4}
        sheet={'properties':{'sheetId':1},'basicFilter':{'range':area,'criteria':{'0':{'hiddenValues':['42']}}},
               'conditionalFormats':[{'ranges':[{**area,'startRowIndex':1}],
                                      'booleanRule':{'condition':{'type':'CUSTOM_FORMULA','values':[{'userEnteredValue':'=$A2>0'}]},'format':{'backgroundColor':{'red':1}}}}],
               'filterViews':[{'filterViewId':2,'title':'Keep me','range':deepcopy(area),'criteria':{'0':{'hiddenValues':['9']}}}]}
        headers=['ID','Notes','# Words','Create Resume']
        rows=[(10,{'ID':1,'# Words':'=LEN(B10)','Create Resume':'=IF(B10="A10","Yes","No")'}),
              (11,{'ID':2,'Notes':'Keep this'}),(12,{'ID':3,'# Words':7})]
        cells={(10,0):{'userEnteredValue':{'numberValue':1},'userEnteredFormat':{'numberFormat':{'type':'NUMBER','pattern':'0'}}},
               (11,0):{'userEnteredValue':{'numberValue':2}},
               (12,0):{'userEnteredValue':{'numberValue':3},'userEnteredFormat':{'backgroundColor':{'red':1}}},
               (12,2):{'userEnteredValue':{'numberValue':7}}}
        return sheet,headers,rows,cells

    def test_extends_filters_and_rules_without_changing_choices(self):
        sheet,headers,rows,cells=self.fixture();original=deepcopy(sheet)
        requests,expected=plan_ranges(sheet,headers,rows,cells)
        basic=next(r['setBasicFilter']['filter'] for r in requests if 'setBasicFilter' in r)
        self.assertEqual(basic['range']['endRowIndex'],12)
        self.assertEqual(basic['criteria'],sheet['basicFilter']['criteria'])
        self.assertEqual(sheet,original)
        self.assertTrue(any('updateFilterView' in r for r in requests))
        self.assertTrue(any('updateConditionalFormatRule' in r for r in requests))
        self.assertEqual(expected[11,2]['userEnteredValue']['formulaValue'],'=LEN(B11)')
        self.assertNotIn((12,2),expected)  # manual number remains
        self.assertEqual(expected[11,3]['userEnteredValue']['formulaValue'],'=IF(B11="A10","Yes","No")')
        self.assertNotIn('userEnteredValue',expected[11,0])  # ID never copied

    def test_reordered_new_columns_expand_header_width(self):
        sheet,headers,rows,cells=self.fixture()
        headers=['Notes','ID','Create Resume','# Words','Custom']
        requests,expected=plan_ranges(sheet,headers,rows,cells)
        self.assertEqual(requests[0]['setBasicFilter']['filter']['range']['endColumnIndex'],5)
        self.assertEqual(expected[11,3]['userEnteredValue']['formulaValue'],'=LEN(B11)')

    def test_existing_formula_and_format_are_preserved(self):
        sheet,headers,rows,cells=self.fixture()
        cells[11,2]={'userEnteredValue':{'formulaValue':'=99'},'userEnteredFormat':{'textFormat':{'bold':True}}}
        cells[11,0]['userEnteredFormat']={'numberFormat':{'type':'TEXT'}}
        _,expected=plan_ranges(sheet,headers,rows,cells)
        self.assertNotIn((11,2),expected)
        self.assertNotIn((11,0),expected)

    def test_open_ended_ranges_are_not_narrowed(self):
        sheet,headers,rows,cells=self.fixture()
        del sheet['basicFilter']['range']['endRowIndex']
        requests,_=plan_ranges(sheet,headers,rows,cells,appended_rows=[11,12])
        self.assertFalse(any('setBasicFilter' in r for r in requests))

    def test_removed_filter_stays_off_but_new_row_formulas_extend(self):
        sheet,headers,rows,cells=self.fixture()
        del sheet['basicFilter']
        requests,expected=plan_ranges(sheet,headers,rows,cells)
        self.assertFalse(any('setBasicFilter' in r for r in requests))
        self.assertEqual(expected[11,2]['userEnteredValue']['formulaValue'],'=LEN(B11)')

    def test_short_custom_rules_are_not_extended(self):
        sheet,headers,rows,cells=self.fixture()
        sheet['conditionalFormats'][0]['ranges'][0]['endRowIndex']=4
        requests,_=plan_ranges(sheet,headers,rows,cells)
        self.assertFalse(any('updateConditionalFormatRule' in r for r in requests))

    def test_no_cross_row_paste_or_value_copy(self):
        requests,expected=plan_ranges(*self.fixture())
        self.assertFalse(any('copyPaste' in r for r in requests))
        for value in expected.values():
            if 'userEnteredValue' in value:self.assertIn('formulaValue',value['userEnteredValue'])

    def test_formula_references_keep_strings_and_absolute_rows(self):
        self.assertEqual(shift_formula('=IF($A10="A10",SUM(10:10,$1:$1,B$2),\'Sheet 2\'!C10)',3),
                         '=IF($A13="A10",SUM(13:13,$1:$1,B$2),\'Sheet 2\'!C13)')

    def test_renamed_counts_extend_even_when_total_already_reaches_bottom(self):
        headers=['ID','Enough Data','# (Gecko) Words','# (FC) Job Desc Words','Total Words']
        rows=[(10,{'ID':1,'Enough Data':'Yes','# (Gecko) Words':'=LEN(B10)',
                    '# (FC) Job Desc Words':'=LEN(C10)','Total Words':'=C10+D10'}),
              (11,{'ID':2,'Enough Data':'','Total Words':'=C11+D11'})]
        sheet={'properties':{'sheetId':1}}
        cells={(10,1):{'userEnteredValue':{'stringValue':'Yes'},
                       'userEnteredFormat':{'backgroundColor':{'green':1}},
                       'dataValidation':{'condition':{'type':'ONE_OF_LIST','values':[{'userEnteredValue':'Yes'},{'userEnteredValue':'No'}]}}},
               (11,4):{'userEnteredValue':{'formulaValue':'=C11+D11'}}}
        requests,expected=plan_ranges(sheet,headers,rows,cells)
        self.assertEqual(expected[11,2]['userEnteredValue']['formulaValue'],'=LEN(B11)')
        self.assertEqual(expected[11,3]['userEnteredValue']['formulaValue'],'=LEN(C11)')
        self.assertNotIn('userEnteredValue',expected[11,1])
        self.assertIn('dataValidation',expected[11,1])
        self.assertNotIn((11,4),expected)

    def test_enough_data_formula_extends_without_overwriting_manual_answers(self):
        headers=['ID','Enough Data']
        rows=[(2,{'ID':1,'Enough Data':'=IF(A2>0,"Yes","No")'}),
              (3,{'ID':2,'Enough Data':'No'}),(4,{'ID':3})]
        cells={(3,1):{'userEnteredValue':{'stringValue':'No'}}}
        _,expected=plan_ranges({'properties':{'sheetId':1}},headers,rows,cells)
        self.assertEqual(expected[4,1]['userEnteredValue']['formulaValue'],'=IF(A4>0,"Yes","No")')
        self.assertNotIn((3,1),expected)


if __name__=='__main__':unittest.main()
