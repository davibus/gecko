import unittest
from recover_gecko_pending import ROOT
from location_evidence import source_location_blocker
from models import RawListing
class CountryEvidence(unittest.TestCase):
    def raw(self,metadata):return RawListing('ashby','id','https://example.org/id','Marketing Manager','Employer',remote_type='remote',metadata=metadata)
    def test_foreign_remote_is_not_global(self):
        self.assertIn('United Kingdom',source_location_blocker(self.raw({'isRemote':True,'address':{'postalAddress':{'addressCountry':'United Kingdom'}}})))
    def test_us_country(self):self.assertEqual('',source_location_blocker(self.raw({'country':'US'})))
    def test_secondary_us_location_is_retained(self):
        self.assertEqual('',source_location_blocker(self.raw({'address':{'postalAddress':{'addressCountry':'Canada'}},'secondaryLocations':[{'address':{'postalAddress':{'addressCountry':'United States'}}}]})))
    def test_workable_locations(self):self.assertIn('AU',source_location_blocker(self.raw({'locations':[{'country':'AU'}]})))
    def test_unknown_is_not_invented(self):self.assertEqual('',source_location_blocker(self.raw({})))
    def test_country_names(self):self.assertIn('Egypt',source_location_blocker(self.raw({'country':'Egypt'})))
    def test_hybrid_overrides_remote_flag(self):
        raw=self.raw({'country':'US','workplaceType':'Hybrid','isRemote':True});raw.location='New York, United States'
        self.assertIn('hybrid',source_location_blocker(raw))
    def test_utah_hybrid_can_continue_through_other_filters(self):
        raw=self.raw({'country':'US','workplaceType':'Hybrid'});raw.location='Murray, UT, US'
        self.assertEqual('',source_location_blocker(raw))
    def test_explicit_applicant_country_overrides_office_country(self):
        raw=self.raw({'applicantLocationRequirements':{'@type':'Country','name':'Canada'},'jobLocation':{'address':{'addressCountry':'US'}}})
        self.assertEqual('',source_location_blocker(raw))
    def test_applicant_us_allows_foreign_head_office(self):
        raw=self.raw({'applicantLocationRequirements':{'@type':'Country','name':'USA'},'jobLocation':{'address':{'addressCountry':'Canada'}}})
        self.assertEqual('',source_location_blocker(raw))
if __name__=='__main__':unittest.main()
