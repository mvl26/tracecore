"""Script Report "Đào tạo KSNK theo khoa" (FEAT-059 AC-8; FR-M11-09; UC-42 bước 2, E3)."""

import frappe
from frappe.utils import today

from tracecore.infection_program import training
from tracecore.infection_program.report.ic_training_by_department import ic_training_by_department as report
from tracecore.infection_program.tests import ic_fixtures as fx
from tracecore.infection_program.tests import training_fixtures as tf
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase


class TestICTrainingByDepartment(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(setattr, frappe.local, "lang", "en")
		frappe.local.lang = "en"
		self.dept = factories.make_department("KSNK BC Đào tạo")
		staff = [fx.employee(f"BC {index}", self.dept) for index in range(4)]
		tf.trained(staff[:3], training.BASIC)

	def _run(self, **filters):
		return report.execute(frappe._dict({"year": int(today()[:4]), **filters}))[:2]

	def test_meta(self):
		meta = frappe.get_doc("Report", "IC Training by Department")
		self.assertEqual((meta.report_type, meta.module), ("Script Report", "Infection Program"))
		roles = {row.role for row in meta.roles}
		self.assertTrue({"TC R01", "TC R02", "TC R10", "TC R11", "TC R13"} <= roles)

	def test_department_row_and_total(self):
		frappe.local.lang = "vi"
		columns, data = self._run(department=self.dept)
		self.assertEqual(
			[column["fieldname"] for column in columns],
			["department", "employees", "trained", "rate", "status", "untrained", "status_code"],
		)
		row, total = data
		self.assertEqual((row["employees"], row["trained"], row["untrained"]), (4, 3, 1))
		self.assertEqual(row["rate"], 75.0)
		self.assertEqual(row["status_code"], "none")
		self.assertEqual(row["status"], "Chưa có mục tiêu")
		self.assertEqual(total["department"], "Toàn viện")
		self.assertEqual(total["employees"], 4)

	def test_department_without_staff_is_not_calculated(self):
		empty = factories.make_department("KSNK BC Trống")
		row, total = self._run(department=empty)[1]
		self.assertEqual((row["employees"], row["status_code"], row["rate"]), (0, "na", None))
		self.assertEqual(row["status"], "Not calculated")
		self.assertEqual(total["status_code"], "na")

	def test_year_defaults_to_current(self):
		data = report.execute(frappe._dict({"department": self.dept}))[1]
		self.assertEqual(data[0]["trained"], 3)
