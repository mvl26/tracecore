"""Launcher: nhóm "Linen" và trạm đồ vải (FEAT-033, A-49 L1)."""

import frappe

from tracecore.tests.factories import make_linen_station, make_user
from tracecore.tests.utils import IsolatedTestCase
from tracecore.v1 import navigation


class TestLinenNavigation(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")

	def test_linen_station_is_reserved_for_r07_and_implemented(self):
		self.assertEqual(navigation.STEP_ROLES["LIN"], {"TC R07"})
		self.assertIn("LIN", navigation.IMPLEMENTED_STEPS)

	def test_supervisor_sees_the_linen_station_as_implemented(self):
		station = make_linen_station()
		frappe.set_user(make_user("linen-nav-r02-st@example.com", roles=("TC R02",)))
		rows = [row for row in navigation.context()["stations"] if row["step"] == "LIN"]
		self.assertEqual([row["name"] for row in rows], [station])
		self.assertTrue(rows[0]["implemented"])

	def test_managers_get_the_linen_links(self):
		frappe.set_user(make_user("linen-nav-r02@example.com", roles=("TC R02",)))
		links = navigation.context()["management"]
		linen = [link["route"] for link in links if link["group"] == "Linen"]
		self.assertEqual(
			linen,
			[
				"/app/linen-type",
				"/app/linen-collection",
				"/app/laundry-batch",
				"/app/query-report/Laundry Cost per Kg",
				"/app/linen-issue",
				"/app/query-report/Linen Reconciliation",
			],
		)
