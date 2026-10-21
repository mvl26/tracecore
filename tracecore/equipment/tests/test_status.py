import frappe

from tracecore.equipment import status
from tracecore.tests.factories import make_equipment
from tracecore.tests.utils import IsolatedTestCase


class TestStatus(IsolatedTestCase):
	def test_set_status_changes_status_and_flag_does_not_leak(self):
		doc = make_equipment()
		status.set_status(doc.name, "Repair")
		self.assertEqual(frappe.db.get_value("Equipment", doc.name, "status"), "Repair")
		fresh = frappe.get_doc("Equipment", doc.name)
		self.assertFalse(fresh.flags.tc_equipment)
		fresh.status = "Ready"
		with self.assertRaises(frappe.ValidationError):
			fresh.save()

	def test_same_status_is_noop(self):
		doc = make_equipment()
		filters = {"ref_doctype": "Equipment", "ref_name": doc.name}
		before = frappe.db.count("Audit Log", filters)
		status.set_status(doc.name, "Ready")
		self.assertEqual(frappe.db.count("Audit Log", filters), before)

	def test_statuses_constant(self):
		self.assertEqual(status.STATUSES, ("Ready", "Locked", "Repair", "Retired"))

	def test_retired_disables_equipment_code_with_reason(self):
		doc = make_equipment(serial="SN-STATUS-CODE")
		status.set_status(doc.name, "Retired", "  Thanh lý  ")
		row = frappe.db.get_value("Code Registry", doc.name, ["status", "disabled_reason"], as_dict=True)
		self.assertEqual((row.status, row.disabled_reason), ("Disabled", "Thanh lý"))


class TestDisableRetiredCodesPatch(IsolatedTestCase):
	"""Patch post_model_sync: máy đã Retired trước FEAT-005 (mã TB- còn Active) → mã Disabled (A-05 R4)."""

	def _legacy_retired(self, name, serial, reason):
		# dữ liệu cũ: Retired qua FEAT-038 khi chưa có bước vô hiệu mã
		doc = make_equipment(name=name, serial=serial)
		frappe.db.set_value("Equipment", doc.name, {"status": "Retired", "retired_reason": reason})
		self.assertEqual(frappe.db.get_value("Code Registry", doc.name, "status"), "Active")
		return doc.name

	def test_patch_disables_codes_of_retired_equipment_idempotently(self):
		from tracecore.patches.v0_1 import disable_retired_equipment_codes as patch

		with_reason = self._legacy_retired("Máy cũ có lý do", "SN-PATCH-1", "Hết khấu hao")
		without_reason = self._legacy_retired("Máy cũ không lý do", "SN-PATCH-2", None)
		ready = make_equipment(name="Máy còn dùng", serial="SN-PATCH-3").name
		unregistered = self._legacy_retired("Máy chưa có sổ", "SN-PATCH-4", "Cũ")
		frappe.db.delete("Code Registry", {"name": unregistered})

		patch.execute()

		row = frappe.db.get_value("Code Registry", with_reason, ["status", "disabled_reason"], as_dict=True)
		self.assertEqual((row.status, row.disabled_reason), ("Disabled", "Hết khấu hao"))
		row = frappe.db.get_value(
			"Code Registry", without_reason, ["status", "disabled_reason"], as_dict=True
		)
		self.assertEqual(row.status, "Disabled")
		self.assertEqual(row.disabled_reason, "Equipment retired before its QR code was disabled")
		self.assertEqual(frappe.db.get_value("Code Registry", ready, "status"), "Active")
		self.assertFalse(frappe.db.exists("Code Registry", unregistered))

		# chạy lại: không lỗi, không đổi ngày/lý do đã ghi
		disabled_on = frappe.db.get_value("Code Registry", with_reason, "disabled_on")
		patch.execute()
		self.assertEqual(frappe.db.get_value("Code Registry", with_reason, "disabled_on"), disabled_on)

	def test_patch_is_registered_post_model_sync(self):
		patches = open(frappe.get_app_path("tracecore", "patches.txt"), encoding="utf-8").read()
		post = patches.split("[post_model_sync]", 1)[1]
		self.assertIn("tracecore.patches.v0_1.disable_retired_equipment_codes", post)
