"""Cấu hình chuyên môn M16 có phiên bản (FEAT-071; FR-M16-04, FR-M16-07; BRU-OCC-004; NFR-MAINT-04; A-137 Q3)."""

import frappe

from tracecore.occupational_safety import config
from tracecore.occupational_safety.tests import os_fixtures as fx
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase, bru

TEMPLATE = "Exposure Follow-up Template"
REQUIREMENT = "Immunization Requirement"


class TestFollowupTemplate(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		fx.clear_templates()

	def test_versions_are_numbered_per_type(self):
		first = fx.template(approve=False)
		second = fx.template(approve=False)
		other = fx.template(fx.SPLASH, approve=False)
		self.assertEqual((first.version_no, second.version_no, other.version_no), (1, 2, 1))
		self.assertEqual(first.name, f"{fx.SHARPS}-V1")
		self.assertEqual(second.name, f"{fx.SHARPS}-V2")
		self.assertEqual(first.status, "Draft")

	@bru("BRU-OCC-004")
	def test_approving_a_new_version_supersedes_the_old_one(self):
		first = fx.template()
		self.assertEqual(first.status, "Approved")
		self.assertEqual(config.active_template(fx.SHARPS).name, first.name)
		second = fx.template(steps=(("Step A", 0),))
		self.assertEqual(frappe.db.get_value(TEMPLATE, first.name, "status"), "Superseded")
		self.assertEqual(config.active_template(fx.SHARPS).name, second.name)
		self.assertTrue(second.approved_by)
		self.assertIsNone(config.active_template(fx.SPLASH))

	def test_template_without_steps_cannot_be_approved(self):
		doc = fx.template(steps=(), approve=False)
		with self.assertRaises(frappe.ValidationError):
			config.approve_template(doc.name)
		self.assertEqual(frappe.db.get_value(TEMPLATE, doc.name, "status"), "Draft")

	def test_approved_version_is_frozen(self):
		doc = fx.template()
		doc.append("steps", {"step": "Extra", "days_after": 3})
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)

	def test_only_r01_approves(self):
		doc = fx.template(approve=False)
		r11 = factories.make_user("os-r11-approve@example.com", roles=["TC R11"])
		r01 = factories.make_user("os-r01-approve@example.com", roles=["TC R01"])
		frappe.set_user(r11)
		with self.assertRaises(frappe.PermissionError):
			config.approve_template(doc.name)
		frappe.set_user(r01)
		config.approve_template(doc.name)
		self.assertEqual(frappe.db.get_value(TEMPLATE, doc.name, "status"), "Approved")
		self.assertTrue(
			frappe.db.exists("Audit Log", {"ref_doctype": TEMPLATE, "ref_name": doc.name, "action": "Update"})
		)


class TestImmunizationRequirement(IsolatedTestCase):
	def test_approval_needs_doses(self):
		doc = fx.requirement("Test Vaccine Zero", doses=0, approve=False)
		with self.assertRaises(frappe.ValidationError):
			config.approve_requirement(doc.name)
		doc = fx.requirement("Test Vaccine One", doses=1)
		self.assertEqual(doc.status, "Approved")


class TestDefaultConfig(IsolatedTestCase):
	@bru("BRU-OCC-004")
	def test_migrate_twice_keeps_hospital_edits(self):
		"""NFR-MAINT-04: fixtures Nháp chỉ chèn khi chưa có; bản R01 đã sửa/duyệt giữ nguyên sau migrate."""
		fx.clear_templates()
		config.ensure_default_config()
		types = set(frappe.get_all(TEMPLATE, pluck="exposure_type"))
		self.assertEqual(types, set(config.EXPOSURE_TYPES))
		self.assertEqual(set(frappe.get_all(TEMPLATE, pluck="status")), {"Draft"})
		# nội dung chuyên môn do R01 nhập: fixtures không có bước nào (D10, OQ-V12-08)
		self.assertFalse(frappe.get_all("Exposure Follow-up Template Step", filters={"parenttype": TEMPLATE}))

		draft = frappe.get_doc(TEMPLATE, f"{fx.SHARPS}-V1")
		draft.append("steps", {"step": "Hospital step", "days_after": 14})
		draft.save(ignore_permissions=True)
		config.approve_template(draft.name)
		vaccines = frappe.get_all(REQUIREMENT, filters={"status": "Draft"}, pluck="name")
		self.assertTrue(vaccines)
		frappe.db.set_value(REQUIREMENT, vaccines[0], "doses_required", 4)

		config.ensure_default_config()
		config.ensure_default_config()
		self.assertEqual(frappe.get_all(TEMPLATE, filters={"exposure_type": fx.SHARPS}, pluck="name"), [draft.name])
		self.assertEqual(frappe.db.get_value(TEMPLATE, draft.name, "status"), "Approved")
		self.assertEqual([r.step for r in frappe.get_doc(TEMPLATE, draft.name).steps], ["Hospital step"])
		self.assertEqual(frappe.db.get_value(REQUIREMENT, vaccines[0], "doses_required"), 4)

	def test_after_migrate_hook_registered(self):
		self.assertIn(
			"tracecore.occupational_safety.config.ensure_default_config", frappe.get_hooks("after_migrate")
		)
