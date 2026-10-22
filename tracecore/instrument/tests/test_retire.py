"""Ngừng sử dụng dụng cụ (FEAT-014 Task 2; FR-M1-01, UC-01 E3; A-06 I13)."""

import frappe
from frappe.utils import getdate, today

from tracecore.instrument import catalog
from tracecore.tests.factories import make_bom, make_instrument, make_item, make_set_type
from tracecore.tests.utils import IsolatedTestCase

# Instrument liên kết Item (ERPNext), loại bộ liên kết Department; site CI chưa chạy Setup Wizard
test_ignore = ["Item", "User", "Batch", "Department"]


def _audit_updates(code):
	return [
		frappe.parse_json(row.new_value)
		for row in frappe.get_all(
			"Audit Log",
			filters={"ref_doctype": "Instrument", "ref_name": code, "action": "Update"},
			fields=["new_value"],
			order_by="name asc",
		)
	]


class TestRetire(IsolatedTestCase):
	def test_retire_requires_reason_and_confirmation_when_in_bom(self):
		make_instrument("RT-BOM")
		set_type = make_set_type("RTB", set_type_name="Retire tray")
		make_bom(set_type, [("RT-BOM", 1)])

		for blank in ("", "   ", None):
			with self.assertRaises(frappe.ValidationError, msg=repr(blank)):
				catalog.retire("RT-BOM", blank, confirm=True)

		first = catalog.retire("RT-BOM", "Broken jaw")
		self.assertFalse(first["retired"])
		self.assertEqual([row["set_type"] for row in first["boms"]], ["RTB"])
		self.assertEqual(first["boms"][0]["set_type_name"], "Retire tray")
		self.assertEqual(frappe.db.get_value("Instrument", "RT-BOM", "status"), "Active")
		self.assertEqual(_audit_updates("RT-BOM"), [])

		done = catalog.retire("RT-BOM", "  Broken jaw  ", confirm=True)
		self.assertTrue(done["retired"])
		self.assertEqual([row["set_type"] for row in done["boms"]], ["RTB"])
		row = frappe.db.get_value(
			"Instrument", "RT-BOM", ["status", "retired_on", "retired_reason"], as_dict=True
		)
		self.assertEqual(
			(row.status, getdate(row.retired_on), row.retired_reason),
			("Retired", getdate(today()), "Broken jaw"),
		)
		updates = _audit_updates("RT-BOM")
		self.assertEqual(len(updates), 1)
		self.assertEqual(updates[0]["status"], "Retired")
		self.assertEqual(updates[0]["retired_reason"], "Broken jaw")

	def test_retire_without_bom_needs_no_confirmation(self):
		make_instrument("RT-FREE")
		result = catalog.retire("RT-FREE", "Lost")
		self.assertEqual(result, {"retired": True, "boms": []})
		self.assertEqual(frappe.db.get_value("Instrument", "RT-FREE", "status"), "Retired")

	def test_retire_bom_on_old_version_only_needs_no_confirmation(self):
		make_instrument("RT-OLDV")
		set_type = make_set_type("RTO")
		make_bom(set_type, [("RT-OLDV", 1)], version=1)
		make_bom(set_type, [("RT-OTHER", 1)], version=2)
		frappe.db.set_value("Instrument Set Type", set_type.name, "current_bom_version", 2)
		self.assertTrue(catalog.retire("RT-OLDV", "Worn out")["retired"])

	def test_retire_is_one_way(self):
		make_instrument("RT-ONE")
		catalog.retire("RT-ONE", "Broken")
		with self.assertRaises(frappe.ValidationError):
			catalog.retire("RT-ONE", "Again", confirm=True)

		doc = frappe.get_doc("Instrument", "RT-ONE")
		doc.status = "Active"
		with self.assertRaises(frappe.ValidationError):
			doc.save()
		doc.reload()
		doc.status = "Active"
		doc.flags.tc_instrument = True  # kể cả qua cờ của danh mục: không quay lại Đang dùng
		with self.assertRaises(frappe.ValidationError):
			doc.save()
		self.assertEqual(frappe.db.get_value("Instrument", "RT-ONE", "status"), "Retired")

		# dụng cụ đã ngừng vẫn sửa được dữ liệu khác
		doc = frappe.get_doc("Instrument", "RT-ONE")
		doc.manufacturer = "Aesculap"
		doc.save()

	def test_retire_unknown_instrument(self):
		with self.assertRaises(frappe.DoesNotExistError):
			catalog.retire("RT-NONE", "Lost", confirm=True)

	def test_retire_accepts_confirm_as_text(self):
		make_instrument("RT-TXT")
		set_type = make_set_type("RTT")
		make_bom(set_type, [("RT-TXT", 1)])
		self.assertFalse(catalog.retire("RT-TXT", "Worn", confirm="0")["retired"])
		self.assertTrue(catalog.retire("RT-TXT", "Worn", confirm="1")["retired"])
		self.assertEqual(frappe.db.get_value("Instrument", "RT-TXT", "status"), "Retired")

	def test_retire_legacy_stub_without_spaulding_or_methods(self):
		# dụng cụ có trước FEAT-014: thiếu Spaulding và phương pháp vẫn ngừng sử dụng được (Task 2 review)
		make_instrument("RT-STUB")
		frappe.db.set_value("Instrument", "RT-STUB", "spaulding_class", None, update_modified=False)
		frappe.db.delete("Instrument Compatible Method", {"parent": "RT-STUB"})

		self.assertTrue(catalog.retire("RT-STUB", "Legacy stub", confirm=True)["retired"])
		row = frappe.db.get_value("Instrument", "RT-STUB", ["status", "spaulding_class"], as_dict=True)
		self.assertEqual((row.status, row.spaulding_class), ("Retired", None))
		self.assertEqual(_audit_updates("RT-STUB")[-1]["status"], "Retired")
		# lưu thường (không phải ngừng sử dụng) vẫn đòi đủ trường bắt buộc
		doc = frappe.get_doc("Instrument", "RT-STUB")
		doc.manufacturer = "Aesculap"
		with self.assertRaises(frappe.MandatoryError):
			doc.save()

	def test_retire_instrument_whose_item_was_disabled_later(self):
		make_item("VT-RT-ITEM", "Lubricant")
		make_instrument("RT-ITEM", item="VT-RT-ITEM")
		frappe.db.set_value("Item", "VT-RT-ITEM", "disabled", 1)

		self.assertTrue(catalog.retire("RT-ITEM", "Replaced", confirm=True)["retired"])
		self.assertEqual(frappe.db.get_value("Instrument", "RT-ITEM", "status"), "Retired")
		doc = frappe.get_doc("Instrument", "RT-ITEM")
		doc.manufacturer = "Aesculap"
		with self.assertRaises(frappe.ValidationError):
			doc.save()
