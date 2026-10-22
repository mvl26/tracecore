"""RPC tracecore.v1.putaway.* và pack.mark_damaged (FEAT-025 Task 5): quét T6, tồn, FEFO, mã HTTP, quyền, idempotent."""

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import frappe

from tracecore import hooks
from tracecore.tests import factories
from tracecore.tests.factories import make_sterile_location, make_user
from tracecore.tests.utils import IsolatedTestCase, bru, request_headers
from tracecore.v1 import pack as pack_api
from tracecore.v1 import putaway as putaway_api

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

STATION = "TR-006"
TIME_ZONE = ZoneInfo("Asia/Ho_Chi_Minh")


def as_administrator(fn, *args, **kwargs):
	"""Dựng dữ liệu bằng quyền Administrator: factory không chạy được với quyền R06 của người dùng kiosk."""
	user = frappe.session.user
	frappe.set_user("Administrator")
	try:
		return fn(*args, **kwargs)
	finally:
		frappe.set_user(user)


def make_released_pack(**kwargs):
	return as_administrator(factories.make_released_pack, **kwargs)


def make_set_type(code):
	return as_administrator(factories.make_set_type, code)


def now_ts():
	return datetime.now(TIME_ZONE).isoformat(timespec="seconds")


def call(fn, key=None, station_header=STATION, **kwargs):
	frappe.local.response.pop("http_status_code", None)
	kwargs.setdefault("client_ts", now_ts())
	with request_headers({"X-Idempotency-Key": key or str(uuid.uuid4()), "X-TC-Station": station_header}):
		return fn(**kwargs)


def http_status():
	return frappe.local.response.get("http_status_code")


class PutawayApiCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.shelf = make_sterile_location("Kệ API")
		self.as_user("kho@example.com", ["TC R06"])

	def as_user(self, email, roles):
		frappe.set_user(make_user(email, roles=roles))
		self.addCleanup(frappe.set_user, "Administrator")


class TestScan(PutawayApiCase):
	def test_scan_pack_returns_card_with_gates(self):
		pack = make_released_pack()
		res = call(putaway_api.scan, raw=pack.name, station=STATION)
		self.assertTrue(res["ok"])
		self.assertEqual(res["kind"], "pack")
		self.assertEqual(res["pack"]["cycle_id"], pack.name)
		self.assertEqual(res["pack"]["status"], "Released")
		self.assertEqual([g["result"] for g in res["pack"]["gates"]], ["Pass"] * 5)

	def test_scan_pack_shows_missing_gates_without_blocking(self):
		pack = make_released_pack(passed=("T1", "T2", "T3"))
		res = call(putaway_api.scan, raw=pack.name, station=STATION)
		self.assertEqual([g["result"] for g in res["pack"]["gates"]][3:], ["Pending", "Pending"])

	@bru("BRU-FLOW-004", "BRU-REP-008")
	def test_scan_location_after_pack_stores_it(self):
		pack = make_released_pack()
		res = call(putaway_api.scan, raw=self.shelf.name, station=STATION, open_pack=pack.name)
		self.assertTrue(res["ok"])
		self.assertEqual(res["kind"], "stored")
		self.assertEqual(res["stored"]["location"], self.shelf.name)
		self.assertEqual(frappe.db.get_value("Pack", pack.name, "status"), "In Sterile Stock")

	def test_scan_location_without_open_pack_is_rejected(self):
		res = call(putaway_api.scan, raw=self.shelf.name, station=STATION)
		self.assertFalse(res["ok"])
		self.assertEqual(res["error"]["code"], "SCAN_INVALID")
		self.assertEqual(http_status(), 422)

	def test_unknown_shelf_is_404_and_audited(self):
		pack = make_released_pack()
		before = frappe.db.count("Audit Log", {"action": "Reject"})
		res = call(putaway_api.scan, raw="KE-9999", station=STATION, open_pack=pack.name)
		self.assertEqual(res["error"]["code"], "LOCATION_NOT_FOUND")
		self.assertEqual(http_status(), 404)
		self.assertEqual(frappe.db.count("Audit Log", {"action": "Reject"}), before + 1)

	@bru("BRU-FLOW-004")
	def test_unreleased_pack_is_409(self):
		pack = make_released_pack(status="Quarantine")
		res = call(putaway_api.scan, raw=self.shelf.name, station=STATION, open_pack=pack.name)
		self.assertEqual(res["error"]["code"], "PACK_NOT_RELEASED")
		self.assertEqual(http_status(), 409)

	def test_missing_gates_listed_in_error_items(self):
		pack = make_released_pack(passed=("T1", "T2", "T3"))
		res = call(putaway_api.scan, raw=self.shelf.name, station=STATION, open_pack=pack.name)
		self.assertEqual(res["error"]["code"], "GATE_PREV_NOT_PASSED")
		self.assertEqual(res["error"]["items"], ["T4", "T5"])

	def test_unknown_code_is_scan_invalid(self):
		res = call(putaway_api.scan, raw="hello", station=STATION)
		self.assertEqual(res["error"]["code"], "SCAN_INVALID")

	def test_wrong_station_step(self):
		pack = make_released_pack()
		res = call(putaway_api.scan, raw=pack.name, station="TR-004")
		self.assertEqual(res["error"]["code"], "STATION_WRONG_STEP")
		self.assertEqual(http_status(), 422)

	def test_replay_with_same_key_does_not_store_twice(self):
		pack = make_released_pack()
		key = str(uuid.uuid4())
		kwargs = {"raw": self.shelf.name, "station": STATION, "open_pack": pack.name, "client_ts": now_ts()}
		first = call(putaway_api.scan, key=key, **kwargs)
		second = call(putaway_api.scan, key=key, **kwargs)
		self.assertEqual(frappe.parse_json(frappe.as_json(first)), second)  # replay trả bản đã qua JSON
		self.assertEqual(frappe.db.count("Sterile Putaway", {"pack": pack.name}), 1)

	def test_requires_storage_role(self):
		self.as_user("khu.sach@example.com", ["TC R04"])
		with self.assertRaises(frappe.PermissionError):
			call(putaway_api.scan, raw="x", station=STATION)


class TestMarkDamaged(PutawayApiCase):
	def stocked(self):
		pack = make_released_pack()
		call(putaway_api.scan, raw=self.shelf.name, station=STATION, open_pack=pack.name)
		return pack

	@bru("BRU-ID-003")
	def test_mark_damaged_voids_pack_and_set_awaits_receipt(self):
		pack = self.stocked()
		res = call(pack_api.mark_damaged, cycle_id=pack.name, reason="Rách góc bao", station=STATION)
		self.assertTrue(res["ok"])
		self.assertEqual((res["status"], res["void_reason"]), ("Void", "Torn"))
		self.assertEqual(frappe.db.get_value("Set Unit", pack.set_unit, "status"), "Awaiting Receipt")

	def test_mark_damaged_needs_reason(self):
		pack = self.stocked()
		res = call(pack_api.mark_damaged, cycle_id=pack.name, reason="", station=STATION)
		self.assertEqual(res["error"]["code"], "REASON_REQUIRED")
		self.assertEqual(http_status(), 422)

	def test_mark_damaged_pack_not_in_stock_is_409(self):
		pack = make_released_pack()
		res = call(pack_api.mark_damaged, cycle_id=pack.name, reason="Rách", station=STATION)
		self.assertEqual(res["error"]["code"], "PACK_NOT_IN_STOCK")
		self.assertEqual(http_status(), 409)

	def test_mark_damaged_requires_storage_role(self):
		pack = self.stocked()
		self.as_user("khu.sach@example.com", ["TC R04"])
		with self.assertRaises(frappe.PermissionError):
			call(pack_api.mark_damaged, cycle_id=pack.name, reason="Rách", station=STATION)


class TestReads(PutawayApiCase):
	def test_overview_returns_stock_expiring_and_return_list(self):
		pack = make_released_pack(expiry_days=3)
		call(putaway_api.scan, raw=self.shelf.name, station=STATION, open_pack=pack.name)
		res = putaway_api.overview(station=STATION)
		self.assertTrue(res["ok"])
		self.assertIn(pack.name, [row["cycle_id"] for row in res["expiring"]])
		self.assertIn(self.shelf.name, [row["location"] for row in res["by_location"]])
		self.assertIn("return_list", res)

	def test_fefo_returns_nearest_expiry_pack(self):
		set_type = make_set_type("T6F001")
		near = make_released_pack(set_type=set_type.name, expiry_days=2)
		far = make_released_pack(set_type=set_type.name, expiry_days=20)
		for pack in (far, near):
			call(putaway_api.scan, raw=self.shelf.name, station=STATION, open_pack=pack.name)
		res = putaway_api.fefo(set_type=set_type.name, cycle_id=far.name)
		self.assertEqual(res["suggested"]["cycle_id"], near.name)
		self.assertEqual(res["warning"]["code"], "FEFO_NEARER_PACK")

	def test_reads_require_storage_role(self):
		self.as_user("khu.sach@example.com", ["TC R04"])
		with self.assertRaises(frappe.PermissionError):
			putaway_api.overview(station=STATION)


class TestScheduler(IsolatedTestCase):
	@bru("BRU-ID-003")
	def test_expiry_runs_at_midnight(self):
		self.assertIn(
			"tracecore.reprocessing.storage.run_expiry", hooks.scheduler_events["cron"]["0 0 * * *"]
		)
