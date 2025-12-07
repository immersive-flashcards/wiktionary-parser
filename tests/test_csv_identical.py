import shutil
import unittest
from pathlib import Path

import yaml

from src.wiktionary_to_csv import main as run_with_config

ROOT_DIR = Path(__file__).parent.parent
TEST_DIR = Path(__file__).parent
TEST_CONFIG_PATH = ROOT_DIR / "config/runs" / "test.yml"


def load_test_config() -> dict:
    with TEST_CONFIG_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


class TestGoldenFiles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_test_config()
        cls.output_dir = (ROOT_DIR / cls.config["output_dir"]).resolve()

    def setUp(self):
        self.output_dir = type(self).output_dir

        # Register cleanup first so it always runs, even if setUp or the test fails
        self.addCleanup(self._cleanup_output_dir)

        # Start with a clean directory
        self._cleanup_output_dir()
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _cleanup_output_dir(self):
        if self.output_dir.exists():
            shutil.rmtree(self.output_dir, ignore_errors=True)

    def test_generated_csvs_match_golden_files(self):
        run_with_config("test")  # Run the generator using the test config

        golden_dir = TEST_DIR / "golden-files" / "spanish"
        generated_dir = self.output_dir / "spanish"

        golden_files = sorted(f for f in golden_dir.glob("*.csv") if f.is_file())
        generated_files = sorted(f for f in generated_dir.glob("*.csv") if f.is_file())

        self.assertEqual(
            [f.name for f in golden_files],
            [f.name for f in generated_files],
            "Generated CSV set does not match golden file set",
        )

        for golden, generated in zip(golden_files, generated_files):
            with golden.open("r", encoding="utf-8") as fg, generated.open("r", encoding="utf-8") as ft:
                golden_content = fg.read()
                generated_content = ft.read()
            self.assertEqual(
                golden_content,
                generated_content,
                f"File differs from golden file: {generated.name}",
            )
