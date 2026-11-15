"""Lệnh thu hồi nhìn từ khoa (FEAT-101, A-161; FR-M9-32, FR-M2-20)."""

import frappe
from frappe.utils import now_datetime

from tracecore.reprocessing import department_recall
from tracecore.tests.factories import make_department
from tracecore.tests.utils import IsolatedTestCase

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


def make_recall(lines, docstatus=0, status="Open", reason="BI positive"):
	"""Lệnh thu hồi ghi thẳng (không chạy cả luồng mẻ tiệt khuẩn): đủ cho phần đọc của cổng khoa."""
	order = frappe.new_doc("Recall Order")
	order.update(
		{
			"name": "TH-TEST-" + frappe.generate_hash(length=8),
			"docstatus": docstatus,
			"status": status,
			"reason": reason,
			"trigger": "BI Positive",
			"opened_at": now_datetime(),
		}
	)
	order.db_insert()
	for idx, line in enumerate(lines, 1):
		row = frappe.new_doc("Recall Order Pack")
		row.update(
			{
				"name": frappe.generate_hash(length=10),
				"parent": order.name,
				"parenttype": "Recall Order",
				"parentfield": "packs",
				"idx": idx,
				"line_status": "Pending",
				**line,
			}
		)
		row.db_insert()
	return order.name


class TestDepartmentRecall(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.dept = make_department("Khoa thu hồi A")
		self.other = make_department("Khoa thu hồi B")

	def test_open_orders_list_only_the_lines_of_the_department(self):
		recall = make_recall(
			[
				{
					"pack": "CY-R-1",
					"department": self.dept,
					"action": "Return from Department",
					"status_at_recall": "Issued",
				},
				{
					"pack": "CY-R-2",
					"department": self.dept,
					"action": "Notify Physician",
					"status_at_recall": "Used",
					"patient_code_masked": "BN09****78",
				},
				{"pack": "CY-R-3", "department": self.other, "action": "Return from Department"},
				{"pack": "CY-R-4", "department": None, "action": "Lock in Stock"},
			]
		)
		orders = department_recall.open_orders(self.dept)
		self.assertEqual([order["recall"] for order in orders], [recall])
		self.assertEqual(orders[0]["reason"], "BI positive")
		lines = orders[0]["lines"]
		self.assertEqual([line["cycle_id"] for line in lines], ["CY-R-1", "CY-R-2"])
		self.assertEqual(lines[1]["patient_code_masked"], "BN09****78")
		self.assertFalse(lines[0]["confirmed"])
		# không trả trường nào chứa mã bệnh nhân đầy đủ
		self.assertNotIn("patient_code", {key for line in lines for key in line} - {"patient_code_masked"})
		self.assertEqual(department_recall.pending_count(self.dept), 2)
		self.assertEqual(department_recall.pending_count(self.other), 1)

	def test_confirmed_lines_stay_listed_but_are_not_pending(self):
		make_recall(
			[
				{
					"pack": "CY-R-5",
					"department": self.dept,
					"action": "Return from Department",
					"line_status": "Confirmed",
					"confirmed_by": "Administrator",
					"confirmed_at": now_datetime(),
				},
				{"pack": "CY-R-6", "department": self.dept, "action": "Return from Department"},
			]
		)
		lines = department_recall.open_orders(self.dept)[0]["lines"]
		self.assertEqual([line["confirmed"] for line in lines], [True, False])
		self.assertEqual(lines[0]["confirmed_by"], "Administrator")
		self.assertEqual(department_recall.pending_count(self.dept), 1)

	def test_closed_orders_are_left_out(self):
		make_recall([{"pack": "CY-R-7", "department": self.dept}], docstatus=1, status="Closed")
		self.assertEqual(department_recall.open_orders(self.dept), [])
		self.assertEqual(department_recall.pending_count(self.dept), 0)
