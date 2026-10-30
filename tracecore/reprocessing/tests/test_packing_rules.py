from datetime import date, datetime

import frappe
from frappe.utils import getdate, today

from tracecore.core.errors import BlockedError
from tracecore.reprocessing import packing
from tracecore.tests.factories import (
	make_batch,
	make_ci_batch,
	make_item,
	make_pack_type,
	make_set_type,
)
from tracecore.tests.utils import IsolatedTestCase, bru

# Pack (và Set Unit → Instrument Set Type) liên kết Item, Batch, Department, User, Employee của ERPNext/HRMS;
# site CI mới chưa chạy Setup Wizard nên bỏ phụ thuộc này (dữ liệu tạo qua tracecore/tests/factories.py).
test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

PACKED_ON = date(2026, 10, 20)


def _block(case, fn, *args):
	"""Gọi `fn` mong đợi BlockedError; trả Block để kiểm mã/nội dung."""
	with case.assertRaises(BlockedError) as raised:
		fn(*args)
	return raised.exception.block


class TestComputeExpiry(IsolatedTestCase):
	@bru("BRU-REP-009")
	def test_compute_expiry_uses_pack_type_days(self):
		pack_type = make_pack_type("Giấy crepe", 30)
		set_type = make_set_type("EXA")
		self.assertEqual(
			packing.compute_expiry(PACKED_ON, pack_type, set_type.name),
			{"expiry": date(2026, 11, 19), "days": 30, "source": "Pack Type"},
		)

	@bru("BRU-REP-009")
	def test_compute_expiry_set_type_override_shorter(self):
		pack_type = make_pack_type("Giấy crepe", 30)
		shorter = make_set_type("EXB", shelf_life_days=14)
		self.assertEqual(
			packing.compute_expiry(PACKED_ON, pack_type, shorter.name),
			{"expiry": date(2026, 11, 3), "days": 14, "source": "Set Type"},
		)
		longer = make_set_type("EXC", shelf_life_days=60)
		self.assertEqual(
			packing.compute_expiry(PACKED_ON, pack_type, longer.name),
			{"expiry": date(2026, 11, 19), "days": 30, "source": "Pack Type"},
		)

	@bru("BRU-REP-009")
	def test_compute_expiry_equal_override_is_attributed_to_pack_type(self):
		pack_type = make_pack_type("Giấy crepe", 30)
		equal = make_set_type("EXD", shelf_life_days=30)
		self.assertEqual(packing.compute_expiry(PACKED_ON, pack_type, equal.name)["source"], "Pack Type")

	@bru("BRU-REP-009")
	def test_compute_expiry_counts_from_the_packing_date_only(self):
		# Hạn dùng tính theo NGÀY đóng gói (D13): giờ trong ngày không làm đổi kết quả
		pack_type = make_pack_type("Giấy crepe", 30)
		set_type = make_set_type("EXE")
		for packed_on in (datetime(2026, 10, 20, 23, 59), "2026-10-20"):
			result = packing.compute_expiry(packed_on, pack_type, set_type.name)
			self.assertEqual(result["expiry"], date(2026, 11, 19), msg=packed_on)
			self.assertIs(type(result["expiry"]), date)

	@bru("BRU-REP-009")
	def test_pack_type_without_shelf_life_rejected(self):
		set_type = make_set_type("EXF")
		no_days = make_item("VT-GOI-KHONG-HAN", "Packaging")
		zero_days = make_item("VT-GOI-HAN-0", "Packaging", shelf_life_days=0)
		label = make_item("VT-NHAN-KHAC", "Label", method="Steam", shelf_life_days=30)
		disabled = make_pack_type("Gói đã ngừng", 30)
		frappe.db.set_value("Item", disabled, "disabled", 1)
		for item in (no_days.name, zero_days.name, label.name, disabled, "VT-GOI-KHONG-TON-TAI", None, ""):
			block = _block(self, packing.compute_expiry, PACKED_ON, item, set_type.name)
			self.assertEqual(block.code, "PACK_TYPE_INVALID", msg=item)
			self.assertEqual(block.http_status, 422)
			self.assertTrue(block.title and block.reason and block.action, msg=item)

	@bru("BRU-REP-009")
	def test_a_set_type_override_cannot_rescue_a_pack_type_without_shelf_life(self):
		no_days = make_item("VT-GOI-KHONG-HAN-2", "Packaging")
		with_override = make_set_type("EXG", shelf_life_days=14)
		block = _block(self, packing.compute_expiry, PACKED_ON, no_days.name, with_override.name)
		self.assertEqual(block.code, "PACK_TYPE_INVALID")


class TestPackTypes(IsolatedTestCase):
	def test_pack_types_lists_only_packaging_with_shelf_life(self):
		good = make_pack_type("Giấy crepe", 30)
		other = make_pack_type("Tyvek", 180)
		make_item("VT-GOI-KHONG-HAN-3", "Packaging")
		make_item("VT-GOI-HAN-0-3", "Packaging", shelf_life_days=0)
		make_item("VT-NHAN-KHAC-3", "Label", method="Steam", shelf_life_days=30)
		make_item("CI5-LIST", "Chemical Indicator", method="Steam", ci_class="5", shelf_life_days=30)
		disabled = make_pack_type("Gói ngừng dùng", 90)
		frappe.db.set_value("Item", disabled, "disabled", 1)
		set_type = make_set_type("PTA")

		rows = packing.pack_types(set_type.name)

		listed = [row["item"] for row in rows]
		self.assertIn(good, listed)
		self.assertIn(other, listed)
		for excluded in (
			"VT-GOI-KHONG-HAN-3",
			"VT-GOI-HAN-0-3",
			"VT-NHAN-KHAC-3",
			"CI5-LIST",
			disabled,
		):
			self.assertNotIn(excluded, listed)
		by_item = {row["item"]: row for row in rows}
		self.assertEqual(by_item[other], {"item": other, "item_name": other, "shelf_life_days": 180})
		self.assertEqual(len(listed), len(set(listed)))

	def test_pack_types_puts_the_set_type_default_first(self):
		make_pack_type("Giấy crepe", 30)
		default = make_pack_type("Tyvek", 180)
		set_type = make_set_type("PTB", default_pack_type=default)
		rows = packing.pack_types(set_type.name)
		self.assertEqual(rows[0]["item"], default)
		self.assertEqual(rows[0]["shelf_life_days"], 180)
		self.assertEqual([row["item"] for row in rows].count(default), 1)
		self.assertGreater(len(rows), 1)

	def test_pack_types_ignores_an_unusable_default(self):
		unusable = make_item("VT-GOI-KHONG-HAN-4", "Packaging")
		usable = make_pack_type("Giấy crepe", 30)
		# FEAT-015 chặn chọn loại gói không dùng được khi lưu loại bộ; loại gói mặc định thôi dùng được sau khi
		# đã chọn (hoặc dữ liệu cũ) thì vẫn gặp ở T4 → ghi thẳng DB để giả lập
		set_type = make_set_type("PTC")
		frappe.db.set_value("Instrument Set Type", set_type.name, "default_pack_type", unusable.name)
		listed = [row["item"] for row in packing.pack_types(set_type.name)]
		self.assertNotIn(unusable.name, listed)
		self.assertIn(usable, listed)

	def test_pack_types_without_default_is_still_a_list(self):
		make_pack_type("Giấy crepe", 30)
		set_type = make_set_type("PTD")
		# loại bộ có trước FEAT-015 chưa có loại gói mặc định (bắt buộc khi lưu từ FEAT-015) → ghi thẳng DB để giả lập
		frappe.db.set_value("Instrument Set Type", set_type.name, "default_pack_type", None)
		self.assertTrue(packing.pack_types(set_type.name))


class TestResolveCiBatch(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.on_date = getdate(today())

	@bru("BRU-REP-013")
	def test_resolve_ci_batch_cleans_scanner_noise(self):
		lot = make_ci_batch("Steam", "5", expiry_days=30, batch_id="LOT-A")
		self.assertEqual(lot, "LOT-A")
		result = packing.resolve_ci_batch(" ]C1lot-a\r\n", "Steam", self.on_date)
		self.assertEqual(
			result,
			{
				"batch": "LOT-A",
				"item": "CI5-STEAM",
				"expiry_date": frappe.utils.add_days(self.on_date, 30),
				"ci_class": "5",
			},
		)
		# Tab ở cuối và chữ hoa/thường khác nhau vẫn ra đúng một lô
		self.assertEqual(packing.resolve_ci_batch("LOT-a\t", "Steam", self.on_date)["batch"], "LOT-A")

	@bru("BRU-REP-013")
	def test_resolve_ci_batch_accepts_class_5_and_6_for_the_matching_method(self):
		steam6 = make_ci_batch("Steam", "6", batch_id="LOT-S6")
		plasma5 = make_ci_batch("Plasma", "5", batch_id="LOT-P5")
		self.assertEqual(packing.resolve_ci_batch(steam6, "Steam", self.on_date)["ci_class"], "6")
		self.assertEqual(packing.resolve_ci_batch(plasma5, "Plasma", self.on_date)["batch"], plasma5)

	@bru("BRU-REP-013")
	def test_resolve_ci_batch_rejects_wrong_method_class_or_item(self):
		plasma = make_ci_batch("Plasma", "5", batch_id="LOT-PLASMA")
		class4 = make_ci_batch("Steam", "4", batch_id="LOT-CLASS4")
		packaging = make_batch(make_pack_type("Giấy crepe", 30), "LOT-GOI", expiry_date=today())
		make_item("CI-NOMETHOD", "Chemical Indicator", ci_class="5")
		no_method = make_batch("CI-NOMETHOD", "LOT-NOMETHOD", expiry_date=today())
		make_item("CI-NOCLASS", "Chemical Indicator", method="Steam")
		no_class = make_batch("CI-NOCLASS", "LOT-NOCLASS", expiry_date=today())
		cases = {
			"plasma CI for a steam set": plasma,
			"class 4": class4,
			"batch of a packaging item": packaging.name,
			"indicator item without a method": no_method.name,
			"indicator item without a class": no_class.name,
			"unknown lot": "LOT-KHONG-CO",
			"nothing scanned": " \r\n",
		}
		for label, raw in cases.items():
			block = _block(self, packing.resolve_ci_batch, raw, "Steam", self.on_date)
			self.assertEqual(block.code, "CI_LOT_INVALID", msg=label)
			self.assertEqual(block.http_status, 422, msg=label)
			self.assertTrue(block.title and block.reason and block.action, msg=label)

	@bru("BRU-REP-013")
	def test_resolve_ci_batch_rejects_a_lot_without_expiry_date(self):
		make_item("CI5-NOEXP", "Chemical Indicator", method="Steam", ci_class="5")
		make_batch("CI5-NOEXP", "LOT-NOEXP", expiry_date=None)
		block = _block(self, packing.resolve_ci_batch, "LOT-NOEXP", "Steam", self.on_date)
		self.assertEqual(block.code, "CI_LOT_INVALID")
		self.assertIn("LOT-NOEXP", block.reason)

	@bru("BRU-INV-001")
	def test_resolve_ci_batch_rejects_a_disabled_lot(self):
		lot = make_ci_batch("Steam", "5", batch_id="LOT-OFF")
		frappe.db.set_value("Batch", lot, "disabled", 1)
		block = _block(self, packing.resolve_ci_batch, lot, "Steam", self.on_date)
		self.assertEqual(block.code, "CI_LOT_INVALID")

	@bru("BRU-INV-001")
	def test_resolve_ci_batch_rejects_expired(self):
		yesterday = make_ci_batch("Steam", "5", expiry_days=-1)
		block = _block(self, packing.resolve_ci_batch, yesterday, "Steam", self.on_date)
		self.assertEqual(block.code, "CI_LOT_EXPIRED")
		self.assertEqual(block.http_status, 422)
		self.assertTrue(block.title and block.reason and block.action)
		self.assertIn(yesterday, block.reason)

	@bru("BRU-INV-001")
	def test_resolve_ci_batch_expiring_today_is_still_usable(self):
		today_lot = make_ci_batch("Steam", "5", expiry_days=0)
		self.assertEqual(packing.resolve_ci_batch(today_lot, "Steam", self.on_date)["batch"], today_lot)
		# cùng lô nhưng tính theo ngày đóng gói sau hạn thì hết hạn
		with self.assertRaises(BlockedError) as raised:
			packing.resolve_ci_batch(today_lot, "Steam", frappe.utils.add_days(self.on_date, 1))
		self.assertEqual(raised.exception.block.code, "CI_LOT_EXPIRED")


class TestMissingLines(IsolatedTestCase):
	BOM = (
		{"instrument": "KC-01", "instrument_name": "Kẹp 1", "image": None, "qty": 2, "position": 1},
		{"instrument": "KC-02", "instrument_name": "Kẹp 2", "image": None, "qty": 1, "position": 2},
	)

	@bru("BRU-REP-013")
	def test_missing_lines(self):
		bom = [dict(line) for line in self.BOM]
		self.assertEqual(packing.missing_lines(bom, ["KC-01"]), [bom[1]])

	@bru("BRU-REP-013")
	def test_missing_lines_keeps_bom_order_and_ignores_unknown_codes(self):
		bom = [dict(line) for line in self.BOM]
		self.assertEqual(packing.missing_lines(bom, []), bom)
		self.assertEqual(packing.missing_lines(bom, ["KC-02", "KC-99"]), [bom[0]])
		self.assertEqual(packing.missing_lines(bom, ["KC-02", "KC-01"]), [])
		self.assertEqual(packing.missing_lines([], ["KC-01"]), [])
		self.assertEqual(packing.missing_lines(bom, None), bom)
