"""Generated Home bundles are exempt; hand-written application files are not."""

import tempfile
import unittest
from pathlib import Path

from scripts.check_architecture import check


class TestHomeGeneratedAssets(unittest.TestCase):
	def test_skips_only_the_exact_built_home_asset_paths(self):
		with tempfile.TemporaryDirectory() as directory:
			root = Path(directory)
			home = root / "tracecore" / "public" / "home"
			home.mkdir(parents=True)
			(home / "home.js").write_text('const label = "Trang chủ";', encoding="utf-8")
			(home / "home.css").write_text(":root{--tc-primary:#1F4E79}", encoding="utf-8")
			self.assertEqual(check(directory), [])

	def test_keeps_checks_for_other_files_in_the_home_directory(self):
		with tempfile.TemporaryDirectory() as directory:
			root = Path(directory)
			home = root / "tracecore" / "public" / "home"
			home.mkdir(parents=True)
			(home / "source.js").write_text('const label = "Trang chủ";', encoding="utf-8")
			(home / "source.css").write_text(".card{color:#1F4E79}", encoding="utf-8")
			self.assertEqual({violation.rule for violation in check(directory)}, {"R3", "R4"})

	def test_keeps_checks_for_same_filenames_outside_built_home_directory(self):
		with tempfile.TemporaryDirectory() as directory:
			root = Path(directory)
			source = root / "tracecore" / "public" / "js"
			source.mkdir(parents=True)
			(source / "home.js").write_text('const label = "Trang chủ";', encoding="utf-8")
			(source / "home.css").write_text(".card{color:#1F4E79}", encoding="utf-8")
			self.assertEqual({violation.rule for violation in check(directory)}, {"R3", "R4"})
