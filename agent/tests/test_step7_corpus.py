from __future__ import annotations

import json
from pathlib import Path
import unittest

from surgical_contracts import CommandIntent


CASES = Path(__file__).parents[1] / "evals" / "step7_cases.json"


class Step7CorpusTests(unittest.TestCase):
    def test_fixed_corpus_is_complete_and_well_formed(self):
        cases = json.loads(CASES.read_text(encoding="utf-8"))
        ids = [case["id"] for case in cases]
        categories = {case["category"] for case in cases}
        valid_intents = {intent.value for intent in CommandIntent}

        self.assertEqual(len(cases), 13)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(case["prompt"].strip() for case in cases))
        self.assertTrue(
            all(case["expected"]["intent"] in valid_intents for case in cases)
        )
        for required in {
            "明确入点和靶点",
            "只有入点",
            "方向和明确距离",
            "方向和模糊一点",
            "缺失单位",
            "缺失坐标系",
            "坐标顺序含糊",
            "同一句多组坐标",
            "否定句",
            "停止",
            "急停",
            "与机械臂无关",
        }:
            self.assertIn(required, categories)


if __name__ == "__main__":
    unittest.main()
