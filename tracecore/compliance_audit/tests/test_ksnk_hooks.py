"""M12 đăng ký vào bảng chỉ số KSNK (FEAT-065; FR-M9-26, FR-M9-29; hook ``tracecore_ksnk_todos``,
``tracecore_ic_self_checks``; A-145 Q3, D8)."""

import frappe

from tracecore.compliance_audit import self_checks, todos
from tracecore.compliance_audit.tests.test_schedule import TODAY, ScheduleCase
from tracecore.tests.utils import IsolatedTestCase

CHEMICAL = "IC Chemical Consumption"


class TestAuditTodos(ScheduleCase):
	def test_missing_audits_counted_per_department(self):
		frappe.db.set_value("Audit Schedule", {"active": 1}, "active", 0)
		self.make_schedule(target_count=3)
		self.make_session(self.dept_a)
		items = todos.todos("Administrator", None, TODAY)
		self.assertEqual(items[0]["count"], 5)  # khoa A còn 2, khoa B còn 3
		self.assertTrue(items[0]["link"])
		own = todos.todos("Administrator", self.dept_a, TODAY)
		self.assertEqual((own[0]["count"], own[0]["link"]), (2, ""))

	def test_no_todo_when_target_met(self):
		frappe.db.set_value("Audit Schedule", {"active": 1}, "active", 0)
		self.make_schedule(target_count=1, departments=[self.dept_a])
		self.make_session(self.dept_a)
		self.assertEqual(todos.todos("Administrator", None, TODAY), [])


def _chemical(period):
	doc = frappe.new_doc(CHEMICAL)
	doc.update({"name": f"HC-TEST-{period}", "period": period, "docstatus": 1})
	doc.db_insert()


class TestChemicalSelfCheck(IsolatedTestCase):
	def test_every_ended_quarter_needs_a_record(self):
		self.assertEqual(self_checks.chemical_quarterly(2033, "2033-02-10")["status"], "Needs confirmation")
		self.assertEqual(self_checks.chemical_quarterly(2033, "2033-07-01")["status"], "Not met")
		_chemical("2033-02")
		result = self_checks.chemical_quarterly(2033, "2033-07-01")
		self.assertEqual(result["status"], "Not met")
		self.assertIn("Q2", result["source_ref"])
		_chemical("2033-06")
		self.assertEqual(self_checks.chemical_quarterly(2033, "2033-07-01")["status"], "Met")
		self.assertIn("ic_chemical_quarterly", self_checks.register())
