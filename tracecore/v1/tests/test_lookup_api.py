"""RPC tracecore.v1.lookup.* (A-68): gợi ý thiết bị / bộ cho chọn tay trên trạm, và ghi cách nhập vào Audit Log."""

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import frappe
from frappe.utils import add_to_date, now_datetime

from tracecore.core import step_gate
from tracecore.tests.factories import (
	deactivate_printers,
	make_cycle,
	make_department,
	make_equipment,
	make_released_pack,
	make_set_unit,
	make_stocked_pack,
	make_user,
	make_wash_machine,
	make_wash_ready_set,
)
from tracecore.tests.utils import IsolatedTestCase, request_headers
from tracecore.v1 import lookup as lookup_api
from tracecore.v1 import wash as wash_api
from tracecore.v1.tests.station_fixtures import make_station_session

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

TIME_ZONE = ZoneInfo("Asia/Ho_Chi_Minh")
TOKENS = {}


def station_of(step):
	return frappe.db.get_value("Zone Station", {"station_step": step, "is_zone": 0, "is_active": 1}, "name")


def now_ts():
	return datetime.now(TIME_ZONE).isoformat(timespec="seconds")


def call(fn, station, **kwargs):
	frappe.local.response.pop("http_status_code", None)
	kwargs.setdefault("client_ts", now_ts())
	kwargs.setdefault("token", TOKENS.get((frappe.session.user, station)))
	with request_headers({"X-Idempotency-Key": str(uuid.uuid4()), "X-TC-Station": station}):
		return fn(station=station, **kwargs)


def ids(result):
	return [row["id"] for row in result["items"]]


class LookupCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		TOKENS.clear()
		self.addCleanup(TOKENS.clear)
		self.addCleanup(frappe.local.response.pop, "http_status_code", None)

	def login(self, step, user="Administrator"):
		station = station_of(step)
		TOKENS[(user, station)] = make_station_session(user, station=station)["token"]
		return station

	def sets(self, step, **kwargs):
		return call(lookup_api.set_units, self.login(step), **kwargs)


class TestLookupEquipment(LookupCase):
	def test_t2_lists_only_ready_washers_matching_query(self):
		washer = make_wash_machine()
		ultrasonic = make_equipment("Máy siêu âm", "Ultrasonic Cleaner", serial="SN-US1")
		sterilizer = make_equipment("Máy hấp", "Steam Sterilizer", serial="SN-ST1")
		locked = make_wash_machine()
		frappe.db.set_value("Equipment", locked.name, "status", "Locked")
		result = call(lookup_api.equipment, self.login("T2"))
		self.assertTrue(result["ok"])
		found = ids(result)
		self.assertIn(washer.name, found)
		self.assertIn(ultrasonic.name, found)
		self.assertNotIn(sterilizer.name, found)
		self.assertNotIn(locked.name, found)
		row = next(r for r in result["items"] if r["id"] == washer.name)
		self.assertEqual(row["label"], f"{washer.name} {chr(0x2013)} {washer.equipment_name}")

	def test_t5_lists_only_sterilizers_and_search_by_name_or_code(self):
		steam = make_equipment("Hấp lớn Alpha", "Steam Sterilizer", serial="SN-A")
		plasma = make_equipment("Plasma Beta", "Plasma Sterilizer", serial="SN-B")
		make_wash_machine()
		station = self.login("T5")
		self.assertEqual(
			set(ids(call(lookup_api.equipment, station))) & {steam.name, plasma.name},
			{steam.name, plasma.name},
		)
		by_name = call(lookup_api.equipment, station, q="alpha")
		self.assertEqual(ids(by_name), [steam.name])
		by_code = call(lookup_api.equipment, station, q=plasma.name)
		self.assertEqual(ids(by_code), [plasma.name])

	def test_pagination_reports_total(self):
		for index in range(3):
			make_equipment(f"Hấp {index}", "Steam Sterilizer", serial=f"SN-P{index}")
		station = self.login("T5")
		page = call(lookup_api.equipment, station, page_length=2)
		self.assertEqual(len(page["items"]), 2)
		self.assertGreaterEqual(page["total"], 3)
		rest = call(lookup_api.equipment, station, start=2, page_length=2)
		self.assertFalse(set(ids(page)) & set(ids(rest)))

	def test_other_role_is_forbidden_and_writes_nothing(self):
		user = make_user("pick-r08@tracecore.test", roles=["TC R08"])
		station = station_of("T2")
		TOKENS[(user, station)] = make_station_session(user, station=station)["token"]
		frappe.set_user(user)
		before = frappe.db.count("Audit Log")
		with self.assertRaises(frappe.PermissionError):
			call(lookup_api.equipment, station)
		self.assertEqual(frappe.db.count("Audit Log"), before)

	def test_wrong_step_station_is_rejected(self):
		result = call(lookup_api.equipment, self.login("T1"))
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "STATION_WRONG_STEP")


class TestLookupSetUnits(LookupCase):
	def test_t1_lists_receivable_sets_with_department_and_priority(self):
		own = make_department("Khoa Nội pick")
		other = make_department("Khoa Ngoại pick")
		mine = make_set_unit(department=own)
		theirs = make_set_unit(department=other)
		done = make_wash_ready_set()  # đã qua T1: không còn tiếp nhận được
		station = self.login("T1")
		result = call(lookup_api.set_units, station, department=own)
		found = ids(result)
		self.assertIn(mine.name, found)
		self.assertIn(theirs.name, found)
		self.assertNotIn(done.name, found)
		self.assertLess(found.index(mine.name), found.index(theirs.name))
		row = next(r for r in result["items"] if r["id"] == mine.name)
		self.assertEqual(row["raw"], mine.name)
		self.assertIn(mine.name, row["label"])
		self.assertIn(frappe.db.get_value("Department", own, "department_name"), row["label"])

	def test_t1_search_by_code_and_name(self):
		unit = make_set_unit()
		other = make_set_unit()
		station = self.login("T1")
		self.assertEqual(ids(call(lookup_api.set_units, station, q=unit.name)), [unit.name])
		by_name = call(lookup_api.set_units, station, q=unit.set_type_name or unit.set_type)
		self.assertIn(unit.name, ids(by_name))
		self.assertIn(other.name, ids(by_name))

	def test_t2_lists_only_received_sets_oldest_first(self):
		newer = make_wash_ready_set()
		older = make_wash_ready_set()
		frappe.db.set_value(
			"Step Gate Result",
			f"{older.name}-C{older.current_cycle_no}-T1",
			"recorded_at",
			add_to_date(now_datetime(), hours=-3),
		)
		new_unit = make_set_unit()  # chưa tiếp nhận
		result = self.sets("T2")
		found = ids(result)
		self.assertIn(older.name, found)
		self.assertIn(newer.name, found)
		self.assertNotIn(new_unit.name, found)
		self.assertLess(found.index(older.name), found.index(newer.name))
		self.assertTrue(result["items"][0]["since"])

	def test_each_set_step_lists_only_sets_waiting_there(self):
		t2_done = make_set_unit()
		make_cycle(t2_done, passed=("T1", "T2"))
		t3_done = make_set_unit()
		make_cycle(t3_done, passed=("T1", "T2", "T3"))
		self.assertIn(t2_done.name, ids(self.sets("T3")))
		self.assertNotIn(t3_done.name, ids(self.sets("T3")))
		self.assertIn(t3_done.name, ids(self.sets("T4")))
		self.assertNotIn(t2_done.name, ids(self.sets("T4")))

	def test_pack_steps_list_packs_by_status(self):
		packed = make_released_pack(status="Packed", passed=("T1", "T2", "T3", "T4"))
		released = make_released_pack(status="Released")
		stocked = make_stocked_pack()
		issued = make_released_pack(status="Issued")
		self.assertIn(packed.name, ids(self.sets("T5")))
		self.assertNotIn(released.name, ids(self.sets("T5")))
		self.assertIn(released.name, ids(self.sets("T6")))
		self.assertNotIn(stocked.name, ids(self.sets("T6")))
		self.assertIn(stocked.name, ids(self.sets("T7")))
		self.assertNotIn(issued.name, ids(self.sets("T7")))
		self.assertIn(issued.name, ids(self.sets("T8")))
		self.assertNotIn(stocked.name, ids(self.sets("T8")))
		row = next(r for r in self.sets("T8")["items"] if r["id"] == issued.name)
		self.assertEqual(row["raw"], issued.name)

	def test_pagination_and_forbidden_role(self):
		for _i in range(3):
			make_set_unit()
		station = self.login("T1")
		page = call(lookup_api.set_units, station, page_length=2)
		self.assertEqual(len(page["items"]), 2)
		self.assertGreaterEqual(page["total"], 3)
		user = make_user("pick-r05@tracecore.test", roles=["TC R05"])
		TOKENS[(user, station)] = make_station_session(user, station=station)["token"]
		frappe.set_user(user)
		with self.assertRaises(frappe.PermissionError):
			call(lookup_api.set_units, station)


class TestManualEntryAudit(LookupCase):
	"""Chọn tay đi qua đúng hàm kiểm tra như khi quét; Audit Log phân biệt Quét / Chọn tay (A-68)."""

	def setUp(self):
		super().setUp()
		self.station = self.login("T2")
		deactivate_printers(self.station)
		self.machine = make_wash_machine()

	def add_set(self, raw, **kwargs):
		return call(wash_api.add_set, self.station, raw=raw, equipment=self.machine.name, queued=[], **kwargs)

	def test_manual_pick_of_wrong_sequence_set_is_blocked_like_scan(self):
		unit = make_set_unit()  # chưa tiếp nhận T1
		scanned = self.add_set(unit.name)
		manual = self.add_set(unit.name, entry_mode="Manual", manual_reason="Scanner broken")
		self.assertFalse(scanned["ok"])
		self.assertFalse(manual["ok"])
		self.assertEqual(manual["error"]["code"], scanned["error"]["code"])

	def test_audit_log_tells_manual_from_scan(self):
		unit = make_wash_ready_set()
		self.add_set(unit.name)
		self.assertFalse(frappe.db.exists("Audit Log", {"action": "Manual Entry", "ref_name": unit.name}))
		self.add_set(unit.name, entry_mode="Manual", manual_reason="Scanner broken")
		row = frappe.db.get_value(
			"Audit Log",
			{"action": "Manual Entry", "ref_name": unit.name},
			["entry_mode", "reason", "station"],
			as_dict=True,
		)
		self.assertEqual(row.entry_mode, "Manual")
		self.assertEqual(row.reason, "Scanner broken")
		self.assertEqual(row.station, self.station)

	def test_manual_without_reason_is_rejected_before_any_work(self):
		unit = make_wash_ready_set()
		result = self.add_set(unit.name, entry_mode="Manual")
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "MANUAL_REASON_REQUIRED")

	def test_invalid_entry_mode_is_bad_request(self):
		unit = make_wash_ready_set()
		with self.assertRaises(frappe.ValidationError):
			self.add_set(unit.name, entry_mode="Telepathy")

	def test_rejected_scan_is_logged_with_scan_mode(self):
		unit = make_set_unit()
		self.add_set(unit.name)
		mode = frappe.db.get_value("Audit Log", {"action": "Reject", "station": self.station}, "entry_mode")
		self.assertEqual(mode, "Scan")

	def test_step_gate_is_untouched_by_lookup(self):
		unit = make_wash_ready_set()
		before = step_gate.gates(unit.name)
		self.sets("T2")
		self.assertEqual(step_gate.gates(unit.name), before)


class TestScanRpcsAcceptEntryMode(LookupCase):
	"""Mọi RPC quét của trạm nhận cách nhập, mặc định Quét (A-68)."""

	def test_scan_rpcs_default_to_scan(self):
		import inspect

		from tracecore.v1 import assembly, issue, load, pack, putaway, receive, usage

		for fn in (
			wash_api.start,
			wash_api.add_set,
			load.create,
			load.add_pack,
			pack.scan,
			putaway.scan,
			usage.scan,
			receive.scan_set,
			assembly.open,
			issue.add_pack,
		):
			params = inspect.signature(getattr(fn, "__wrapped__", fn)).parameters
			self.assertEqual(params["entry_mode"].default, "Scan", fn.__qualname__)
			self.assertIn("manual_reason", params, fn.__qualname__)

	def test_manual_machine_pick_logs_and_checks_like_scan(self):
		station = self.login("T2")
		deactivate_printers(station)
		machine = make_wash_machine()
		scanned = call(wash_api.start, station, raw=machine.name)
		manual = call(wash_api.start, station, raw=machine.name, entry_mode="Manual", manual_reason="Mã mờ")
		self.assertTrue(scanned["ok"])
		self.assertEqual(manual["equipment"], scanned["equipment"])
		self.assertEqual(
			frappe.db.get_value("Audit Log", {"action": "Manual Entry", "ref_name": machine.name}, "reason"),
			"Mã mờ",
		)
