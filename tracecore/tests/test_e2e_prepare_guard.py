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
    result = {}
    for spec in kwargs["specs"]:
        result[spec["key"] + "_user"] = spec["name"] + "@tracecore.local"
        result[spec["key"] + "_otp_secret"] = os.environ["TC_FAKE_OTP"]
    print(json.dumps(result))
elif method == "tracecore.setup.provision.desk_user":
    # provision.desk_user gọi trực tiếp (không có R10 tạm) bị guard FEAT-003 từ chối trên site thật
    print("frappe.exceptions.PermissionError: Only R10 can create or disable accounts.", file=sys.stderr)
    sys.exit(1)
elif method.endswith("ensure_t2_e2e_user"):
    print(json.dumps({"t2_user": "station-tr-002@tracecore.local", "t2_otp_secret": os.environ["TC_FAKE_OTP"]}))
elif method.endswith("ensure_t2_demo"):
    print(json.dumps({"machine": "TB-0001", "sets": ["S-1", "S-2", "S-3"]}))
elif method.endswith("ensure_t3_e2e_users"):
    print(json.dumps({"t3_user": "station-t3@tracecore.local", "t3_r02_user": "r02-t3-e2e@tracecore.local", "t3_otp_secret": os.environ["TC_FAKE_OTP"]}))
elif method.endswith("ensure_t3_r02"):
    print(json.dumps({"employee": "DEMO-R02", "card_id": "CARD-R02-" + kwargs["station"], "pin": "135790"}))
elif method.endswith("ensure_t3_demo"):
    print(json.dumps({"set_full": "S-F", "set_short": "S-S", "set_branch": "S-B", "set_no_wash": "S-N", "short_instrument": "KC-1"}))
elif method.endswith("ensure_t6_e2e_user"):
    print(json.dumps({"t6_user": "station-t6@tracecore.local", "t6_otp_secret": os.environ["TC_FAKE_OTP"]}))
elif method.endswith("ensure_t6_demo"):
    print(json.dumps({"location": "KE-0001", "pack_released": "CY-261022-0001"}))
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
			self.assertEqual(values["TC_E2E_STATION"], "TR-090")  # trạm tra cứu chung, không phải trạm T3
			self.assertEqual(values["TC_E2E_CARD_ID"], "CARD-TR-090")
			self.assertEqual(values["TC_E2E_T4_CARD_ID"], "CARD-TR-004")
			self.assertEqual(values["TC_E2E_T3_STATION"], "TR-003")
			self.assertEqual(values["TC_E2E_T3_CARD_ID"], "CARD-TR-003")
			self.assertEqual(values["TC_E2E_T3_R02_CARD_ID"], "CARD-R02-TR-003")
			self.assertEqual(values["TC_E2E_T3_R02_PIN"], "135790")
			self.assertEqual(values["TC_E2E_T3_OTP_SECRET"], env["TC_FAKE_OTP"])
			self.assertEqual(values["TC_E2E_T3_SET_SHORT"], "S-S")
			self.assertEqual(values["TC_E2E_T4_SECOND_STATION"], "TR-005")
			self.assertEqual(values["TC_E2E_OTP_SECRET"], env["TC_FAKE_OTP"])
			self.assertEqual(values["TC_E2E_T4_OTP_SECRET"], env["TC_FAKE_OTP"])
			self.assertEqual(values["TC_E2E_R10_OTP_SECRET"], env["TC_FAKE_OTP"])
