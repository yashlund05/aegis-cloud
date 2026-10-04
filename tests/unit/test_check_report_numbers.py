import unittest
import json
import tempfile
import os
from eval.check_report_numbers import check_report

class TestCheckReportNumbers(unittest.TestCase):
    def setUp(self):
        self.data = {
            "val1": 121.79,
            "val2": -75.132,
            "nested": {
                "pct": 0.8677,
                "count": 42
            }
        }
        self.json_file = tempfile.NamedTemporaryFile("w", delete=False, suffix=".json")
        json.dump(self.data, self.json_file)
        self.json_file.close()

    def tearDown(self):
        os.remove(self.json_file.name)

    def test_matched_numbers(self):
        md_content = """
        # Test Report
        The value is 121.79 and delta is -75.13.
        Coverage percentage is 86.77% with count 42.
        """
        md_file = tempfile.NamedTemporaryFile("w", delete=False, suffix=".md")
        md_file.write(md_content)
        md_file.close()

        unmatched = check_report(md_file.name, self.json_file.name)
        os.remove(md_file.name)
        self.assertEqual(unmatched, [])

    def test_unmatched_numbers(self):
        md_content = """
        # Bad Report
        Fake value is 999.99 and 171.61.
        """
        md_file = tempfile.NamedTemporaryFile("w", delete=False, suffix=".md")
        md_file.write(md_content)
        md_file.close()

        unmatched = check_report(md_file.name, self.json_file.name)
        os.remove(md_file.name)
        self.assertIn("999.99", unmatched)
        self.assertIn("171.61", unmatched)

    def test_rounding(self):
        md_content = """
        # Rounded Report
        Value rounded to 1 decimal: 121.8.
        """
        md_file = tempfile.NamedTemporaryFile("w", delete=False, suffix=".md")
        md_file.write(md_content)
        md_file.close()

        unmatched = check_report(md_file.name, self.json_file.name)
        os.remove(md_file.name)
        self.assertEqual(unmatched, [])

if __name__ == "__main__":
    unittest.main()
