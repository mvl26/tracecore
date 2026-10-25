"""Patch A-22 `mark_tracecore_wards`: khoa đã có dữ liệu TraceCore được đánh dấu `tc_is_ward`, phòng ban khác giữ nguyên."""

import frappe

from tracecore.patches.v0_1 import mark_tracecore_wards
from tracecore.tests.factories import make_department, make_set_type
from tracecore.tests.utils import IsolatedTestCase

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


class TestMarkTracecoreWards(IsolatedTestCase):
	def test_departments_with_tracecore_data_are_marked_others_are_not(self):
		ward = make_department("Khoa có loại bộ (patch A-22)")
		office = make_department("Phòng hành chính (patch A-22)")
		make_set_type("PW22", department=ward)
		frappe.db.set_value("Department", ward, "tc_is_ward", 0)
		frappe.db.set_value("Department", office, "tc_is_ward", 0)
		mark_tracecore_wards.execute()
		self.assertEqual(frappe.db.get_value("Department", ward, "tc_is_ward"), 1)
		self.assertEqual(frappe.db.get_value("Department", office, "tc_is_ward"), 0)
		mark_tracecore_wards.execute()  # chạy lại không lỗi, không đổi
		self.assertEqual(frappe.db.get_value("Department", office, "tc_is_ward"), 0)

	def test_patch_creates_the_field_from_the_fixture_definition(self):
		# migrate chạy patch trước khi đồng bộ fixtures: patch tự tạo field theo đúng định nghĩa fixture
		field = mark_tracecore_wards._field_definition()
		self.assertEqual(
			(field["fieldname"], field["fieldtype"], field["default"]), ("tc_is_ward", "Check", "0")
		)
		self.assertNotIn("name", field)
