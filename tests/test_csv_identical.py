import unittest
from pathlib import Path


class TestCsvDirsIdentical(unittest.TestCase):
    def test_csv_dirs_identical(self):
        here = Path(__file__).resolve().parent
        project_root = here.parent

        test_files = project_root / "data" / "verb-csvs" / "spanish"
        golden_files = here / "golden-files" / "spanish"

        # Guard against false greens
        self.assertTrue(test_files.is_dir(), f"Missing test_files dir: {test_files}")
        self.assertTrue(golden_files.is_dir(), f"Missing golden_files dir: {golden_files}")

        files1 = sorted(p.name for p in test_files.glob("*.csv"))
        files2 = sorted(p.name for p in golden_files.glob("*.csv"))
        self.assertEqual(files1, files2, "CSV filenames differ")

        for name in files1:
            c1 = (test_files / name).read_text(encoding="utf-8")
            c2 = (golden_files / name).read_text(encoding="utf-8")
            self.assertEqual(c1, c2, f"CSV content differs in {name}")


if __name__ == "__main__":
    unittest.main()
