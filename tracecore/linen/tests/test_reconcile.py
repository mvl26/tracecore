"""Tồn khoa, đối chiếu thu - trả - hủy, báo cáo và cảnh báo cuối ngày (FEAT-035; FR-M3-05, FR-M3-06, .1, .3, .4;
BRU-LIN-004; A-50 G3, G6, G7)."""

import frappe
from frappe.utils import add_days, today

from tracecore.core import notification
from tracecore.linen import reconcile
from tracecore.linen.report.linen_reconciliation import linen_reconciliation as report
from tracecore.tests.factories import (
	linen_line,
	make_department,
	make_linen_collection,
	make_linen_issue,
	make_linen_type,
	make_user,
)
from tracecore.tests.utils import IsolatedTestCase, bru

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


class ReconcileCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		self.department = make_department("Test linen recon ward")
		self.sheet = make_linen_type(
			std_weight_kg=0.5,
			quotas=[{"department": self.department, "min_qty": 20, "max_qty": 100}],
		).name

	def collect(self, qty):
		return make_linen_collection(
			[linen_line(self.sheet, qty, qty / 2)], department=self.department, submit=True
		)

	def issue(self, qty, kind="Return"):
		return make_linen_issue(
			[linen_line(self.sheet, qty, qty / 2)], department=self.department, kind=kind, submit=True
		)

	def row(self, **filters):
		rows = reconcile.rows(self.department, self.sheet, **filters)
		return rows[0] if rows else None


class TestReconcile(ReconcileCase):
	@bru("BRU-LIN-004")
	def test_variance_is_collected_minus_returned_minus_disposed(self):  # FR-M3-06
		self.collect(100)
		self.issue(70)
		self.issue(10, "Dispose")
		row = self.row()
		self.assertEqual(
			(row["collected"], row["returned"], row["disposed"], row["variance"]), (100, 70, 10, 20)
		)
		self.assertEqual((row["variance_kg"], row["variance_pct"]), (10, 20))

	def test_new_stock_does_not_change_variance_but_adds_to_department_stock(self):  # G3
		self.collect(100)
		self.issue(30, "New")
		row = self.row()
		self.assertEqual(row["variance"], 100)
		self.assertEqual(row["stock"], 30 - 100)

	def test_stock_is_returned_plus_new_minus_collected(self):  # G3
		self.collect(100)
		self.issue(90)
		self.issue(25, "New")
		self.assertEqual(self.row()["stock"], 90 + 25 - 100)

	def test_cancelled_and_draft_documents_are_ignored(self):
		self.collect(50)
		self.issue(50).cancel()
		make_linen_issue([linen_line(self.sheet, 5, 2.5)], department=self.department)  # nháp
		self.assertEqual(self.row()["returned"], 0)

	def test_period_filters_by_date_but_stock_accumulates(self):
		self.collect(40)
		tomorrow = add_days(today(), 1)
		row = self.row(from_date=tomorrow, to_date=add_days(today(), 2))
		self.assertEqual(
			(row["collected"], row["stock"]), (0, -40)
		)  # kỳ sau ngày thu: không có phát sinh, tồn cộng dồn
		earlier = reconcile.rows(self.department, self.sheet, add_days(today(), -1), today())
		self.assertEqual(earlier[0]["stock"], -40)

	def test_balance_lists_unreturned_stock_and_quota(self):  # FR-M3-05 hiện ngay đối chiếu
		self.collect(60)
		self.issue(25)
		line = next(row for row in reconcile.balance(self.department) if row["linen_type"] == self.sheet)
		self.assertEqual((line["unreturned"], line["unreturned_kg"]), (35, 17.5))
		self.assertEqual((line["stock"], line["min_qty"], line["max_qty"]), (-35, 20, 100))

	def test_variance_ratio_is_zero_without_collection(self):
		self.assertEqual(reconcile.variance_ratio(reconcile._empty()), 0.0)

	@bru("BRU-LIN-004")
	def test_five_percent_is_not_over_but_more_is(self):  # FR-M3-06.1
		entry = {**reconcile._empty(), "collected": 100, "returned": 95}
		self.assertFalse(reconcile.over_variance(entry))
		entry["returned"] = 94
		self.assertTrue(reconcile.over_variance(entry))


class TestReport(ReconcileCase):
	def run_report(self, **filters):
		return report.execute({"department": self.department, **filters})

	def test_empty_period_shows_a_zero_total_row_not_an_error(self):  # FR-M3-06.4
		columns, rows, _m, _c, summary = self.run_report()
		self.assertEqual(len(rows), 1)
		self.assertEqual(
			(rows[0]["collected"], rows[0]["variance"], rows[0]["variance_pct"], rows[0]["stock"]),
			(0, 0, 0, 0),
		)
		self.assertTrue(columns)
		self.assertEqual(summary[0]["value"], 0)

	def test_report_rows_and_total(self):  # FR-M3-06
		self.collect(100)
		self.issue(80)
		_c, rows, _m, _x, summary = self.run_report()
		self.assertEqual([row["linen_type"] for row in rows[:-1]], [self.sheet])
		self.assertEqual((rows[-1]["collected"], rows[-1]["returned"], rows[-1]["variance"]), (100, 80, 20))
		self.assertEqual(rows[-1]["variance_pct"], 20)
		self.assertEqual(summary[3]["indicator"], "red")

	def test_report_is_restricted_to_linen_roles(self):  # FR-M3-06.3: xuất Excel bằng nút của Script Report
		roles = frappe.get_all("Has Role", filters={"parent": "Linen Reconciliation"}, pluck="role")
		self.assertCountEqual(roles, ["TC R01", "TC R02", "TC R07", "TC R09", "System Manager"])
		frappe.set_user(make_user("linen-recon-r03@example.com", roles=("TC R03",)))
		self.assertFalse(frappe.get_doc("Report", "Linen Reconciliation").is_permitted())


class TestDailyAlert(ReconcileCase):
	def deliveries(self):
		return frappe.get_all(
			"Notification Delivery", filters={"event_code": reconcile.EVENT}, fields=["message", "recipient"]
		)

	def setUp(self):
		super().setUp()
		notification.ensure_default_rules()
		self.r02 = make_user("linen-recon-r02@example.com", roles=("TC R02",))

	@bru("BRU-LIN-004")
	def test_variance_over_five_percent_alerts_r02(self):  # FR-M3-06.1
		self.collect(100)
		self.issue(90)
		self.assertIn(self.department, reconcile.run_daily(add_days(today(), 1)))
		self.assertTrue(any(self.department in row.message for row in self.deliveries()))

	def test_exactly_five_percent_is_quiet(self):
		ward = make_department("Test linen quiet ward")  # khoa không định mức: không cảnh báo tồn
		quiet = make_linen_type(std_weight_kg=0.5).name
		make_linen_collection([linen_line(quiet, 100, 50)], department=ward, submit=True)
		make_linen_issue([linen_line(quiet, 95, 47.5)], department=ward, submit=True)
		self.assertNotIn(ward, reconcile.run_daily(add_days(today(), 1)))

	def test_stock_below_minimum_alerts_even_without_variance(self):
		self.collect(10)
		self.issue(10)  # chênh lệch 0 %, tồn 0 < min 20
		self.assertIn(self.department, reconcile.run_daily(add_days(today(), 1)))

	def test_same_day_is_not_alerted_twice(self):
		self.collect(100)
		self.issue(50)
		first = reconcile.run_daily(add_days(today(), 1))
		self.assertIn(self.department, first)
		self.assertNotIn(self.department, reconcile.run_daily(add_days(today(), 1)))
