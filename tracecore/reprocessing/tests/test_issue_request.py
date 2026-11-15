"""Khoa gửi đề nghị cấp bộ dụng cụ (FEAT-101, A-161; FR-M2-27 .1-.3)."""

import frappe
from frappe.utils import add_to_date, now_datetime, today

from tracecore.reprocessing import issue_request
from tracecore.reprocessing.tests.test_usage import issue
from tracecore.tests.factories import make_department, make_stocked_pack
from tracecore.tests.utils import IsolatedTestCase

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


def later(hours=2):
	return str(add_to_date(now_datetime(), hours=hours).replace(microsecond=0))


class IssueRequestCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.dept = make_department("Khoa đề nghị cấp")
		self.held = issue(make_stocked_pack(), self.dept)
		self.set_type = self.held.set_type

	def rejected(self, *args, **kwargs):
		with self.assertRaises(issue_request.RequestRejected) as raised:
			issue_request.create(*args, **kwargs)
		return raised.exception


class TestOptions(IssueRequestCase):
	def test_set_types_carry_department_stock_and_par(self):
		rows = {row["set_type"]: row for row in issue_request.options(self.dept)}
		row = rows[self.set_type]
		self.assertEqual(row["stock"], 1)
		self.assertTrue(row["set_name"])
		for key in ("min", "max", "available"):
			self.assertIn(key, row)


class TestCreate(IssueRequestCase):
	def test_request_is_recorded_and_changes_no_pack(self):
		before = frappe.db.get_value("Pack", self.held.name, "status")
		needed = later()
		out = issue_request.create(self.dept, self.set_type, "2", needed)
		doc = frappe.get_doc("Set Issue Request", out["request"])
		self.assertEqual(doc.docstatus, 1)
		self.assertEqual((doc.department, doc.set_type, doc.qty), (self.dept, self.set_type, 2))
		self.assertEqual(str(doc.needed_by), needed)
		self.assertEqual(doc.stock_at_request, 1)
		self.assertEqual(doc.requested_by, frappe.session.user)
		self.assertTrue(doc.requested_at and doc.set_name)
		# đề nghị chỉ là thông báo: không giữ chỗ, không đổi trạng thái gói
		self.assertEqual(frappe.db.get_value("Pack", self.held.name, "status"), before)

	def test_rejects_bad_set_type_quantity_and_time(self):
		self.assertEqual(self.rejected(self.dept, "NOPE-TYPE", 1, later()).code, "SET_TYPE_INVALID")
		self.assertEqual(self.rejected(self.dept, None, 1, later()).code, "SET_TYPE_INVALID")
		for qty in (0, 100, "1.5", "abc", None, -2):
			self.assertEqual(self.rejected(self.dept, self.set_type, qty, later()).code, "QTY_INVALID")
		for value in (None, "", "not a date"):
			self.assertEqual(self.rejected(self.dept, self.set_type, 1, value).code, "NEEDED_BY_INVALID")
		error = self.rejected(self.dept, self.set_type, 1, later(hours=-3))
		self.assertEqual(error.code, "NEEDED_BY_PAST")
		# kết quả → lý do → hành động
		self.assertTrue(error.title and error.reason and error.action)
		self.assertEqual(frappe.db.count("Set Issue Request", {"department": self.dept}), 0)

	def test_request_cannot_be_made_or_cancelled_outside_the_service(self):
		doc = frappe.get_doc(
			{
				"doctype": "Set Issue Request",
				"department": self.dept,
				"set_type": self.set_type,
				"qty": 1,
				"needed_by": later(),
			}
		)
		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)
		out = issue_request.create(self.dept, self.set_type, 1, later())
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc("Set Issue Request", out["request"]).cancel()


class TestRequestsToday(IssueRequestCase):
	def test_status_follows_issue_notes_after_the_request(self):
		out = issue_request.create(self.dept, self.set_type, 2, later())
		row = issue_request.requests_on(self.dept, today())[0]
		self.assertEqual(row["request"], out["request"])
		# gói khoa đã giữ từ trước không tính là đã cấp cho đề nghị này
		self.assertEqual((row["qty"], row["issued_count"], row["status"]), (2, 0, "Waiting"))
		self.assertTrue(row["set_name"] and row["needed_by"] and row["requested_by_name"])
		issue(make_stocked_pack(set_type=self.set_type), self.dept)
		row = issue_request.requests_on(self.dept, today())[0]
		self.assertEqual((row["issued_count"], row["status"]), (1, "Partly issued"))
		issue(make_stocked_pack(set_type=self.set_type), self.dept)
		issue(make_stocked_pack(set_type=self.set_type), self.dept)
		row = issue_request.requests_on(self.dept, today())[0]
		self.assertEqual((row["issued_count"], row["status"]), (2, "Issued"))

	def test_only_requests_of_the_department_and_day(self):
		issue_request.create(self.dept, self.set_type, 1, later())
		self.assertEqual(issue_request.requests_on(make_department("Khoa khác đề nghị cấp"), today()), [])
		self.assertEqual(issue_request.requests_on(self.dept, "2020-01-01"), [])
