"""M16 đăng ký việc cần xử lý của bảng chỉ số KSNK (FEAT-065; FR-M9-26; hook ``tracecore_ksnk_todos``; A-145 Q3;
NFR-PRIV-01: chỉ đếm, không tên)."""

from frappe.utils import add_days, now_datetime, today

from tracecore.occupational_safety import exposure, todos
from tracecore.occupational_safety.tests import os_fixtures as fx
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase


class TestExposureTodos(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		fx.clear_templates()
		fx.thresholds()
		self.dept = factories.make_department("PN Hook Khoa")
		self.other = factories.make_department("PN Hook Khoa Khac")
		self.employee = fx.employee("PN Hook Staff", self.dept)
		fx.template(steps=(("Step 1", 0), ("Step 2", 10)))
		doc = exposure.create_report(
			{"employee": self.employee, "exposure_type": fx.SHARPS, "occurred_at": now_datetime()}
		)
		self.doc = exposure.record_handling(doc.name, first_aid_done=1, prophylaxis="Not Indicated")
		exposure.mark_followup_done(self.doc.name, self.doc.followups[0].name, today())

	def test_counts_steps_due_within_three_days_without_names(self):
		self.assertEqual(todos.todos("Administrator", self.dept, today()), [])
		items = todos.todos("Administrator", self.dept, add_days(today(), 7))
		self.assertEqual(items[0]["count"], 1)
		self.assertEqual(items[0]["link"], "")
		self.assertNotIn("PN Hook Staff", str(items))
		self.assertNotIn(self.doc.name, str(items))
		self.assertEqual(todos.todos("Administrator", self.other, add_days(today(), 7)), [])
		hospital = todos.todos("Administrator", None, add_days(today(), 7))
		self.assertEqual(hospital[0]["link"], exposure.LINK)
