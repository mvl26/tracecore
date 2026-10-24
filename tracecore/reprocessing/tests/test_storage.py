"""Kho vô khuẩn T6 (FEAT-025, UC-11): nhập kho theo vị trí, hết hạn 00:00, báo rách, tồn, FEFO."""

import frappe
from frappe.utils import add_days, getdate, today

from tracecore.core.errors import BlockedError
from tracecore.reprocessing import storage
from tracecore.tests.factories import (
	make_released_pack,
	make_set_type,
	make_sterile_location,
)
from tracecore.tests.utils import IsolatedTestCase, bru

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

STATION = "TR-006"


def blocked(testcase, code, fn, *args, **kwargs):
	"""Gọi `fn` và kiểm nó ném BlockedError mang mã `code`; trả Block."""
	with testcase.assertRaises(BlockedError) as caught:
		fn(*args, **kwargs)
	testcase.assertEqual(caught.exception.block.code, code)
	return caught.exception.block


def stock_pack(shelf, expiry_days=30, **kwargs):
	"""Pack Released nhập vào `shelf`, rồi đặt hạn = hôm nay + `expiry_days` (ghi thẳng DB, như thời gian trôi)."""
	pack = make_released_pack(**kwargs)
	storage.putaway(pack.name, shelf.name, STATION)
	frappe.db.set_value("Pack", pack.name, "expiry", add_days(today(), expiry_days), update_modified=False)
	return pack


def pack_row(pack):
	return frappe.db.get_value(
		"Pack", pack.name, ["status", "location", "void_reason", "void_note"], as_dict=True
	)


def set_status(pack):
	return frappe.db.get_value("Set Unit", pack.set_unit, ["status", "active_cycle_id"], as_dict=True)


class TestPutaway(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.shelf = make_sterile_location("Kệ A1")

	@bru("BRU-FLOW-004", "BRU-REP-008")
	def test_putaway_moves_released_pack_into_stock(self):
		pack = make_released_pack()
		result = storage.putaway(pack.name, self.shelf.name, STATION)
		self.assertEqual(pack_row(pack).status, "In Sterile Stock")
		self.assertEqual(pack_row(pack).location, self.shelf.name)
		self.assertEqual(result["action"], "Putaway")
		self.assertEqual((result["cycle_id"], result["location"]), (pack.name, self.shelf.name))

	def test_putaway_creates_submitted_sterile_putaway(self):
		pack = make_released_pack()
		result = storage.putaway(pack.name, self.shelf.name, STATION)
		row = frappe.db.get_value(
			"Sterile Putaway",
			result["putaway"],
			["docstatus", "pack", "location", "action", "station", "putaway_by_user"],
			as_dict=True,
		)
		self.assertEqual(
			(row.docstatus, row.pack, row.location, row.action, row.station, row.putaway_by_user),
			(1, pack.name, self.shelf.name, "Putaway", STATION, frappe.session.user),
		)

	def test_putaway_accepts_datamatrix_and_hri_of_pack(self):
		pack = make_released_pack()
		hri = f"(01){pack.gtin}(11){getdate(pack.packed_at):%y%m%d}(17){getdate(pack.expiry):%y%m%d}(21){pack.name}"
		storage.putaway(hri, self.shelf.name, STATION)
		self.assertEqual(pack_row(pack).status, "In Sterile Stock")

	@bru("BRU-FLOW-004")
	def test_putaway_rejects_pack_not_released(self):
		for status in ("Packed", "In Load", "Quarantine"):
			pack = make_released_pack(status=status)
			block = blocked(self, "PACK_NOT_RELEASED", storage.putaway, pack.name, self.shelf.name, STATION)
			self.assertIn(status, block.reason or "")  # nêu rõ trạng thái hiện tại của gói
			self.assertEqual(pack_row(pack).status, status)
			self.assertIsNone(pack_row(pack).location)

	@bru("BRU-FLOW-004")
	def test_putaway_rejects_set_with_missing_gates_and_lists_them(self):
		pack = make_released_pack(passed=("T1", "T2", "T3"))
		block = blocked(self, "GATE_PREV_NOT_PASSED", storage.putaway, pack.name, self.shelf.name, STATION)
		self.assertEqual(block.items, ["T4", "T5"])
		self.assertEqual(pack_row(pack).status, "Released")

	def test_putaway_rejects_unknown_location(self):
		pack = make_released_pack()
		blocked(self, "LOCATION_NOT_FOUND", storage.putaway, pack.name, "KE-9999", STATION)
		self.assertEqual(pack_row(pack).status, "Released")

	def test_putaway_rejects_inactive_location(self):
		self.shelf.is_active = 0
		self.shelf.save()
		pack = make_released_pack()
		blocked(self, "LOCATION_INACTIVE", storage.putaway, pack.name, self.shelf.name, STATION)

	def test_putaway_rejects_wrong_scan_types(self):
		pack = make_released_pack()
		blocked(self, "SCAN_INVALID", storage.putaway, "xyz", self.shelf.name, STATION)
		blocked(self, "SCAN_INVALID", storage.putaway, pack.name, pack.set_unit, STATION)
		blocked(self, "SCAN_INVALID", storage.putaway, pack.name, "CN-00001", STATION)

	def test_putaway_unknown_pack(self):
		blocked(self, "PACK_NOT_FOUND", storage.putaway, "CY-200101-0001", self.shelf.name, STATION)

	def test_putaway_rejects_expired_pack(self):
		pack = make_released_pack(expiry_days=-1)
		blocked(self, "PACK_EXPIRED", storage.putaway, pack.name, self.shelf.name, STATION)
		self.assertEqual(pack_row(pack).status, "Released")

	def test_putaway_pack_that_expires_today_is_accepted(self):
		pack = make_released_pack(expiry_days=0)
		storage.putaway(pack.name, self.shelf.name, STATION)
		self.assertEqual(pack_row(pack).status, "In Sterile Stock")

	def test_move_pack_to_other_location(self):
		other = make_sterile_location("Kệ B2")
		pack = make_released_pack()
		storage.putaway(pack.name, self.shelf.name, STATION)
		result = storage.putaway(pack.name, other.name, STATION)
		self.assertEqual(result["action"], "Move")
		self.assertEqual(result["previous_location"], self.shelf.name)
		self.assertEqual(pack_row(pack).location, other.name)
		move = frappe.db.get_value(
			"Sterile Putaway", result["putaway"], ["action", "from_location"], as_dict=True
		)
		self.assertEqual((move.action, move.from_location), ("Move", self.shelf.name))

	def test_move_to_same_location_is_rejected(self):
		pack = make_released_pack()
		storage.putaway(pack.name, self.shelf.name, STATION)
		blocked(self, "PACK_ALREADY_ON_LOCATION", storage.putaway, pack.name, self.shelf.name, STATION)


class TestDamagedAndExpiry(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.shelf = make_sterile_location("Kệ A1")

	def stocked(self, expiry_days=30, **kwargs):
		"""Gói đã vào kho; hạn đặt sau khi nhập (nhập kho từ chối gói quá hạn) để giả lập thời gian trôi."""
		return stock_pack(self.shelf, expiry_days=expiry_days, **kwargs)

	@bru("BRU-ID-003")
	def test_mark_damaged_voids_pack_and_returns_set_for_receipt(self):
		pack = self.stocked()
		result = storage.mark_damaged(pack.name, "Bao gói bị ướt", STATION)
		row = pack_row(pack)
		self.assertEqual((row.status, row.void_reason, row.void_note), ("Void", "Torn", "Bao gói bị ướt"))
		self.assertEqual(set_status(pack).status, "Awaiting Receipt")
		self.assertIsNone(set_status(pack).active_cycle_id)
		self.assertEqual(frappe.db.get_value("Code Registry", pack.name, "status"), "Disabled")
		self.assertEqual((result["cycle_id"], result["status"]), (pack.name, "Void"))

	def test_mark_damaged_requires_reason(self):
		pack = self.stocked()
		blocked(self, "REASON_REQUIRED", storage.mark_damaged, pack.name, "  ", STATION)
		self.assertEqual(pack_row(pack).status, "In Sterile Stock")

	def test_mark_damaged_only_for_pack_in_stock(self):
		pack = make_released_pack()
		blocked(self, "PACK_NOT_IN_STOCK", storage.mark_damaged, pack.name, "Rách", STATION)
		blocked(self, "PACK_NOT_FOUND", storage.mark_damaged, "CY-200101-0001", "Rách", STATION)

	def test_mark_damaged_twice_is_rejected(self):
		pack = self.stocked()
		storage.mark_damaged(pack.name, "Rách", STATION)
		blocked(self, "PACK_NOT_IN_STOCK", storage.mark_damaged, pack.name, "Rách", STATION)

	@bru("BRU-ID-003")
	def test_expire_due_voids_packs_past_expiry_only(self):
		expired = self.stocked(expiry_days=-1)
		last_day = self.stocked(expiry_days=0)
		fresh = self.stocked(expiry_days=10)
		released = make_released_pack(expiry_days=-3)  # chưa nhập kho nhưng đã quá hạn
		names = storage.expire_due()
		self.assertCountEqual(names, [expired.name, released.name])
		self.assertEqual(pack_row(expired).status, "Void")
		self.assertEqual(pack_row(expired).void_reason, "Expired")
		self.assertEqual(set_status(expired).status, "Awaiting Receipt")
		self.assertEqual(pack_row(released).void_reason, "Expired")
		self.assertEqual(pack_row(last_day).status, "In Sterile Stock")
		self.assertEqual(pack_row(fresh).status, "In Sterile Stock")

	def test_expire_due_runs_at_midnight_after_expiry_day(self):
		pack = self.stocked(expiry_days=0)
		self.assertEqual(storage.expire_due(today()), [])
		self.assertEqual(storage.expire_due(add_days(today(), 1)), [pack.name])

	def test_expire_due_is_idempotent(self):
		self.stocked(expiry_days=-1)
		self.assertEqual(len(storage.expire_due()), 1)
		self.assertEqual(storage.expire_due(), [])

	def test_expire_due_keeps_going_when_one_pack_fails(self):
		first = self.stocked(expiry_days=-1)
		second = self.stocked(expiry_days=-2)
		original = storage._void_pack
		calls = []

		def flaky(pack_name, *args, **kwargs):
			calls.append(pack_name)
			if len(calls) == 1:
				raise frappe.ValidationError("boom")
			return original(pack_name, *args, **kwargs)

		with self.patch_void(flaky):
			names = storage.expire_due()
		self.assertEqual(len(names), 1)
		self.assertEqual(len(calls), 2)
		self.assertCountEqual([pack_row(first).status, pack_row(second).status], ["In Sterile Stock", "Void"])

	def patch_void(self, fn):
		from unittest.mock import patch

		return patch.object(storage, "_void_pack", fn)


class TestOverviewAndFefo(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.shelf = make_sterile_location("Kệ A1")
		self.other = make_sterile_location("Kệ B2")
		self.type_a = make_set_type("T6A001")
		self.type_b = make_set_type("T6B001")

	def stock(self, shelf, set_type, days):
		return stock_pack(shelf, expiry_days=days, set_type=set_type.name)

	def test_overview_counts_by_set_type_and_location(self):
		self.stock(self.shelf, self.type_a, 20)
		self.stock(self.shelf, self.type_a, 5)
		self.stock(self.other, self.type_b, 30)
		data = storage.overview()
		by_type = {row["set_type"]: row for row in data["by_set_type"]}
		self.assertEqual(by_type[self.type_a.name]["count"], 2)
		self.assertEqual(by_type[self.type_a.name]["nearest_expiry"], getdate(add_days(today(), 5)))
		self.assertEqual(by_type[self.type_b.name]["count"], 1)
		by_loc = {row["location"]: row for row in data["by_location"]}
		self.assertEqual(by_loc[self.shelf.name]["count"], 2)
		self.assertEqual(by_loc[self.other.name]["count"], 1)

	@bru("BRU-REP-008")
	def test_overview_lists_packs_expiring_within_seven_days(self):
		soon = self.stock(self.shelf, self.type_a, 7)
		today_pack = self.stock(self.shelf, self.type_a, 0)
		self.stock(self.shelf, self.type_a, 8)
		names = [row["cycle_id"] for row in storage.overview()["expiring"]]
		self.assertCountEqual(names, [soon.name, today_pack.name])
		self.assertEqual(names[0], today_pack.name)  # hết hạn sớm nhất trước
		row = storage.overview()["expiring"][1]
		self.assertEqual((row["days_left"], row["location"]), (7, self.shelf.name))

	@bru("BRU-REP-008")
	def test_fefo_suggest_picks_earliest_expiry_of_set_type(self):
		self.stock(self.shelf, self.type_a, 20)
		earliest = self.stock(self.other, self.type_a, 3)
		self.stock(self.shelf, self.type_b, 1)
		self.assertEqual(storage.fefo_suggest(self.type_a.name)["cycle_id"], earliest.name)
		self.assertIsNone(storage.fefo_suggest("T6ZZZZ"))

	def test_fefo_suggest_ignores_packs_not_in_stock(self):
		self.stock(self.shelf, self.type_a, 20)
		released = make_released_pack(set_type=self.type_a.name, expiry_days=2)  # chưa nhập kho
		self.assertNotEqual(storage.fefo_suggest(self.type_a.name)["cycle_id"], released.name)

	@bru("BRU-REP-008")
	def test_fefo_check_warns_when_nearer_pack_exists(self):
		near = self.stock(self.shelf, self.type_a, 3)
		far = self.stock(self.shelf, self.type_a, 20)
		warning = storage.fefo_check(far.name)
		self.assertEqual(warning["code"], "FEFO_NEARER_PACK")
		self.assertEqual(warning["suggested"]["cycle_id"], near.name)
		self.assertIsNone(storage.fefo_check(near.name))

	def test_return_list_has_expired_and_torn_packs_awaiting_dirty_zone(self):
		torn = self.stock(self.shelf, self.type_a, 20)
		expired = self.stock(self.shelf, self.type_a, -1)
		fine = self.stock(self.shelf, self.type_b, 20)
		storage.mark_damaged(torn.name, "Rách góc", STATION)
		storage.expire_due()
		rows = {row["cycle_id"]: row for row in storage.return_list()}
		self.assertEqual(set(rows) & {torn.name, expired.name, fine.name}, {torn.name, expired.name})
		self.assertEqual(rows[torn.name]["void_reason"], "Torn")
		self.assertEqual(rows[expired.name]["void_reason"], "Expired")
		self.assertEqual(rows[torn.name]["location"], self.shelf.name)
