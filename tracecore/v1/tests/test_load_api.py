"""RPC tracecore.v1.load.* (FEAT-022 Task 5): phiên trạm thẻ, quyền, mã HTTP theo loại lỗi, replay idempotent."""

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import frappe
from frappe.utils import add_to_date, now_datetime

from tracecore.tests.factories import (
	deactivate_printers,
	make_load,
	make_load_ready_pack,
	make_sterilize_program,
	make_sterilizer,
	make_user,
)
from tracecore.tests.utils import IsolatedTestCase, bru, request_headers
from tracecore.v1 import load as load_api
from tracecore.v1._common import BadRequestError
from tracecore.v1.tests.station_fixtures import make_station_session

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

STATION = "TR-005"
OTHER_STATION = "TR-004"
TIME_ZONE = ZoneInfo("Asia/Ho_Chi_Minh")
PARAMETERS = [
	{"parameter_name": "Temperature", "unit": "°C", "min_value": 132, "max_value": 138, "required": 1}
]
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
	return tuple(frappe.db.count(d) for d in ("Audit Log", "Idempotency Key", "Sterilization Load"))


class LoadApiCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		TOKENS.clear()
		self.addCleanup(TOKENS.clear)
		self.login("Administrator", STATION)
		self.addCleanup(frappe.local.response.pop, "http_status_code", None)
		deactivate_printers(STATION)
		self.machine = make_sterilizer(has_printout=1)
		self.program = make_sterilize_program(self.machine.name, parameters=PARAMETERS)

	def login(self, user, station):
		TOKENS[(user, station)] = make_station_session(user, station=station)["token"]
		return TOKENS[(user, station)]

	def as_user(self, email, roles, station=STATION):
		user = make_user(email, roles=roles)
		self.login(user, station)
		frappe.set_user(user)
		self.addCleanup(frappe.set_user, "Administrator")
		return user

	def complete(self, packs, key=None, program=None, machine=None, station=STATION, **kwargs):
		return call(
			load_api.complete,
			key=key,
			equipment=(machine or self.machine).name,
			program=(program or self.program).name,
			packs=packs,
			station=station,
			**kwargs,
		)

	def data_args(self, load, machine=None, station=STATION):
		return {
			"load": load,
			"equipment_raw": (machine or self.machine).name,
			"load_raw": load,
			"station": station,
		}

	def card_of(self, user="Administrator"):
		return frappe.db.get_value("Employee", {"user_id": user}, "tc_card_id")

	def manual_data(self, load, machine=None, station=STATION, user="Administrator", **overrides):
		key = overrides.pop("key", None)
		args = {
			"values": [{"parameter_name": "Temperature", "value": "134"}],
			"started_at": str(add_to_date(now_datetime(), hours=-1)),
			"ended_at": str(now_datetime()),
			"confirmed": 1,
			"card": self.card_of(user),
			"machine_report": "/files/printout.png",
			**overrides,
		}
		return call(load_api.manual_data, key=key, **args, **self.data_args(load, machine, station))

	def assert_rejection(self, result, code, status):
		self.assertIs(result["ok"], False, msg=result)
		self.assertEqual(result["error"]["code"], code)
		self.assertEqual(http_status(), status)
		for key in ("title", "reason", "action"):
			self.assertTrue(result["error"][key], msg=key)


class TestLoadApi(LoadApiCase):
	@bru("BRU-REP-016")
	def test_create_then_add_pack_then_complete_happy_path(self):
		started = call(load_api.create, raw=f"]Q1{self.machine.name}\r\n", station=STATION)
		self.assertIs(started["ok"], True)
		self.assertEqual(started["equipment"]["name"], self.machine.name)
		self.assertEqual([p["program_code"] for p in started["programs"]], [self.program.name])

		pack = make_load_ready_pack()
		args = {"equipment": self.machine.name, "program": self.program.name, "station": STATION}
		added = call(load_api.add_pack, raw=pack.name, queued="[]", **args)
		self.assertIs(added["ok"], True)
		self.assertEqual(
			(added["cycle_id"], added["set_id"], added["duplicate"]), (pack.name, pack.set_unit, False)
		)
		again = call(load_api.add_pack, raw=pack.name, queued=[pack.name], **args)
		self.assertIs(again["duplicate"], True)

		done = self.complete([pack.name])
		self.assertIs(done["ok"], True)
		self.assertRegex(done["load"], r"^ME-\d{6}-\d{2}$")
		self.assertEqual((done["packs"], done["rejected"]), ([pack.name], []))
		self.assertEqual(done["print"]["status"], "Waiting")
		employee = frappe.db.get_value("Employee", {"user_id": "Administrator"}, "name")
		self.assertEqual(frappe.db.get_value("Sterilization Load", done["load"], "operator"), employee)
		self.assertEqual(frappe.db.get_value("Pack", pack.name, "status"), "In Load")

	@bru("BRU-REP-004")
	def test_add_pack_incompatible_writes_audit_and_422(self):
		plasma_pack = make_load_ready_pack(method="Plasma")
		before = frappe.db.count("Audit Log", {"action": "Reject"})
		result = call(
			load_api.add_pack,
			raw=plasma_pack.name,
			equipment=self.machine.name,
			program=self.program.name,
			queued=[],
			station=STATION,
		)
		self.assert_rejection(result, "PACK_INCOMPATIBLE", 422)
		self.assertEqual(frappe.db.count("Audit Log", {"action": "Reject"}), before + 1)
		row = frappe.get_all(
			"Audit Log",
			filters={"action": "Reject"},
			fields=["ref_doctype", "ref_name", "reason", "station", "user"],
			order_by="creation desc, name desc",
			limit=1,
		)[0]
		self.assertEqual(
			(row.ref_doctype, row.ref_name, row.reason, row.station),
			("Pack", plasma_pack.name, "PACK_INCOMPATIBLE", STATION),
		)

	@bru("BRU-FLOW-004")
	def test_add_pack_without_t4_pass_is_409(self):
		pack = make_load_ready_pack(passed=("T1", "T2", "T3"))
		result = call(
			load_api.add_pack,
			raw=pack.name,
			equipment=self.machine.name,
			program=self.program.name,
			queued=[],
			station=STATION,
		)
		self.assert_rejection(result, "GATE_PREV_NOT_PASSED", 409)
		self.assertEqual(result["error"]["redo_step"], "T4")

	def test_create_and_complete_need_a_t5_station(self):
		self.login("Administrator", OTHER_STATION)
		result = call(load_api.create, raw=self.machine.name, station=OTHER_STATION)
		self.assert_rejection(result, "STATION_WRONG_STEP", 422)

	def test_complete_replay_same_key_returns_same_load(self):
		pack = make_load_ready_pack()
		key, ts = str(uuid.uuid4()), now_ts()
		first = self.complete([pack.name], key=key, client_ts=ts)
		second = self.complete([pack.name], key=key, client_ts=ts)
		self.assertEqual(first, second)
		self.assertEqual(frappe.db.count("Load Pack", {"pack": pack.name}), 1)

	def test_complete_with_new_key_for_same_packs_rejected(self):
		pack = make_load_ready_pack()
		first = self.complete([pack.name])["load"]
		frappe.db.set_value(
			"Sterilization Load",
			first,
			{"status": "Cycle Complete", "unload_scan_at": frappe.utils.now_datetime()},
		)  # đã dỡ thì máy nạp tiếp được (A-86)
		result = self.complete([pack.name])
		self.assert_rejection(result, "LOAD_EMPTY", 422)
		self.assertEqual(result["error"]["items"][0]["code"], "PACK_IN_OTHER_LOAD")

	def test_http_status_by_error_code(self):
		self.assert_rejection(
			call(load_api.lookup, raw="ME-000101-99", station=STATION), "LOAD_NOT_FOUND", 404
		)
		other_program = make_sterilize_program(make_sterilizer().name)
		self.assert_rejection(
			self.complete([make_load_ready_pack().name], program=other_program), "PROGRAM_INVALID", 422
		)
		repair = make_sterilizer()
		frappe.db.set_value("Equipment", repair.name, "status", "Repair")
		self.assert_rejection(
			call(load_api.create, raw=repair.name, station=STATION), "EQUIPMENT_NOT_READY", 423
		)
		load = self.complete([make_load_ready_pack().name])["load"]
		other = make_sterilizer()
		self.assert_rejection(
			call(load_api.data_scan, load=load, raw=other.name, station=STATION), "EQUIPMENT_MISMATCH", 409
		)
		washer_scan = call(load_api.create, raw="LR-261023-01", station=STATION)
		self.assert_rejection(washer_scan, "SCAN_INVALID", 422)

	def test_bad_parameters_are_400(self):
		args = {"equipment": self.machine.name, "program": self.program.name, "station": STATION}
		with self.assertRaises(BadRequestError):
			call(load_api.add_pack, raw="x", queued="not json", **args)
		with self.assertRaises(BadRequestError):
			call(load_api.complete, packs=[1, 2], **args)
		with self.assertRaises(BadRequestError):
			call(load_api.complete, equipment=1, program=self.program.name, packs=[], station=STATION)
		with self.assertRaises(BadRequestError):
			call(
				load_api.manual_data,
				values="[not json",
				started_at=None,
				ended_at=None,
				confirmed=1,
				card="x",
				**self.data_args("ME-000101-01"),
			)

	def test_roles_r05_and_r02_allowed_r03_denied(self):
		for role in ("TC R05", "TC R02"):
			pack = make_load_ready_pack()
			self.as_user(f"load-{role[-3:].lower()}@test.local", (role,))
			done = self.complete([pack.name])
			self.assertIs(done["ok"], True, msg=role)
			frappe.set_user("Administrator")
			frappe.db.set_value(
				"Sterilization Load",
				done["load"],
				{"status": "Cycle Complete", "unload_scan_at": frappe.utils.now_datetime()},
			)  # A-86
		pack = make_load_ready_pack()
		self.as_user("load-r03@test.local", ("TC R03",))
		before = counts()
		with self.assertRaises(frappe.PermissionError):
			self.complete([pack.name])
		self.assertEqual(counts(), before)

	def test_session_station_mismatch(self):
		token = TOKENS[("Administrator", STATION)]
		result = call(load_api.create, raw=self.machine.name, station=OTHER_STATION, token=token)
		self.assertEqual(result["error"]["code"], "SESSION_STATION_MISMATCH")
		result = call(load_api.create, raw=self.machine.name, station=STATION, token="bad")
		self.assertEqual(result["error"]["code"], "SESSION_INVALID")

	def test_lookup_and_overview_do_not_write(self):
		pack = make_load_ready_pack()
		load = self.complete([pack.name])["load"]
		before = counts()
		info = call(load_api.lookup, raw=load, station=STATION)
		self.assertIs(info["ok"], True)
		self.assertEqual(info["load"]["load"], load)
		self.assertEqual(info["load"]["packs"][0]["cycle_id"], pack.name)
		running = call(load_api.overview, station=STATION)
		self.assertIn(load, [row["load"] for row in running["running"]])
		self.assertEqual(counts(), before)

	def test_complete_priority_flag(self):
		load = self.complete([make_load_ready_pack().name], is_priority="true")["load"]
		self.assertEqual(frappe.db.get_value("Sterilization Load", load, "is_priority"), 1)


class TestLoadDataApi(LoadApiCase):
	def test_data_scan_then_context_then_manual_data(self):
		load = self.complete([make_load_ready_pack().name])["load"]
		self.assertEqual(
			call(load_api.data_scan, load=load, raw=self.machine.name, station=STATION),
			{"ok": True, "kind": "equipment"},
		)
		self.assertEqual(
			call(load_api.data_scan, load=load, raw=load, station=STATION), {"ok": True, "kind": "load"}
		)
		context = call(load_api.data_context, **self.data_args(load))
		self.assertEqual(context["load"]["parameter_schema"][0]["parameter_name"], "Temperature")
		saved = self.manual_data(load)
		self.assertEqual((saved["ok"], saved["data_complete"], saved["status"]), (True, 1, "Cycle Complete"))
		employee = frappe.db.get_value("Employee", {"user_id": "Administrator"}, "name")
		self.assertEqual(frappe.db.get_value("Sterilization Load", load, "manual_confirmed_by"), employee)

	@bru("BRU-REP-015")
	def test_manual_data_via_rpc_uses_session_employee_and_card(self):
		load = self.complete([make_load_ready_pack().name])["load"]
		other = make_user("load-other@test.local", roles=("TC R05",))
		self.login(other, STATION)
		wrong = self.manual_data(load, card=self.card_of(other))  # thẻ của người khác với phiên Administrator
		self.assert_rejection(wrong, "CARD_MISMATCH", 403)
		missing = self.manual_data(load, values=[])
		self.assert_rejection(missing, "DATA_INCOMPLETE", 422)
		self.assertEqual(missing["error"]["items"], ["Temperature"])
		self.assertEqual(frappe.db.get_value("Sterilization Load", load, "status"), "Running")

	def test_manual_data_replay_same_key(self):
		load = self.complete([make_load_ready_pack().name])["load"]
		key, ts = str(uuid.uuid4()), now_ts()
		started, ended = str(add_to_date(now_datetime(), hours=-1)), str(now_datetime())
		same = {"key": key, "client_ts": ts, "started_at": started, "ended_at": ended}
		first = self.manual_data(load, **same)
		second = self.manual_data(load, **same)
		self.assertEqual(first, second)
		self.assertEqual(frappe.db.get_value("Sterilization Load", load, "status"), "Cycle Complete")

	def test_data_station_exit_zone_allowed_other_station_denied(self):
		load = self.complete([make_load_ready_pack().name])["load"]
		self.login("Administrator", "TR-006")
		saved = self.manual_data(load, station="TR-006")
		self.assertIs(saved["ok"], True, msg=saved)
		self.login("Administrator", OTHER_STATION)
		denied = call(load_api.data_scan, load=load, raw=self.machine.name, station=OTHER_STATION)
		self.assert_rejection(denied, "STATION_WRONG_STEP", 422)

	def test_closed_load_is_409(self):
		pack = make_load_ready_pack()
		load = make_load(self.machine, self.program, [pack])
		frappe.db.set_value("Sterilization Load", load.name, "status", "Released")
		result = call(load_api.data_scan, load=load.name, raw=self.machine.name, station=STATION)
		self.assert_rejection(result, "LOAD_NOT_OPEN", 409)
