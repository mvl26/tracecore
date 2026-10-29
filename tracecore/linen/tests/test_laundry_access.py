"""Quyền Laundry Batch theo ma trận SEC, menu Linen và tài sản trạm (FEAT-034, A-50 D1, D13)."""

import frappe

from tracecore.tests.factories import make_linen_station, make_user
from tracecore.tests.utils import IsolatedTestCase, assert_permission_matrix
from tracecore.v1 import navigation

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

DOCTYPE = "Laundry Batch"


class TestLaundryAccess(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")

	def can(self, role, ptype, doc=None):
		user = make_user(f"laundry-{role.lower().replace(' ', '-')}@example.com", roles=(role,))
		return frappe.has_permission(DOCTYPE, ptype, doc=doc, user=user)

	def test_effective_permissions_match_the_matrix(self):
		assert_permission_matrix(self, DOCTYPE)

	def test_r07_creates_and_submits_but_cannot_cancel(self):
		doc = frappe.new_doc(DOCTYPE)
		self.assertTrue(self.can("TC R07", "create"))
		self.assertTrue(self.can("TC R07", "submit", doc=doc))
		self.assertFalse(self.can("TC R07", "cancel", doc=doc))

	def test_r02_can_cancel_and_amend(self):
		doc = frappe.new_doc(DOCTYPE)
		self.assertTrue(self.can("TC R02", "cancel", doc=doc))
		self.assertTrue(self.can("TC R02", "amend", doc=doc))

	def test_readers_cannot_write_and_nobody_can_delete(self):
		for role in ("TC R01", "TC R09", "TC R10"):
			self.assertTrue(self.can(role, "read"), role)
			self.assertFalse(self.can(role, "write"), role)
		for role in ("TC R02", "TC R07", "TC R10"):
			self.assertFalse(self.can(role, "delete"), role)

	def test_managers_get_the_laundry_links_in_the_linen_group(self):
		frappe.set_user(make_user("laundry-nav-r02@example.com", roles=("TC R02",)))
		links = navigation.context()["management"]
		linen = [link["route"] for link in links if link["group"] == "Linen"]
		self.assertIn("/app/laundry-batch", linen)
		self.assertIn("/app/query-report/Laundry Cost per Kg", [link["route"] for link in links])

	def test_laundry_screen_is_served_with_the_station_page(self):
		make_linen_station()
		assets = (frappe.get_hooks("page_js") or {}).get("station", [])
		self.assertIn("public/js/station_laundry.js", assets)
