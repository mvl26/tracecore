"""RPC tracecore.v1.assembly.* (FEAT-020 Task 4): phiên thẻ, quyền, mã HTTP theo loại lỗi, replay idempotent."""

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import frappe

from tracecore.core import station_auth, step_gate
from tracecore.reprocessing import packing
from tracecore.tests.factories import make_cycle, make_set_type, make_set_unit, make_user
from tracecore.tests.utils import IsolatedTestCase, bru, request_headers
from tracecore.v1 import assembly as assembly_api
from tracecore.v1._common import BadRequestError
from tracecore.v1.tests.station_fixtures import make_station_session

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

STATION = "TR-003"
T4_STATION = "TR-004"
BOM = [("API-KEO", 2), ("API-KEP", 1)]
PIN = "135790"
TIME_ZONE = ZoneInfo("Asia/Ho_Chi_Minh")
TOKENS = {}


def now_ts():
	return datetime.now(TIME_ZONE).isoformat(timespec="seconds")


def call(fn, key=None, station_header=STATION, **kwargs):
	frappe.local.response.pop("http_status_code", None)
	kwargs.setdefault("client_ts", now_ts())
	kwargs.setdefault("token", TOKENS.get((frappe.session.user, kwargs.get("station"))))
	with request_headers({"X-Idempotency-Key": key or str(uuid.uuid4()), "X-TC-Station": station_header}):
		return fn(**kwargs)


def http_status():
	return frappe.local.response.get("http_status_code")


def counts():
	return tuple(frappe.db.count(d) for d in ("Audit Log", "Idempotency Key", "Assembly Record"))


class AssemblyApiCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		TOKENS.clear()
		self.addCleanup(TOKENS.clear)
		self.addCleanup(frappe.local.response.pop, "http_status_code", None)
		self.login("Administrator", STATION)
		unit = make_set_unit(make_set_type("APIA", bom=BOM).name)
		make_cycle(unit, passed=("T1", "T2"))
		self.set_id = unit.name

	def login(self, user, station):
		TOKENS[(user, station)] = make_station_session(user, station=station)["token"]
		return TOKENS[(user, station)]

	def as_user(self, email, roles, station=STATION):
		frappe.set_user("Administrator")
		user = make_user(email, roles=roles)
		self.login(user, station)
		frappe.set_user(user)
		self.addCleanup(frappe.set_user, "Administrator")
		return user

	def open(self, station=STATION, **kwargs):
		return call(assembly_api.open, raw=kwargs.pop("raw", self.set_id), station=station, **kwargs)

	def count(self, name, **short):
		for code, qty in BOM:
			result = call(
				assembly_api.line, assembly=name, instrument=code, actual_qty=short.get(code, qty), station=STATION
			)
			self.assertIs(result["ok"], True, msg=result)

	def assert_rejection(self, result, code, status):
		self.assertIs(result["ok"], False, msg=result)
		self.assertEqual(result["error"]["code"], code)
		self.assertEqual(http_status(), status)
		for key in ("title", "reason", "action"):
			self.assertTrue(result["error"][key], msg=key)


class TestAssemblyFlow(AssemblyApiCase):
	@bru("BRU-FLOW-004")
	def test_open_count_submit_records_t3_and_unlocks_t4(self):
		opened = self.open()
		self.assertIs(opened["ok"], True)
		self.assertEqual(opened["set"]["set_id"], self.set_id)
		name = opened["assembly"]
		self.count(name)
		done = call(assembly_api.submit, assembly=name, notes="Đủ", station=STATION)
		self.assertEqual((done["ok"], done["result"], done["pack_locked"]), (True, "Pass", False))
		self.assertEqual(done["next_station"], T4_STATION)
		self.assertEqual(step_gate.gates(self.set_id)[2]["result"], "Pass")
		self.assertEqual(packing.get_context(self.set_id, T4_STATION)["gates"][2]["result"], "Pass")

	@bru("BRU-REP-003")
	def test_shortage_locks_t4_until_r02_confirms_with_pin(self):
		name = self.open()["assembly"]
		self.count(name, **{"API-KEO": 0})
		locked = call(assembly_api.submit, assembly=name, station=STATION)
		self.assert_rejection(locked, "SHORTAGE_UNCONFIRMED", 409)
		self.assertEqual([i["instrument"] for i in locked["error"]["items"]], ["API-KEO"])
		self.assertEqual(frappe.db.get_value("Assembly Record", name, "docstatus"), 0)
		self.assertEqual(
			call(assembly_api.line, assembly=name, instrument="API-KEO", actual_qty=0, station=STATION)["pack_lock_reason"],
			"SHORTAGE_UNCONFIRMED",
		)
		with self.assertRaises(Exception) as caught:
			packing.get_context(self.set_id, T4_STATION)
		self.assertEqual(caught.exception.block.code, "GATE_PREV_NOT_PASSED")
		# R04 không xác nhận được
		self.as_user("api-t3-r04@test.local", ("TC R04",))
		with self.assertRaises(frappe.PermissionError):
			call(assembly_api.confirm_shortage, assembly=name, reason="Gấp", station=STATION)
		# R02 đăng nhập thẻ tại trạm, nhập PIN rồi xác nhận
		user = self.as_user("api-t3-r02@test.local", ("TC R02",))
		employee = frappe.db.get_value("Employee", {"user_id": user}, "name")
		station_auth.set_pin(employee, PIN)
		self.addCleanup(station_auth.clear_pin_rate_limit, employee)
		missing = call(assembly_api.confirm_shortage, assembly=name, reason="Ca mổ gấp", station=STATION)
		self.assert_rejection(missing, "R02_CONFIRM_REQUIRED", 409)
		proof = station_auth.create_pin_proof(TOKENS[(user, STATION)], PIN)["proof"]
		confirmed = call(
			assembly_api.confirm_shortage,
			assembly=name,
			reason="Ca mổ gấp",
			reviewer_proof=proof,
			station=STATION,
		)
		self.assertEqual((confirmed["ok"], confirmed["shortage_confirmed_by"]), (True, user))
		done = call(assembly_api.submit, assembly=name, station=STATION)
		self.assertEqual((done["ok"], done["result"]), (True, "Pass"))
		self.assertTrue(packing.get_context(self.set_id, T4_STATION))

	def test_branch_via_rpc_fails_t3(self):
		name = self.open()["assembly"]
		done = call(
			assembly_api.submit,
			assembly=name,
			branch="Repair",
			branch_reason="Gãy kẹp",
			station=STATION,
		)
		self.assertEqual((done["ok"], done["result"], done["branch"], done["next_station"]), (True, "Fail", "Repair", None))
		self.assertEqual(frappe.db.get_value("Set Unit", self.set_id, "status"), "Reprocess")

	def test_replay_same_key_returns_same_result_without_duplicates(self):
		key, ts = str(uuid.uuid4()), now_ts()
		first = self.open(key=key, client_ts=ts)
		second = self.open(key=key, client_ts=ts)
		self.assertEqual(first, second)
		self.assertEqual(frappe.db.count("Assembly Record", {"set_unit": self.set_id}), 1)
		name = first["assembly"]
		self.count(name)
		key, ts = str(uuid.uuid4()), now_ts()
		one = call(assembly_api.submit, key=key, client_ts=ts, assembly=name, station=STATION)
		two = call(assembly_api.submit, key=key, client_ts=ts, assembly=name, station=STATION)
		self.assertEqual(one, two)
		self.assertEqual(step_gate.gates(self.set_id)[2], {"step": "T3", "result": "Pass", "redo_count": 0})

	def test_all_ok_and_scan_arguments_are_accepted(self):
		name = self.open()["assembly"]
		ctx = call(assembly_api.line, assembly=name, all_ok="1", station=STATION)
		self.assertTrue(all(line["counted"] for line in ctx["lines"]))
		ctx = call(
			assembly_api.line,
			assembly=name,
			instrument="API-KEO",
			actual_qty="1",
			damaged_qty="1",
			replaced_qty="1",
			disposition="Repair",
			station=STATION,
		)
		self.assertEqual(ctx["lines"][0]["actual_qty"], 1)


class TestAssemblyRejections(AssemblyApiCase):
	def test_rejections_carry_http_status_audit_and_idempotency_key(self):
		before = counts()
		rejected = self.open(raw="XYZ-123")
		self.assert_rejection(rejected, "SCAN_INVALID", 422)
		after = counts()
		self.assertEqual(after[0], before[0] + 1)  # Audit Log Reject
		self.assertEqual(after[1], before[1] + 1)  # Idempotency Key
		self.assertTrue(frappe.db.exists("Audit Log", {"action": "Reject", "reason": "SCAN_INVALID"}))

	@bru("BRU-FLOW-002")
	def test_wrong_station_gate_and_unknown_assembly(self):
		self.login("Administrator", T4_STATION)
		self.assert_rejection(self.open(station=T4_STATION), "STATION_WRONG_STEP", 422)
		self.login("Administrator", STATION)  # một thẻ – một phiên: đăng nhập T4 đã đóng phiên T3
		other = make_set_unit(make_set_type("APIB", bom=BOM).name)
		make_cycle(other, passed=("T1",))
		self.assert_rejection(self.open(raw=other.name), "GATE_PREV_NOT_PASSED", 409)
		missing = call(assembly_api.line, assembly="AS-2026-99999", instrument="API-KEO", actual_qty=1, station=STATION)
		self.assert_rejection(missing, "ASSEMBLY_NOT_FOUND", 404)

	def test_business_codes_map_to_http_statuses(self):
		name = self.open()["assembly"]
		bad = call(assembly_api.line, assembly=name, instrument="API-KEO", actual_qty=-1, station=STATION)
		self.assert_rejection(bad, "QTY_INVALID", 422)
		partial = call(assembly_api.submit, assembly=name, station=STATION)
		self.assert_rejection(partial, "LINES_NOT_COUNTED", 422)
		nothing = call(assembly_api.confirm_shortage, assembly=name, reason="x", station=STATION)
		self.assert_rejection(nothing, "NO_SHORTAGE", 409)
		branch = call(assembly_api.submit, assembly=name, branch="Burn", branch_reason="x", station=STATION)
		self.assert_rejection(branch, "BRANCH_INVALID", 422)
		self.count(name)
		call(assembly_api.submit, assembly=name, station=STATION)
		closed = call(assembly_api.line, assembly=name, instrument="API-KEO", actual_qty=1, station=STATION)
		self.assert_rejection(closed, "ASSEMBLY_CLOSED", 409)

	def test_malformed_arguments_are_400(self):
		name = self.open()["assembly"]
		for fn, kwargs in (
			(assembly_api.open, {"raw": 5}),
			(assembly_api.line, {"assembly": 5, "instrument": "API-KEO"}),
			(assembly_api.line, {"assembly": name, "instrument": 5}),
			(assembly_api.submit, {"assembly": name, "notes": 5}),
			(assembly_api.confirm_shortage, {"assembly": name, "reason": 5}),
		):
			with self.assertRaises(BadRequestError, msg=str(kwargs)):
				call(fn, station=STATION, **kwargs)

	def test_station_role_and_session_are_required(self):
		self.as_user("api-t3-r03@test.local", ("TC R03",))
		with self.assertRaises(frappe.PermissionError):
			self.open()
		frappe.set_user("Administrator")
		TOKENS.clear()
		result = call(assembly_api.open, raw=self.set_id, station=STATION)
		self.assertEqual(result["error"]["code"], "SESSION_INVALID")
