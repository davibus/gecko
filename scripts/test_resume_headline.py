"""Job-specific headline selection and reviewed custom-positioning safeguards."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import gecko_v2 as g


class HeadlineTests(unittest.TestCase):
    def test_examples_follow_the_target_role(self):
        lines = ["Variations of Specialization/Main Titles",
                 "• Paid Search | Campaign Automation | Team Leadership",
                 "• E-Commerce Technology | Shopify | APIs | Automation"]
        with patch.object(g, "master_lines", return_value=lines):
            self.assertTrue(g.select_headline("Google Ads paid search", "Paid Search Manager").startswith("Paid Search"))
            self.assertTrue(g.select_headline("Shopify APIs commerce", "E-Commerce Technology Lead").startswith("E-Commerce"))

    def test_custom_wording_is_allowed_but_review_cannot_be_reused_after_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            listing = Path(folder) / "job.md"
            listing.write_text("Paid acquisition and campaign optimization", encoding="utf-8")
            plan = {"listing": str(listing), "job": {"title": "Paid Search Lead"}, "resume": {}}
            with patch.object(g, "source_fingerprint", return_value="master-hash"):
                g.set_reviewed_headline(plan, "Paid Acquisition | Campaign Optimization", "Supported by master paid-media accomplishments.")
                g.verify_headline(plan, listing.read_text())
                plan["resume"]["headline"] = "Unsupported replacement"
                with self.assertRaisesRegex(ValueError, "changed"):
                    g.verify_headline(plan, listing.read_text())
                plan["resume"]["headline"] = plan["resume"]["headline_review"]["headline"]
                listing.write_text("Different role", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "stale"):
                    g.verify_headline(plan, listing.read_text())

    def test_missing_examples_do_not_silently_use_generic_default(self):
        with patch.object(g, "master_lines", return_value=["Dave Call"]):
            with self.assertRaisesRegex(ValueError, "missing Variations"):
                g.select_headline("Paid search", "Manager")


if __name__ == "__main__":
    unittest.main()
