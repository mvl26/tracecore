"""FEAT-099 (A-158, FR-M9-31): RPC đọc của cổng khoa trên Page tc-flow."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.v1 import flow


def make_department(name, ward=1):
	existing = frappe.db.get_value("Department", {"department_name": name}, "name")
	if existing:
		frappe.db.set_value("Department", existing, {"tc_is_ward": ward, "disabled": 0})
		return existing
	company = frappe.db.get_value("Company", {}, "name")
	doc = frappe.get_doc(
		{"doctype": "Department", "department_name": name, "company": company, "tc_is_ward": ward}
	).insert(ignore_permissions=True)
	return doc.name


class TestFlowApi(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.ward = make_department("TCF Ward A")
		self.other = make_department("TCF Ward B")
		self.office = make_department("TCF Office", ward=0)

	def test_departments_lists_only_wards(self):
		names = [row["name"] for row in flow.departments()["departments"]]
		self.assertIn(self.ward, names)
		self.assertIn(self.other, names)
		self.assertNotIn(self.office, names)
		row = next(row for row in flow.departments()["departments"] if row["name"] == self.ward)
		self.assertEqual(row["label"], "TCF Ward A")

	def test_ward_staff_only_get_their_own_department(self):
		with patch.object(flow, "_scope", return_value=self.ward):
			self.assertEqual([row["name"] for row in flow.departments()["departments"]], [self.ward])
			self.assertTrue(flow.department_stock(self.ward)["ok"])
			with self.assertRaises(frappe.PermissionError):
				flow.department_stock(self.other)

	def test_department_stock_reuses_the_usage_overview(self):
		out = flow.department_stock(self.ward)
		self.assertEqual(out["department"], self.ward)
		self.assertEqual(out["department_name"], "TCF Ward A")
		self.assertEqual(out["at_department"], [])
		self.assertEqual(out["waiting_return"], [])
		# 4 số liệu của màn Bộ tại khoa và cơ số; khoa mới chưa đặt cơ số
		self.assertEqual(
			out["counts"], {"held": 0, "reprocessing": 0, "recall_pending": 0, "waiting_return": 0}
		)
		self.assertIsNone(out["par"])
		# không có trường mã người bệnh
		self.assertNotIn("patient", " ".join(out.keys()))

	def test_unknown_or_non_ward_department_is_rejected(self):
		for value in (None, "", "TCF-NOPE", self.office):
			with self.assertRaises(frappe.DoesNotExistError):
				flow.department_stock(value)

	def test_scope_by_role(self):
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.session.user = "someone@example.com"
		with patch.object(frappe, "get_roles", return_value=["TC R02"]):
			self.assertIsNone(flow._scope())
		with patch.object(frappe, "get_roles", return_value=["TC R08"]):
			with patch.object(flow, "_own_department", return_value=self.ward):
				self.assertEqual(flow._scope(), self.ward)
			with patch.object(flow, "_own_department", return_value=None):
				self.assertEqual(flow._scope(), "-")  # R08 chưa gắn khoa: không thấy khoa nào
		with patch.object(frappe, "get_roles", return_value=["TC R03"]):
			with self.assertRaises(frappe.PermissionError):
				flow._scope()

	def test_par_range_sums_the_department_stock_levels(self):
		rows = [frappe._dict(min_qty=2, max_qty=4), frappe._dict(min_qty=4, max_qty=6)]
		with patch.object(frappe, "get_all", return_value=rows):
			self.assertEqual(flow._par_range(self.ward), {"min": 6, "max": 10})
		with patch.object(frappe, "get_all", return_value=[]):
			self.assertIsNone(flow._par_range(self.ward))

	def test_held_packs_carry_set_id_and_set_type(self):
		overview = {"at_department": [{"cycle_id": "CY-1", "set_name": "A", "expiry": "2026-12-01"}]}
		packs = [frappe._dict(name="CY-1", set_unit="SET-1", set_type="BO-A")]
		with patch.object(frappe, "get_all", return_value=packs):
			rows = flow._held_packs(overview)
		self.assertEqual(rows[0]["set_id"], "SET-1")
		self.assertEqual(rows[0]["set_type"], "BO-A")
		self.assertEqual(flow._held_packs({"at_department": []}), [])
