import unittest
import json
import os


class TestTertileMonotonicity(unittest.TestCase):
    def test_ca_median_energy_decreases_or_stays_same_with_higher_shortfall_target(
        self,
    ):
        """
        CA median energy in a tertile cannot increase when the shortfall target
        is increased from 0.1% to 1.0% (higher shortfall budget allows lower energy).
        """
        json_path = "eval/headline_results_v4.json"
        if not os.path.exists(json_path):
            self.skipTest(f"{json_path} not found")

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        msp = data.get("matched_shortfall_pareto", {})
        self.assertIn("0.1%", msp)
        self.assertIn("1.0%", msp)

        # Check across all arms
        for arm in ["rolling", "scale_aware", "static", "aci_005", "aci_020"]:
            tert_01 = msp["0.1%"][arm]["tertiles"]
            tert_10 = msp["1.0%"][arm]["tertiles"]

            for tert_name in ["low_load", "mid_load", "high_load"]:
                ca_med_01 = tert_01[tert_name]["ca_median_energy"]
                ca_med_10 = tert_10[tert_name]["ca_median_energy"]
                self.assertLessEqual(
                    ca_med_10,
                    ca_med_01,
                    f"Arm {arm}, tertile {tert_name}: CA median energy at 1.0% ({ca_med_10}) "
                    f"must not exceed that at 0.1% ({ca_med_01})",
                )


if __name__ == "__main__":
    unittest.main()
