"""M13 đăng ký vào bảng chỉ số KSNK (FEAT-065; FR-M9-26, FR-M9-29; hook ``tracecore_ksnk_todos``,
``tracecore_ic_self_checks``; A-145 Q3, D8)."""

from frappe.utils import add_days, getdate, today

from tracecore.hai_surveillance import self_checks, todos
from tracecore.hai_surveillance.tests.factories import make_census, make_episode, make_ward
from tracecore.tests.utils import IsolatedTestCase


class TestHaiHooks(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.ward_a = make_ward("KSNK Hook Ward A")
		self.ward_b = make_ward("KSNK Hook Ward B")
		self.yesterday = getdate(add_days(today(), -1))
		make_census(self.ward_a, self.yesterday)

	def test_missing_census_listed_for_hospital_and_department(self):
		items = todos.todos("Administrator", None)
		self.assertEqual(items[0]["severity"], "error")
		self.assertGreaterEqual(items[0]["count"], 1)
		own = todos.todos("Administrator", self.ward_b)
		self.assertEqual((own[0]["count"], own[0]["link"]), (1, todos.PORTAL_LINK))
		self.assertEqual(todos.todos("Administrator", self.ward_a), [])

	def test_surveillance_activity_check(self):
		self.assertEqual(self_checks.surveillance_active(1990)["status"], "Not met")
		make_episode(self.ward_a, inserted_on=self.yesterday)
		result = self_checks.surveillance_active(self.yesterday.year)
		self.assertEqual(result["status"], "Needs confirmation")
		self.assertNotIn("BN-", result["source_ref"])
		self.assertIn("hai_surveillance_active", self_checks.register())
