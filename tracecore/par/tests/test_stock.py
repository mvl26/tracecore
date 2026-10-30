"""Cơ số tồn khoa khi cấp phát T7 (FEAT-026 C5, FR-M2-16, FR-M8-02, BRU-PAR-005): hook `tracecore_issue_par_check`."""

import frappe

from tracecore.par import stock
from tracecore.tests.factories import make_department, make_par_level, make_set_type
from tracecore.tests.utils import IsolatedTestCase, bru

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


class TestIssuePar(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.dept = make_department("Khoa test cơ số")
		self.set_type = make_set_type("PSK").name

	def configure(self, min_qty=2, max_qty=5, **values):
		values.setdefault("is_active", 1)
		return make_par_level(
			"Instrument Set Type",
			self.set_type,
			par_kind="Department Stock",
			department=self.dept,
			min_qty=min_qty,
			max_qty=max_qty,
			**values,
		)

	def check(self, stock_qty, adding):
		return stock.issue_par(
			{"department": self.dept, "set_type": self.set_type, "stock": stock_qty, "adding": adding}
		)

	@bru("BRU-PAR-005")
	def test_within_min_max_is_ok(self):
		self.configure()
		result = self.check(2, 2)
		self.assertEqual(result["state"], "ok")
		self.assertEqual((result["min"], result["max"], result["after"]), (2, 5, 4))
		self.assertEqual(result["suggest"], 0)

	@bru("BRU-PAR-005")
	def test_over_max_needs_approval(self):
		# FR-M2-16.1: tồn khoa + số cấp > tối đa → cảnh báo, R02 duyệt
		self.configure()
		result = self.check(4, 2)
		self.assertEqual(result["state"], "over")
		self.assertEqual(result["after"], 6)
		self.assertEqual(self.check(3, 2)["state"], "ok")  # đúng bằng tối đa vẫn được

	@bru("BRU-PAR-005")
	def test_emergency_department_may_exceed_within_percent(self):
		# FR-M2-16.3: khoa cấp cứu cho phép vượt 20 % → tối đa 10 thành 12, không cần duyệt
		self.configure(min_qty=2, max_qty=10, over_percent=20, is_emergency_dept=1)
		within = self.check(10, 2)
		self.assertEqual(within["state"], "over_allowed")
		self.assertEqual(within["limit"], 12)
		self.assertEqual(self.check(10, 3)["state"], "over")

	@bru("BRU-PAR-005")
	def test_suggests_supply_when_stock_below_min(self):
		# FR-M2-16.2: tồn khoa < tối thiểu → gợi ý cấp thêm đủ tối thiểu
		self.configure(min_qty=4, max_qty=8)
		result = self.check(1, 1)
		self.assertEqual(result["state"], "ok")
		self.assertEqual(result["suggest"], 2)
		self.assertEqual(self.check(1, 3)["suggest"], 0)
		self.assertEqual(self.check(4, 0)["suggest"], 0)

	@bru("BRU-PAR-005")
	def test_unconfigured_department_is_reported(self):
		# FR-M2-16.4: khoa chưa có cơ số → cho cấp, cảnh báo
		result = self.check(0, 3)
		self.assertEqual(result["state"], "unconfigured")
		self.assertIsNone(result["max"])

	def test_inactive_par_level_counts_as_unconfigured(self):
		self.configure(is_active=0)
		self.assertEqual(self.check(0, 1)["state"], "unconfigured")

	def test_other_department_par_level_is_ignored(self):
		other = make_department("Khoa test khác")
		make_par_level(
			"Instrument Set Type",
			self.set_type,
			par_kind="Department Stock",
			department=other,
			min_qty=0,
			max_qty=1,
			is_active=1,
		)
		self.assertEqual(self.check(0, 3)["state"], "unconfigured")

	def test_hook_is_registered(self):
		self.assertIn("tracecore.par.stock.issue_par", frappe.get_hooks("tracecore_issue_par_check"))
