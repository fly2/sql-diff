import csv
import os
import tempfile
import unittest

import sql_diff


OLD_SQL = """
CREATE OR REPLACE PACKAGE BODY PKG_SAMPLE IS
  FUNCTION F_TEST(P_ID NUMBER DEFAULT 1) RETURN NUMBER IS
  BEGIN
    RETURN NVL(P_ID, 0);
  END F_TEST;
END PKG_SAMPLE;
/
"""

NEW_SQL = """
CREATE OR REPLACE PACKAGE BODY PKG_SAMPLE AS
  FUNCTION F_TEST(P_ID NUMERIC := 1) RETURN NUMERIC AS
  DECLARE
  BEGIN
    RETURN COALESCE(P_ID, 0);
  END;
END PKG_SAMPLE;
/
"""


class WordDiffTest(unittest.TestCase):
    def test_semantic_normalization_ignores_common_conversion_tokens(self):
        old_body = sql_diff.extract_body(OLD_SQL, "PKG_SAMPLE")
        new_body = sql_diff.extract_body(NEW_SQL, "PKG_SAMPLE")

        old_words, new_words, changed_words, _, old_func_count, changed_func_count, _, _ = (
            sql_diff.compute_scheme_diff(
                old_body,
                new_body,
                sql_diff.normalize_semantic,
            )
        )

        self.assertGreater(old_words, 0)
        self.assertGreater(new_words, 0)
        self.assertEqual(changed_words, 0)
        self.assertEqual(old_func_count, 1)
        self.assertEqual(changed_func_count, 0)

    def test_main_writes_summary_and_detail_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_dir = os.path.join(tmp, "old")
            new_dir = os.path.join(tmp, "new")
            output_dir = os.path.join(tmp, "output")
            os.makedirs(old_dir)
            os.makedirs(new_dir)

            with open(os.path.join(old_dir, "PKG_SAMPLE.sql"), "w", encoding="utf-8") as f:
                f.write(OLD_SQL)
            with open(os.path.join(new_dir, "PKG_SAMPLE.sql"), "w", encoding="utf-8") as f:
                f.write(NEW_SQL)

            sql_diff.main(["--old", old_dir, "--new", new_dir, "--output", output_dir])

            summary_path = os.path.join(output_dir, "diff_summary.csv")
            detail_path = os.path.join(output_dir, "diff_detail.csv")

            self.assertTrue(os.path.exists(summary_path))
            self.assertTrue(os.path.exists(detail_path))

            with open(detail_path, "r", encoding="utf-8-sig", newline="") as f:
                rows = list(csv.reader(f))

            self.assertEqual(rows[0][-1], "方案")
            self.assertEqual(rows[1][-1], "方案1(语义归一化)")
            self.assertEqual(rows[2][-1], "方案2(空白归一化)")


if __name__ == "__main__":
    unittest.main()
