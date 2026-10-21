"""Kiểm tra chốt chặn của scripts/e2e_prepare.sh: từ chối site test.

Site test: tên test_site, hoặc allow_tests bật trong site_config.json hoặc sites/common_site_config.json.

Chạy script ở chế độ TC_E2E_CHECK_ONLY=1 với BENCH_DIR là thư mục tạm chứa site giả, nên không chạm site thật nào.
"""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "e2e_prepare.sh"


def run_guard(site, site_config=None, allow_override=False, common_config=None):
	with tempfile.TemporaryDirectory() as bench:
		if common_config is not None:
			Path(bench, "sites").mkdir(parents=True, exist_ok=True)
			Path(bench, "sites", "common_site_config.json").write_text(json.dumps(common_config))
		if site_config is not None:
			site_dir = Path(bench, "sites", site)
			site_dir.mkdir(parents=True, exist_ok=True)
			(site_dir / "site_config.json").write_text(json.dumps(site_config))
		env = {**os.environ, "BENCH_DIR": bench, "TC_E2E_CHECK_ONLY": "1", "TC_E2E_ENV": f"{bench}/e2e.env"}
		env.pop("TC_E2E_ALLOW_TEST_SITE", None)
		if allow_override:
			env["TC_E2E_ALLOW_TEST_SITE"] = "1"
		return subprocess.run(
			["bash", str(SCRIPT), site], env=env, capture_output=True, text=True, timeout=60
		)


class TestE2ePrepareGuard(unittest.TestCase):
	def test_refuses_site_named_test_site(self):
		result = run_guard("test_site")
		self.assertEqual(result.returncode, 2, result.stderr)
		self.assertIn("refuses", result.stderr)

	def test_refuses_site_with_allow_tests(self):
		for flag in (1, True, "1"):
			result = run_guard("fake.local", {"allow_tests": flag})
			self.assertEqual(result.returncode, 2, (flag, result.stderr))
			self.assertIn("allow_tests", result.stderr)

	def test_refuses_when_allow_tests_in_common_site_config(self):
		for flag in (1, True, "1"):
			result = run_guard("fake.local", {"developer_mode": 1}, common_config={"allow_tests": flag})
			self.assertEqual(result.returncode, 2, (flag, result.stderr))
			self.assertIn("common_site_config.json", result.stderr)
		self.assertEqual(run_guard("fake.local", common_config={"allow_tests": 1}).returncode, 2)
		self.assertEqual(run_guard("fake.local", {}, common_config={"allow_tests": 0}).returncode, 0)

	def test_accepts_dev_site(self):
		result = run_guard("fake.local", {"developer_mode": 1, "allow_tests": 0})
		self.assertEqual(result.returncode, 0, result.stderr)
		self.assertEqual(run_guard("fake.local", {"developer_mode": 1}).returncode, 0)

	def test_ci_override_allows_test_site(self):
		self.assertEqual(run_guard("test_site", {"allow_tests": 1}, allow_override=True).returncode, 0)
		self.assertEqual(
			run_guard("fake.local", {}, allow_override=True, common_config={"allow_tests": 1}).returncode, 0
		)
