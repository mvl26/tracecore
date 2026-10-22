"""Kiểm tra chốt chặn của scripts/e2e_prepare.sh: từ chối site test.

Site test: tên test_site, hoặc allow_tests bật trong site_config.json hoặc sites/common_site_config.json.

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
	def test_preparation_exports_both_cards_without_disclosing_credentials(self):
		with tempfile.TemporaryDirectory() as bench:
			bin_dir = Path(bench, "bin")
			bin_dir.mkdir()
			fake_bench = bin_dir / "bench"
			fake_bench.write_text("""#!/usr/bin/env python3
import ast, json, os, sys
if "execute" not in sys.argv:
    sys.exit(0)
method = sys.argv[sys.argv.index("execute") + 1]
kwargs = ast.literal_eval(sys.argv[sys.argv.index("--kwargs") + 1]) if "--kwargs" in sys.argv else {}
if method == "frappe.is_setup_complete":
    print("true")
elif method.endswith("ensure_e2e_users"):
    print(json.dumps({"user": "station-tr-003@tracecore.local", "t4_user": "station-tr-004@tracecore.local", "r10_user": "r10-e2e@tracecore.local", "otp_secret": os.environ["TC_FAKE_OTP"], "t4_otp_secret": os.environ["TC_FAKE_OTP"], "r10_otp_secret": os.environ["TC_FAKE_OTP"]}))
elif method.endswith("ensure_desk_users"):
    print(json.dumps({"codes_user": "r10-codes-e2e@tracecore.local", "codes_otp_secret": os.environ["TC_FAKE_OTP"], "instr_user": "r02-instr-e2e@tracecore.local", "instr_otp_secret": os.environ["TC_FAKE_OTP"], "inv_user": "r09-inv-e2e@tracecore.local", "inv_otp_secret": os.environ["TC_FAKE_OTP"]}))
elif method.endswith("ensure_t2_e2e_user"):
    print(json.dumps({"t2_user": "station-tr-002@tracecore.local", "t2_otp_secret": os.environ["TC_FAKE_OTP"]}))
elif method.endswith("ensure_t2_demo"):
    print(json.dumps({"machine": "TB-0001", "sets": ["S-1", "S-2", "S-3"]}))
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
			# FEAT-021: user kiosk T2 có thẻ, OTP riêng và mã demo T2 (danh sách bộ nối bằng dấu phẩy)
			self.assertEqual(values["TC_E2E_T2_CARD_ID"], "CARD-TR-002")
			self.assertEqual(values["TC_E2E_T2_OTP_SECRET"], env["TC_FAKE_OTP"])
			self.assertEqual(values["TC_E2E_T2_STATION"], "TR-002")
			self.assertEqual(values["TC_E2E_T2_SETS"], "S-1,S-2,S-3")
			for key in ("CODES", "INSTR", "INV"):
				self.assertEqual(values[f"TC_E2E_{key}_OTP_SECRET"], env["TC_FAKE_OTP"])
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

	def test_sets_local_printer_flag_after_guard_before_codes_demo(self):
		# server chỉ gửi tới máy in mạng demo ở 127.0.0.1 khi site bật cờ (print_server.printer_address, lúc gửi)
		script = SCRIPT.read_text()
		flag = script.index("set-config tracecore_allow_local_printers 1")
		self.assertGreater(flag, script.index('refuse_test_site "$SITE" || exit 2'))
		self.assertLess(flag, script.index("tracecore.setup.devdata.ensure_codes_demo --kwargs"))
