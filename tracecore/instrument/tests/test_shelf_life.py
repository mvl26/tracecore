"""Hạn lưu loại gói / loại bộ (FEAT-015 Task 1; FR-M1-03.4, FR-M1-03.5, BRU-REP-009, A-02 D4)."""

import frappe
from frappe.utils import getdate, nowdate

from tracecore.core.errors import BlockedError
from tracecore.instrument import shelf_life
from tracecore.reprocessing import packing  # test được đối chiếu với M2 (lint R1 bỏ qua tests/)
from tracecore.tests.factories import make_department, make_item, make_pack_type, make_set_type
from tracecore.tests.utils import IsolatedTestCase, bru

# Instrument Set Type liên kết Department, Item của ERPNext; site CI mới chưa chạy Setup Wizard nên bỏ phụ thuộc
# tạo bản ghi test tự động (dữ liệu tạo qua tracecore/tests/factories.py).
test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


def _set_type_doc(type_code, **values):
	doc = {
		"doctype": "Instrument Set Type",
		"type_code": type_code,
		"set_type_name": f"Set {type_code}",
		"method": "Steam",
		"department": make_department(),
		"default_pack_type": make_pack_type("Giấy crepe", 30),
	}
	doc.update(values)
	doc = frappe.get_doc(doc)
	# loại bộ chỉ tạo qua bom_versions (Task 2); test luật loại gói / hạn lưu ghi như dịch vụ BOM
	doc.flags.tc_bom = True
	return doc


class TestShelfLife(IsolatedTestCase):
	def test_pack_type_days_criteria(self):
		good = make_pack_type("Giấy crepe", 30)
		zero = make_item("VT-GOI-SL-0", "Packaging", shelf_life_days=0).name
		blank = make_item("VT-GOI-SL-BLANK", "Packaging").name
		label = make_item("VT-NHAN-SL", "Label", method="Steam", shelf_life_days=30).name
		disabled = make_pack_type("Gói tắt SL", 30, disabled=1)
		self.assertEqual(shelf_life.pack_type_days(good), 30)
		for item in (zero, blank, label, disabled, "VT-GOI-KHONG-TON-TAI", None, ""):
			self.assertIsNone(shelf_life.pack_type_days(item), msg=item)

	@bru("BRU-REP-009")
	def test_pack_type_without_shelf_life_not_selectable(self):
		# FR-M1-03.5: loại gói chưa có hạn lưu (0/trống), không phải Packaging hoặc đã ngừng dùng → không chọn được
		zero = make_item("VT-GOI-SL-0", "Packaging", shelf_life_days=0).name
		blank = make_item("VT-GOI-SL-BLANK", "Packaging").name
		label = make_item("VT-NHAN-SL", "Label", method="Steam", shelf_life_days=30).name
		disabled = make_pack_type("Gói tắt SL", 30, disabled=1)
		for index, item in enumerate((zero, blank, label, disabled)):
			with self.assertRaises(frappe.ValidationError, msg=item):
				_set_type_doc(f"PTX{index}", default_pack_type=item).insert()
			self.assertFalse(frappe.db.exists("Instrument Set Type", f"PTX{index}"))

		# thông báo đã dịch, nêu mã loại gói
		frappe.local.lang = "vi"
		try:
			with self.assertRaises(frappe.ValidationError) as raised:
				_set_type_doc("PTXVI", default_pack_type=zero).insert()
		finally:
			frappe.local.lang = "en"
		self.assertIn(zero, str(raised.exception))
		self.assertIn("không chọn được", str(raised.exception))

		ok = _set_type_doc("PTOK", default_pack_type=make_pack_type("Giấy crepe", 30)).insert()
		self.assertEqual(ok.default_pack_type, make_pack_type("Giấy crepe", 30))

		# đổi sang loại gói không dùng được trên loại bộ đã có cũng bị chặn
		ok.default_pack_type = zero
		with self.assertRaises(frappe.ValidationError):
			ok.save()

	@bru("BRU-REP-009")
	def test_override_only_shorter_than_pack_type(self):
		# FR-M1-03.4: hạn lưu mặc định từ loại gói, loại bộ chỉ ghi đè bằng giá trị ngắn hơn
		pack = make_pack_type("Giấy crepe", 30)
		shorter = _set_type_doc("OVR20", shelf_life_days=20).insert()
		self.assertEqual(
			shelf_life.effective(shorter),
			{"days": 20, "source": "Set Type", "pack_type_days": 30, "override": 20},
		)
		self.assertEqual(shelf_life.effective(shorter.name)["days"], 20)

		for index, days in enumerate((30, 45, -1)):
			with self.assertRaises(frappe.ValidationError, msg=days):
				_set_type_doc(f"OVB{index}", shelf_life_days=days).insert()
		with self.assertRaises(frappe.ValidationError) as raised:
			_set_type_doc("OVBMSG", shelf_life_days=30).insert()
		self.assertIn("30", str(raised.exception))

		default = _set_type_doc("OVR0", shelf_life_days=0).insert()
		self.assertEqual(
			shelf_life.effective(default),
			{"days": 30, "source": "Pack Type", "pack_type_days": 30, "override": 0},
		)

		# sửa ghi đè trên loại bộ đã có cũng theo cùng luật
		shorter.shelf_life_days = 30
		with self.assertRaises(frappe.ValidationError):
			shorter.save()
		self.assertEqual(frappe.db.get_value("Instrument Set Type", "OVR20", "shelf_life_days"), 20)

		# loại gói khác (truyền vào) vẫn theo công thức min (D4)
		longer = make_pack_type("Tyvek", 180)
		self.assertEqual(shelf_life.effective(shorter.name, longer)["days"], 20)
		self.assertEqual(shelf_life.effective(default.name, longer)["source"], "Pack Type")
		self.assertEqual(shelf_life.effective(default.name, pack)["days"], 30)

	@bru("BRU-REP-009")
	def test_no_hard_coded_default_shelf_life(self):
		set_type = _set_type_doc("NOHC").insert()
		# mọi loại gói thôi dùng được → không có lựa chọn, không bịa số ngày
		frappe.db.set_value("Item", {"tc_item_group_cssd": "Packaging"}, "disabled", 1)
		self.assertEqual(shelf_life.usable_pack_types(), [])
		self.assertEqual(
			shelf_life.effective(set_type.name),
			{"days": None, "source": None, "pack_type_days": None, "override": 0},
		)
		self.assertIsNone(shelf_life.effective(set_type.name, None)["days"])

	def test_shelf_life_rules_match_packing(self):
		# Cùng tiêu chí với M2 (packing._pack_type_days / pack_types / compute_expiry), trên 6 Item mẫu
		good = make_pack_type("Giấy crepe", 30)
		tyvek = make_pack_type("Tyvek", 180)
		blank = make_item("VT-GOI-SLM-BLANK", "Packaging").name
		zero = make_item("VT-GOI-SLM-0", "Packaging", shelf_life_days=0).name
		label = make_item("VT-NHAN-SLM", "Label", method="Steam", shelf_life_days=30).name
		disabled = make_pack_type("Gói tắt SLM", 90, disabled=1)
		set_type = make_set_type("SLM", default_pack_type=tyvek, shelf_life_days=14)

		def as_set(rows):
			return {tuple(sorted(row.items())) for row in rows}

		self.assertEqual(as_set(shelf_life.usable_pack_types()), as_set(packing.pack_types(set_type.name)))
		for row in shelf_life.usable_pack_types():
			self.assertEqual(set(row), {"item", "item_name", "shelf_life_days"})

		today = getdate(nowdate())
		for override in (0, 14, 29):
			frappe.db.set_value("Instrument Set Type", set_type.name, "shelf_life_days", override)
			for item in (good, tyvek):
				expected = packing.compute_expiry(today, item, set_type.name)
				result = shelf_life.effective(set_type.name, item)
				self.assertEqual(
					(result["days"], result["source"]),
					(expected["days"], expected["source"]),
					(override, item),
				)
			for item in (blank, zero, label, disabled):
				with self.assertRaises(BlockedError):
					packing.compute_expiry(today, item, set_type.name)
				self.assertIsNone(shelf_life.effective(set_type.name, item)["days"], msg=item)
