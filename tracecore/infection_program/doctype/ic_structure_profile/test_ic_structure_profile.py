"""IC Structure Profile — bộ tiêu chí cơ cấu có phiên bản (FEAT-094 AC-094-01, 02; FR-M11-01.8; NFR-MAINT-04)."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from tracecore.infection_program import structure_profile, structure_seed
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase, assert_permission_matrix, bru

DOCTYPE = "IC Structure Profile"


def _draft(**values):
	doc = structure_seed.default_profile()
	doc.update({"profile_name": "Test", "effective_from": add_days(today(), -1), **values})
	return frappe.get_doc(doc).insert(ignore_permissions=True)


def _audit_statuses(name):
	return frappe.get_all(
		"Audit Log", filters={"ref_doctype": DOCTYPE, "ref_name": name}, pluck="reason", order_by="creation"
	)


class TestICStructureProfile(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")

	def test_meta(self):
		meta = frappe.get_meta(DOCTYPE)
		self.assertEqual(meta.module, "Infection Program")
		self.assertEqual(meta.autoname, "BTC-.YYYY.-.##")
		self.assertFalse(meta.is_submittable)
		self.assertEqual(meta.get_field("committee_min_beds").default, "150")
		self.assertEqual(meta.get_field("department_min_beds").default, "150")
		self.assertEqual(
			frappe.get_meta("IC Structure Role Requirement").get_field("ic_role").options.split("\n"),
			["Head", "Head Nurse", "Person in Charge", "Surveillance Officer"],
		)

	def test_insert_is_draft_with_next_version(self):
		first = _draft()
		second = _draft(status="Approved")
		self.assertEqual(first.status, "Draft")
		self.assertEqual(second.status, "Draft")  # không tự đặt trạng thái khi tạo
		self.assertEqual(second.version_no, first.version_no + 1)
		self.assertTrue(first.name.startswith("BTC-"))

	@bru("BRU-ICP-001")
	def test_r01_approves_supersedes_previous_and_logs(self):
		old = structure_profile.approve(_draft().name)
		new = _draft()
		user = factories.make_user("ksnk-profile-r01@example.com", ["TC R01"])
		frappe.set_user(user)
		structure_profile.approve(new.name)
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value(DOCTYPE, new.name, "status"), "Approved")
		self.assertEqual(frappe.db.get_value(DOCTYPE, old.name, "status"), "Superseded")
		self.assertTrue(frappe.db.get_value(DOCTYPE, new.name, "approved_on"))
		self.assertIn("Approved", _audit_statuses(new.name))
		self.assertIn("Superseded", _audit_statuses(old.name))
		self.assertEqual(structure_profile.active_profile().name, new.name)

	def test_future_profile_does_not_supersede_current(self):
		current = structure_profile.approve(_draft().name)
		future = structure_profile.approve(_draft(effective_from=add_days(today(), 30)).name)
		self.assertEqual(frappe.db.get_value(DOCTYPE, current.name, "status"), "Approved")
		self.assertEqual(structure_profile.active_profile().name, current.name)
		self.assertEqual(structure_profile.active_profile(add_days(today(), 30)).name, future.name)

	def test_approved_profile_cannot_be_changed(self):
		doc = structure_profile.approve(_draft().name)
		doc.reload()
		doc.committee_min_beds = 0
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)
		doc.reload()
		doc.role_requirements[0].min_education = "College"
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)

	def test_only_draft_can_be_approved(self):
		doc = structure_profile.approve(_draft().name)
		with self.assertRaises(frappe.ValidationError):
			structure_profile.approve(doc.name)

	def test_other_roles_cannot_approve(self):
		doc = _draft()
		users = [
			factories.make_user(f"ksnk-profile-{code.lower()}@example.com", [f"TC {code}"])
			for code in ("R02", "R10", "R13")
		]
		for user in users:
			frappe.set_user(user)
			with self.assertRaises(frappe.PermissionError):
				structure_profile.approve(doc.name)
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value(DOCTYPE, doc.name, "status"), "Draft")

	def test_form_method_approves(self):
		doc = _draft()
		doc.approve()
		self.assertEqual(frappe.db.get_value(DOCTYPE, doc.name, "status"), "Approved")

	def test_row_validation(self):
		with self.assertRaises(frappe.ValidationError):
			_draft(committee_requirements=[{"requirement_type": "Representing", "min_count": 1}])
		with self.assertRaises(frappe.ValidationError):
			_draft(committee_requirements=[{"requirement_type": "Role", "min_count": 1}])
		with self.assertRaises(frappe.ValidationError):
			_draft(
				committee_requirements=[
					{"requirement_type": "Role", "committee_role": "Vice Chair", "min_count": 0}
				]
			)
		roles = structure_seed.default_profile()["role_requirements"]
		with self.assertRaises(frappe.ValidationError):
			_draft(role_requirements=[*roles, dict(roles[0])])
		with self.assertRaises(frappe.ValidationError):
			_draft(department_min_beds=0)

	def test_certificate_types_are_trimmed(self):
		roles = structure_seed.default_profile()["role_requirements"]
		roles[0] = {**roles[0], "certificate_types": "  CC KSNK \n\n Văn bằng  "}
		doc = _draft(role_requirements=roles)
		self.assertEqual(doc.role_requirements[0].certificate_types, "CC KSNK\nVăn bằng")

	def test_active_profile_none_without_approved(self):
		frappe.db.sql("update `tabIC Structure Profile` set status = 'Draft'")
		self.assertIsNone(structure_profile.active_profile())


class TestStructureSeed(IsolatedTestCase):
	def test_seed_inserts_draft_once(self):
		frappe.db.sql("delete from `tabIC Structure Committee Requirement`")
		frappe.db.sql("delete from `tabIC Structure Role Requirement`")
		frappe.db.sql("delete from `tabIC Structure Profile`")
		name = structure_seed.ensure_seed()
		self.assertIsNone(structure_seed.ensure_seed())
		self.assertEqual(frappe.db.count(DOCTYPE), 1)
		doc = frappe.get_doc(DOCTYPE, name)
		self.assertEqual(doc.status, "Draft")
		self.assertEqual(doc.legal_basis, "TT 16/2018/TT-BYT Điều 16-22")
		self.assertEqual(
			[row.representing for row in doc.committee_requirements], list(structure_seed.COMMITTEE_GROUPS)
		)
		self.assertEqual(len(doc.role_requirements), len(structure_seed.ROLES))

	@bru("BRU-ICP-001")
	def test_seed_keeps_hospital_edited_or_approved_version(self):
		frappe.db.sql("delete from `tabIC Structure Profile`")
		name = structure_seed.ensure_seed()
		doc = frappe.get_doc(DOCTYPE, name)
		doc.committee_min_beds = 100
		doc.save(ignore_permissions=True)
		structure_profile.approve(name)
		self.assertIsNone(structure_seed.ensure_seed())
		self.assertEqual(frappe.db.count(DOCTYPE), 1)
		self.assertEqual(
			frappe.db.get_value(DOCTYPE, name, ["committee_min_beds", "status"]), (100, "Approved")
		)

	def test_hooks_register_seed(self):
		self.assertIn(
			"tracecore.infection_program.structure_seed.ensure_seed", frappe.get_hooks("after_migrate")
		)


class TestICStructureProfilePermissions(FrappeTestCase):
	def test_permission_matrix(self):
		assert_permission_matrix(self, DOCTYPE)
