"""Kiểm tra chốt chặn của scripts/e2e_prepare.sh: từ chối site test (tên test_site hoặc allow_tests bật).

Chạy script ở chế độ TC_E2E_CHECK_ONLY=1 với BENCH_DIR là thư mục tạm chứa site giả, nên không chạm site thật nào.
"""

import base64
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "e2e_prepare.sh"


def run_guard(site, site_config=None, allow_override=False):
	with tempfile.TemporaryDirectory() as bench:
		if site_config is not None:
			site_dir = Path(bench, "sites", site)
			site_dir.mkdir(parents=True)
			(site_dir / "site_config.json").write_text(json.dumps(site_config))
		env = {**os.environ, "BENCH_DIR": bench, "TC_E2E_CHECK_ONLY": "1", "TC_E2E_ENV": f"{bench}/e2e.env"}
		env.pop("TC_E2E_ALLOW_TEST_SITE", None)
		if allow_override:
			env["TC_E2E_ALLOW_TEST_SITE"] = "1"
		return subprocess.run(
			["bash", str(SCRIPT), site], env=env, capture_output=True, text=True, timeout=60
		)


class TestE2ePrepareGuard(unittest.TestCase):
	def test_preparation_exports_both_cards_without_disclosing_credentials(self):
		with tempfile.TemporaryDirectory() as bench:
			bin_dir = Path(bench, "bin")
			bin_dir.mkdir()
			fake_bench = bin_dir / "bench"
			fake_bench.write_text("""#!/usr/bin/env python3
import ast, json, os, sys
method = sys.argv[sys.argv.index("execute") + 1]
kwargs = ast.literal_eval(sys.argv[sys.argv.index("--kwargs") + 1]) if "--kwargs" in sys.argv else {}
if method == "frappe.is_setup_complete":
    print("true")
elif method.endswith("ensure_e2e_users"):
    print(json.dumps({"user": "station-tr-003@tracecore.local", "t4_user": "station-tr-004@tracecore.local", "r10_user": "r10-e2e@tracecore.local", "otp_secret": os.environ["TC_FAKE_OTP"], "t4_otp_secret": os.environ["TC_FAKE_OTP"], "r10_otp_secret": os.environ["TC_FAKE_OTP"]}))
elif method.endswith("station_user"):
    print(json.dumps("station-" + kwargs["station"].lower() + "@tracecore.local"))
elif method.endswith("desk_user"):
    print(json.dumps("r10-e2e@tracecore.local"))
elif method.endswith("ensure_station_demo"):
    print(json.dumps({"employee": "DEMO-" + kwargs["station"], "card_id": "CARD-" + kwargs["station"]}))
elif method.endswith("ensure_demo_set"):
    print(json.dumps("9520000DEMO000001"))
else:
    print("{}")
""")
			fake_bench.chmod(0o700)
			env_file = Path(bench, "e2e.env")
			env = {
				**os.environ,
				"BENCH_DIR": bench,
				"TC_E2E_ENV": str(env_file),
				"PATH": f"{bin_dir}:{os.environ['PATH']}",
				"TC_FAKE_OTP": base64.b32encode(os.urandom(20)).decode(),
			}
			for key in ("TC_E2E_CHECK_ONLY", "TC_E2E_ALLOW_TEST_SITE"):
				env.pop(key, None)
			result = subprocess.run(
				["bash", str(SCRIPT), "fake.local"], env=env, capture_output=True, text=True, timeout=60
			)
			self.assertEqual(result.returncode, 0, result.stderr)
			values = dict(line.split("=", 1) for line in env_file.read_text().splitlines())
			self.assertEqual(values["TC_E2E_CARD_ID"], "CARD-TR-003")
			self.assertEqual(values["TC_E2E_T4_CARD_ID"], "CARD-TR-004")
			self.assertEqual(values["TC_E2E_T4_SECOND_STATION"], "TR-005")
			self.assertEqual(values["TC_E2E_OTP_SECRET"], env["TC_FAKE_OTP"])
			self.assertEqual(values["TC_E2E_T4_OTP_SECRET"], env["TC_FAKE_OTP"])
			self.assertEqual(values["TC_E2E_R10_OTP_SECRET"], env["TC_FAKE_OTP"])
			self.assertNotIn(env["TC_FAKE_OTP"], result.stdout + result.stderr)
			self.assertNotEqual(values["TC_E2E_PASSWORD"], values["TC_E2E_R10_PASSWORD"])
			self.assertNotIn(values["TC_E2E_PASSWORD"], result.stdout + result.stderr)
			self.assertEqual(env_file.stat().st_mode & 0o777, 0o600)
			result = subprocess.run(
				["bash", str(SCRIPT), "fake.local"], env=env, capture_output=True, text=True, timeout=60
			)
			self.assertEqual(result.returncode, 0, result.stderr)
			self.assertEqual(
				env_file.read_text().splitlines(), [f"{key}={value}" for key, value in values.items()]
			)

	def test_refuses_site_named_test_site(self):
		result = run_guard("test_site")
		self.assertEqual(result.returncode, 2, result.stderr)
		self.assertIn("refuses", result.stderr)

	def test_refuses_site_with_allow_tests(self):
		for flag in (1, True, "1"):
			result = run_guard("fake.local", {"allow_tests": flag})
			self.assertEqual(result.returncode, 2, (flag, result.stderr))
			self.assertIn("allow_tests", result.stderr)

	def test_accepts_dev_site(self):
		result = run_guard("fake.local", {"developer_mode": 1, "allow_tests": 0})
		self.assertEqual(result.returncode, 0, result.stderr)
		self.assertEqual(run_guard("fake.local", {"developer_mode": 1}).returncode, 0)

	def test_ci_override_allows_test_site(self):
		self.assertEqual(run_guard("test_site", {"allow_tests": 1}, allow_override=True).returncode, 0)
