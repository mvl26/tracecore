"""Usage Record (FEAT-027 Task 1; FR-M2-17, FR-M2-17.1; BRU-ID-003; NFR-SEC-02): chỉ dịch vụ T8 ghi, tên US-YYYY-#####,
mã bệnh nhân mã hóa và che 4 ký tự giữa, không hủy, quyền DT-USAGE."""

import re

import frappe
from frappe.utils import now_datetime

from tracecore.reprocessing.doctype.usage_record.usage_record import mask_patient_code
from tracecore.tests.factories import make_department, make_stocked_pack
from tracecore.tests.utils import IsolatedTestCase, assert_permission_matrix, bru

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


def make_usage(pack, **fields):
	doc = frappe.get_doc(
		{
			"doctype": "Usage Record",
			"pack": pack.name,
			"set_unit": pack.set_unit,
			"department": make_department(),
			"scanned_by_user": frappe.session.user,
			"station": "TR-008",
			"used_at": now_datetime(),
			"patient_code": "BN12345678",
			**fields,
		}
	)
	doc.flags.tc_usage = True
	return doc.insert(ignore_permissions=True)


class TestUsageRecord(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.pack = make_stocked_pack()

	def test_name_follows_usage_series(self):
		record = make_usage(self.pack)
		self.assertRegex(record.name, re.compile(rf"^US-{now_datetime().year}-\d{{5}}$"))

	@bru("BRU-ID-003")
	def test_only_usage_service_creates_and_edits(self):
		doc = frappe.get_doc(
			{"doctype": "Usage Record", "pack": self.pack.name, "department": make_department()}
		)
		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)
		record = frappe.get_doc("Usage Record", make_usage(self.pack).name)  # không mang cờ của dịch vụ
		record.room = "P1"
		with self.assertRaises(frappe.ValidationError):
			record.save(ignore_permissions=True)

	def test_cannot_cancel_cycle_id_never_reactivates(self):
		record = make_usage(self.pack)
		record.flags.tc_usage = True
		record.submit()
		with self.assertRaises(frappe.ValidationError):
			record.cancel()

	def test_one_usage_record_per_pack(self):
		make_usage(self.pack)
		with self.assertRaises(frappe.ValidationError):
			make_usage(self.pack)

	def test_mask_hides_four_middle_characters(self):
		self.assertEqual(mask_patient_code("BN12345678"), "BN1****678")
		self.assertEqual(mask_patient_code("1234567"), "1****67")
		self.assertEqual(mask_patient_code("12345"), "****5")
		self.assertEqual(mask_patient_code("AB12"), "****")
		self.assertEqual(mask_patient_code("AB"), "**")
		self.assertEqual(mask_patient_code(None), "")
		self.assertEqual(mask_patient_code(""), "")

	def test_patient_code_is_not_stored_in_clear(self):
		record = make_usage(self.pack, patient_code="BN12345678")
		self.assertNotEqual(frappe.db.get_value("Usage Record", record.name, "patient_code"), "BN12345678")
		stored = frappe.db.sql(
			"select `password` from `__Auth` where doctype = 'Usage Record' and name = %s and fieldname = 'patient_code'",
			record.name,
		)
		self.assertTrue(stored)
		self.assertNotIn("BN12345678", stored[0][0])
		self.assertEqual(frappe.get_doc("Usage Record", record.name).patient_code_masked, "BN1****678")

	def test_permissions_match_matrix(self):
		assert_permission_matrix(self, "Usage Record")
