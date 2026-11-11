"""Quyền theo khoa của mẫu số và đợt thiết bị (FEAT-062; NFR-SEC-09, ADR-010 mở rộng; A-141 g)."""

import frappe

from tracecore.hai_surveillance.tests import factories as f
from tracecore.tests.utils import IsolatedTestCase


class TestDepartmentScope(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		self.ward_a = f.make_ward("KSNK Perm Khoa A")
		self.ward_b = f.make_ward("KSNK Perm Khoa B")
		for ward in (self.ward_a, self.ward_b):
			frappe.db.delete("Ward Daily Census", {"department": ward})
			frappe.db.delete("Device Episode", {"department": ward})
		self.census_b = f.make_census(self.ward_b).name
		self.census_a = f.make_census(self.ward_a).name
		self.episode_b = f.make_episode(self.ward_b).name
		self.r12 = f.make_dept_user("perm-r12-a@test.local", f.R12, self.ward_a)
		self.r13 = f.factories.make_user("perm-r13@test.local", [f.R13])
		self.r11 = f.factories.make_user("perm-r11@test.local", [f.R11])

	def test_r12_sees_only_own_department(self):
		frappe.set_user(self.r12)
		names = frappe.get_list(
			"Ward Daily Census", filters={"department": ["in", [self.ward_a, self.ward_b]]}, pluck="name"
		)
		self.assertEqual(names, [self.census_a])
		self.assertEqual(
			frappe.get_list("Device Episode", filters={"department": self.ward_b}, pluck="name"), []
		)
		self.assertFalse(frappe.has_permission("Ward Daily Census", "read", self.census_b))
		self.assertTrue(frappe.has_permission("Ward Daily Census", "read", self.census_a))

	def test_r13_cannot_read_device_episode(self):
		frappe.set_user(self.r13)
		self.assertFalse(frappe.has_permission("Device Episode", "read"))

	def test_r11_reads_all(self):
		frappe.set_user(self.r11)
		self.assertTrue(frappe.has_permission("Device Episode", "read", self.episode_b))

	def test_nobody_deletes(self):
		for role in ("TC R01", "TC R08", "TC R11", "TC R12"):
			for doctype in ("Ward Daily Census", "Device Episode"):
				self.assertFalse(
					frappe.db.exists("Custom DocPerm", {"parent": doctype, "role": role, "delete": 1}),
					(doctype, role),
				)
