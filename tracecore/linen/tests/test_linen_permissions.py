"""Quyền Linen Type / Linen Collection theo ma trận SEC (FEAT-033, A-49 L10)."""

import frappe

from tracecore.tests.factories import make_linen_collection, make_user
from tracecore.tests.utils import IsolatedTestCase, assert_permission_matrix

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


class TestLinenPermissions(IsolatedTestCase):
	def test_effective_permissions_match_the_matrix(self):
		for doctype in ("Linen Type", "Linen Collection"):
			assert_permission_matrix(self, doctype)

	def can(self, role, ptype, doctype="Linen Collection", doc=None):
		user = make_user(f"linen-{role.lower().replace(' ', '-')}@example.com", roles=(role,))
		return frappe.has_permission(doctype, ptype, doc=doc, user=user)

	def test_r07_collects_and_submits_but_cannot_cancel(self):
		doc = make_linen_collection()
		self.assertTrue(self.can("TC R07", "create"))
		self.assertTrue(self.can("TC R07", "submit", doc=doc))
		self.assertFalse(self.can("TC R07", "cancel", doc=doc))

	def test_r02_can_cancel_and_amend(self):
		doc = make_linen_collection()
		self.assertTrue(self.can("TC R02", "cancel", doc=doc))
		self.assertTrue(self.can("TC R02", "amend", doc=doc))

	def test_r08_cannot_read_collections_yet(self):  # chờ quyền theo khoa của FEAT-035
		self.assertFalse(self.can("TC R08", "read"))

	def test_readers_cannot_write(self):
		for role in ("TC R01", "TC R09"):
			self.assertTrue(self.can(role, "read"))
			self.assertFalse(self.can(role, "write"))

	def test_r07_and_r02_manage_the_catalogue_and_r10_configures_it(self):
		for role in ("TC R02", "TC R07", "TC R10"):
			self.assertTrue(self.can(role, "write", "Linen Type"), role)
		self.assertFalse(self.can("TC R09", "write", "Linen Type"))

	def test_nobody_can_delete(self):
		for doctype in ("Linen Type", "Linen Collection"):
			self.assertFalse(self.can("TC R10", "delete", doctype), doctype)
