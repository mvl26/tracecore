"""M11 đăng ký vào bảng chỉ số KSNK (FEAT-065; FR-M9-26, FR-M9-29; hook ``tracecore_ksnk_todos``,
``tracecore_ic_self_checks``; A-145 Q3, D8)."""

import datetime

from tracecore.infection_program import self_checks, todos
from tracecore.infection_program.tests import ic_fixtures as fx
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase

YEAR = 2032
ON = datetime.date(YEAR, 6, 1)


class TestIcProgramHooks(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		fx.clear_plans(YEAR)
		self.dept = factories.make_department("KSNK Hook Plan A")
		self.other = factories.make_department("KSNK Hook Plan B")
		owner = fx.employee("Hook Plan Owner")
		self.doc = fx.plan(
			YEAR,
			activities=[
				{
					"activity": "Late training",
					"responsible": owner,
					"due_date": "2032-05-01",
					"department": self.dept,
				},
				{"activity": "Late audit", "responsible": owner, "due_date": "2032-05-20"},
				{"activity": "Done", "responsible": owner, "due_date": "2032-05-01", "status": "Completed"},
				{"activity": "Later", "responsible": owner, "due_date": "2032-07-01"},
			],
		)

	def test_draft_plan_has_no_todo_and_is_not_approved(self):
		self.assertEqual(todos.todos("Administrator", None, ON), [])
		self.assertEqual(self_checks.plan_approved(YEAR)["status"], "Not met")

	def test_overdue_activities_of_approved_plan(self):
		doc = fx.approve(self.doc, fx.user("R13", prefix="ksnk-hook"))
		items = todos.todos("Administrator", None, ON)
		self.assertEqual(items[0]["count"], 2)
		self.assertIn("Late training", items[0]["detail"])
		self.assertTrue(items[0]["link"])
		own = todos.todos("Administrator", self.dept, ON)
		self.assertEqual((own[0]["count"], own[0]["link"]), (1, ""))
		self.assertEqual(todos.todos("Administrator", self.other, ON), [])
		self.assertEqual(self_checks.plan_approved(YEAR), {"status": "Met", "source_ref": doc.name})
		self.assertIn("ic_plan_approved", self_checks.register())
