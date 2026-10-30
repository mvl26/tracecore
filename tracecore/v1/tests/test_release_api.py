"""RPC tracecore.v1.release.* (FEAT-023): dỡ mẻ, chỉ thị, giải phóng PIN R02, Không đạt, BI; mã HTTP, quyền, idempotent."""

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import frappe
from frappe.utils import add_to_date, now_datetime, today

from tracecore.core import client_time, station_auth
from tracecore.reprocessing import sterilizing
from tracecore.tests.factories import (
	make_employee,
	make_load,
	make_load_ready_pack,
	make_sterilize_program,
	make_sterilizer,
	make_user,
)
from tracecore.tests.utils import IsolatedTestCase, bru, request_headers
from tracecore.v1 import release as release_api
from tracecore.v1.tests.station_fixtures import make_station_session

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

STATION = "TR-005"
TIME_ZONE = ZoneInfo("Asia/Ho_Chi_Minh")
SESSION_TOKENS = {}
PARAMETERS = [
	{"parameter_name": "Temperature", "unit": "°C", "min_value": 132, "max_value": 138, "required": 1},
]


def now_ts():
	return datetime.now(TIME_ZONE).isoformat(timespec="seconds")


def call(fn, key=None, **kwargs):
	frappe.local.response.pop("http_status_code", None)
	kwargs.setdefault("client_ts", now_ts())
	kwargs.setdefault("token", SESSION_TOKENS.get(frappe.session.user))
	with request_headers({"X-Idempotency-Key": key or str(uuid.uuid4()), "X-TC-Station": STATION}):
		return fn(**kwargs)


class ReleaseApiCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		SESSION_TOKENS.clear()
		self.addCleanup(SESSION_TOKENS.clear)
		self.addCleanup(frappe.local.response.pop, "http_status_code", None)
		frappe.set_user("Administrator")
		self.machine = make_sterilizer()
		self.other_machine = make_sterilizer()
		self.program = make_sterilize_program(self.machine.name, parameters=PARAMETERS)
		self.employee = make_employee()
		self.pack = make_load_ready_pack()
		self.load = make_load(self.machine, self.program, [self.pack], operator=self.employee.name)
		sterilizing.save_manual_data(
			load=self.load.name,
			equipment_raw=self.machine.name,
			load_raw=self.load.name,
			values=[{"parameter_name": "Temperature", "value": "134"}],
			started_at=str(add_to_date(now_datetime(), hours=-1)),
			ended_at=str(now_datetime()),
			machine_alerts=None,
			machine_report="/files/p.png",
			reason=None,
			confirmed=True,
			card=self.employee.tc_card_id,
			client_ts=client_time.utc_now(),
			employee=self.employee.name,
			station=STATION,
		)
		self.technician = self.as_user("ky-thuat@example.com", ["TC R05"])

	def as_user(self, email, roles):
		frappe.set_user("Administrator")
		user = make_user(email, roles=roles)
		SESSION_TOKENS[user] = make_station_session(user, STATION)["token"]
		frappe.set_user(user)
		self.addCleanup(frappe.set_user, "Administrator")
		return user

	def scans(self):
		return {
			"load": self.load.name,
			"equipment_raw": self.machine.name,
			"load_raw": self.load.name,
			"station": STATION,
		}

	def pin_proof(self, user, pin="246810"):
		employee = frappe.db.get_value("Employee", {"user_id": user}, "name")
		frappe.db.set_value("Employee", employee, "tc_pin_reset_required", 0)
		station_auth.set_pin(employee, pin)
		return station_auth.create_pin_proof(SESSION_TOKENS[user], pin)["proof"]


class TestReleaseApi(ReleaseApiCase):
	@bru("BRU-REP-005", "BRU-FLOW-004")
	def test_full_flow_unload_indicators_release(self):
		self.assertTrue(call(release_api.context, **self.scans())["ok"])
		self.assertTrue(call(release_api.cycle_result, result="Pass", confirmed=1, **self.scans())["ok"])
		self.assertTrue(
			call(release_api.indicator, indicator="chemical_class_5", result="Pass", **self.scans())["ok"]
		)
		self.assertTrue(
			call(
				release_api.indicator,
				indicator="bowie_dick",
				result="Pass",
				test_date=today(),
				**self.scans(),
			)["ok"]
		)
		# người dỡ (R05) không giải phóng được; R02 đăng nhập cùng trạm và nhập PIN
		blocked = call(release_api.release, **self.scans())
		self.assertEqual(blocked["error"]["code"], "R02_CONFIRM_REQUIRED")
		self.assertEqual(frappe.local.response.get("http_status_code"), blocked["error"]["http_status"])
		r02 = self.as_user("giam-sat@example.com", ["TC R02"])
		self.assertEqual(frappe.session.user, r02)
		key = str(uuid.uuid4())
		stamp = now_ts()
		proof = self.pin_proof(r02)
		done = call(release_api.release, key, pin_proof=proof, client_ts=stamp, **self.scans())
		self.assertEqual((done["ok"], done["status"]), (True, "Released"))
		replay = call(release_api.release, key, pin_proof=proof, client_ts=stamp, **self.scans())
		self.assertEqual(replay["status"], "Released")
		self.assertEqual(frappe.db.get_value("Set Unit", self.pack.set_unit, "cycles_used"), 1)  # đếm một lần

	def test_roles_and_wrong_station(self):
		other = self.as_user("kho@example.com", ["TC R06"])
		with self.assertRaises(frappe.PermissionError):
			call(release_api.context, **self.scans())
		frappe.set_user(self.technician)
		wrong = call(release_api.context, **{**self.scans(), "station": "TR-001"})
		self.assertFalse(wrong["ok"])
		self.assertEqual(wrong["error"]["code"], "SESSION_STATION_MISMATCH")
		self.assertTrue(other)

	@bru("BRU-REP-016")
	def test_other_machine_qr_is_rejected(self):
		result = call(release_api.context, **{**self.scans(), "equipment_raw": self.other_machine.name})
		self.assertEqual(result["error"]["code"], "EQUIPMENT_MISMATCH")

	@bru("BRU-REP-007")
	def test_reject_sends_the_sets_back(self):
		call(release_api.cycle_result, result="Fail", confirmed=1, **self.scans())
		done = call(release_api.reject, reason="Chu trình lỗi", redo_from="T2", **self.scans())
		self.assertEqual(done["status"], "Failed")
		self.assertEqual(frappe.db.get_value("Pack", self.pack.name, "status"), "Void")
		bad = call(release_api.reject, redo_from="T9", **self.scans())
		self.assertFalse(bad["ok"])

	def test_bi_without_waiting_indicator(self):
		result = call(release_api.bi_result, load=self.load.name, result="Pass", station=STATION)
		self.assertEqual(result["error"]["code"], "BI_NOT_PENDING")
		self.assertEqual(frappe.local.response.get("http_status_code"), 409)
