"""RPC tracecore.v1.sync.snapshot / status (FEAT-009 Task 4; ADR-003 dữ liệu đọc offline; A-40 D2, D4)."""

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import frappe

from tracecore.reprocessing.tests.test_usage import issue
from tracecore.tests.factories import (
	make_department,
	make_employee,
	make_set_unit,
	make_stocked_pack,
	make_t4_ready_set,
	make_user,
)
from tracecore.tests.utils import IsolatedTestCase, request_headers
from tracecore.v1 import sync as sync_api
from tracecore.v1.tests.station_fixtures import make_station_session

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]
TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def snapshot(station, token):
	with request_headers({"X-TC-Station": station}):
		return sync_api.snapshot(
			station=station, client_ts=datetime.now(TZ).isoformat(timespec="seconds"), token=token
		)


class SnapshotCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		frappe.get_doc("User", "Administrator").add_roles("TC R10", "TC R03", "TC R04", "TC R08")
		self.addCleanup(frappe.set_user, "Administrator")

	def token(self, station):
		return make_station_session("Administrator", station)["token"]


class TestSnapshotT1(SnapshotCase):
	def test_snapshot_t1_lists_receivable_sets(self):
		ready = make_t4_ready_set()  # đang Processing: T1 không nhận
		unit = make_set_unit(ready.set_type)  # New: T1 nhận
		result = snapshot("TR-001", self.token("TR-001"))
		self.assertIs(result["ok"], True)
		self.assertEqual(result["function"], "RECEIVE")
		sets = {row["set_id"]: row for row in result["sets"]}
		self.assertIn(unit.name, sets)
		self.assertNotIn(ready.set_id, sets)
		row = sets[unit.name]
		self.assertEqual(row["status"], "New")
		self.assertEqual(sorted(line["instrument"] for line in row["bom"]), sorted(ready.instruments))
		self.assertTrue(all(line["qty"] > 0 for line in row["bom"]))
		self.assertIn("departments", result)


class TestSnapshotT4(SnapshotCase):
	def test_snapshot_t4_only_t3_passed_and_flags(self):
		ready = make_t4_ready_set()
		not_ready = make_set_unit(ready.set_type)  # New: chưa qua T3
		result = snapshot("TR-004", self.token("TR-004"))
		self.assertEqual(result["function"], "PACK")
		sets = {row["set_id"]: row for row in result["sets"]}
		self.assertIn(ready.set_id, sets)
		self.assertNotIn(not_ready.name, sets)
		row = sets[ready.set_id]
		self.assertEqual(sorted(line["instrument"] for line in row["bom"]), sorted(ready.instruments))
		self.assertIs(row["par_blocked"], False)
		self.assertIs(row["maint_pending"], False)
		self.assertEqual(row["context"]["set"]["set_id"], ready.set_id)  # màn T4 offline vẽ từ ngữ cảnh này
		self.assertIsNone(row["context"]["printer"])
		self.assertIn("ci_class", result["ci_batches"][0])
		self.assertIn(ready.pack_type, [p["item"] for p in row["pack_types"]])
		self.assertIn(ready.ci_batch, [lot["batch"] for lot in result["ci_batches"]])
		self.assertTrue(result["ranges"])
		self.assertTrue(result["ranges"][0]["prefix"].endswith("-T004-"))

	def test_snapshot_t4_is_read_only(self):
		ready = make_t4_ready_set(max_cycles=1)
		# hết cơ số: T4 online sẽ chặn PAR_EXCEEDED và chuyển bộ sang Hết vòng đời
		frappe.db.set_value("Set Unit", ready.set_id, "cycles_used", 1, update_modified=False)
		token = self.token("TR-004")
		rejects = frappe.db.count("Audit Log", {"action": "Reject"})
		result = snapshot("TR-004", token)
		row = {r["set_id"]: r for r in result["sets"]}.get(ready.set_id)
		self.assertIsNotNone(row)
		self.assertIs(row["par_blocked"], True)
		self.assertEqual(frappe.db.get_value("Set Unit", ready.set_id, "status"), "Processing")
		self.assertEqual(frappe.db.count("Audit Log", {"action": "Reject"}), rejects)


class TestSnapshotT8(SnapshotCase):
	def test_snapshot_t8_only_department_issued_packs_and_key(self):
		dept = make_department("Khoa snapshot T8")
		other = make_department("Khoa khác snapshot T8")
		mine = issue(make_stocked_pack(), dept)
		theirs = issue(make_stocked_pack(), other)
		user = make_user("snap-t8@example.com", roles=("TC R08",))
		employee = make_employee(first_name="Snapshot T8", department=dept)
		frappe.db.set_value("Employee", employee.name, "user_id", user)
		token = make_station_session(user, "TR-008")["token"]
		frappe.set_user(user)
		result = snapshot("TR-008", token)
		self.assertEqual(result["function"], "USE")
		packs = {row["cycle_id"]: row for row in result["packs"]}
		self.assertIn(mine.name, packs)
		self.assertNotIn(theirs.name, packs)
		self.assertEqual(packs[mine.name]["status"], "Issued")
		self.assertTrue(packs[mine.name]["expiry"])
		self.assertIn("BEGIN PUBLIC KEY", result["patient_key"])
		self.assertNotIn("PRIVATE", result["patient_key"])


class TestSnapshotOther(SnapshotCase):
	def test_snapshot_other_step_offline_false(self):
		frappe.get_doc("User", "Administrator").add_roles("TC R05")
		result = snapshot("TR-005", self.token("TR-005"))
		self.assertEqual(result, {"ok": True, "function": "STERI_LOAD", "offline": False})

	def test_snapshot_requires_session(self):
		result = snapshot("TR-004", "invalid-" + uuid.uuid4().hex)
		self.assertIs(result["ok"], False)
		self.assertEqual(result["error"]["code"], "SESSION_INVALID")


class TestStatus(SnapshotCase):
	def test_status_counts_open_conflicts(self):
		from tracecore.core import sync

		sync.record_conflict(
			endpoint="tracecore.v1.pack.generate_cycle_id",
			key=str(uuid.uuid4()),
			client_ts=datetime(2026, 10, 26, 2, 0),
			args={"station": "TR-004"},
			error={"code": "CODE_RANGE_INVALID", "http_status": 409},
			http_status=409,
		)
		result = sync_api.status(station="TR-004")
		self.assertGreaterEqual(result["open_conflicts"], 1)
		self.assertTrue(result["last_conflict"])
