"""IC Network Member — mạng lưới viên KSNK (FEAT-057 AC-7..AC-9; FR-M11-03; BRU-ICP-003; A-132 c, d; UC-40 E2, E3)."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.infection_program import network
from tracecore.infection_program.tests import ic_fixtures as fx
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase, assert_permission_matrix, bru

DOCTYPE = "IC Network Member"


def _dept_permissions(user):
	return set(
		frappe.get_all("User Permission", filters={"user": user, "allow": "Department"}, pluck="for_value")
	)


class TestICNetworkMember(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		fx.clear_required_departments()
		self.dept_a = fx.required_department("KSNK Test Ngoại")
		self.dept_b = fx.required_department("KSNK Test Sản")

	def test_meta(self):
		meta = frappe.get_meta(DOCTYPE)
		self.assertEqual(meta.module, "Infection Program")
		self.assertEqual(meta.autoname, "ML-.#####")
		self.assertEqual(
			meta.get_field("member_type").options.split("\n"), ["Doctor", "Nurse", "Midwife", "Technician"]
		)
		self.assertEqual(frappe.get_meta("Department").get_field("tc_ic_network_required").fieldtype, "Check")

	def test_duplicate_active_membership_rejected(self):
		emp = fx.employee("Dup Doctor")
		fx.network_member(emp, self.dept_a, "Doctor")
		with self.assertRaises(frappe.ValidationError):
			fx.network_member(emp, self.dept_a, "Doctor")
		fx.network_member(emp, self.dept_b, "Doctor")  # khoa khác thì được

	def test_assigns_r12_role_and_department_permission(self):
		user = factories.make_user("ksnk-nw-a@example.com")
		member = fx.network_member(fx.employee("Net User", self.dept_a, user=user), self.dept_a, "Nurse")
		self.assertIn("TC R12", frappe.get_roles(user))
		self.assertEqual(_dept_permissions(user), {self.dept_a})
		audit = frappe.get_all("Audit Log", filters={"ref_doctype": "User", "ref_name": user}, pluck="reason")
		self.assertTrue(audit)

		member.is_active = 0
		member.save(ignore_permissions=True)
		self.assertNotIn("TC R12", frappe.get_roles(user))
		self.assertEqual(_dept_permissions(user), set())

	def test_r01_and_r02_save_member_and_role_sync_still_runs(self):
		"""R01/R02 không có quyền ghi User; gán R12 + User Permission vẫn chạy (bỏ qua quyền ở bước hệ thống)."""
		for code in ("R01", "R02"):
			with self.subTest(role=code):
				editor = factories.make_user(f"ksnk-nw-editor-{code.lower()}@example.com", [f"TC {code}"])
				user = factories.make_user(f"ksnk-nw-target-{code.lower()}@example.com")
				employee = fx.employee(f"Net Target {code}", self.dept_a, user=user)
				frappe.set_user(editor)
				member = frappe.get_doc(
					{
						"doctype": DOCTYPE,
						"employee": employee,
						"department": self.dept_a,
						"member_type": "Doctor",
					}
				).insert()
				member.is_active = 0
				member.save()
				frappe.set_user("Administrator")
				self.assertNotIn("TC R12", frappe.get_roles(user))
				frappe.set_user(editor)
				member.is_active = 1
				member.save()
				frappe.set_user("Administrator")
				self.assertIn("TC R12", frappe.get_roles(user))
				self.assertEqual(_dept_permissions(user), {self.dept_a})

	def test_keeps_role_while_another_membership_is_active(self):
		user = factories.make_user("ksnk-nw-b@example.com")
		emp = fx.employee("Net Two", self.dept_a, user=user)
		first = fx.network_member(emp, self.dept_a, "Doctor")
		fx.network_member(emp, self.dept_b, "Doctor")
		self.assertEqual(_dept_permissions(user), {self.dept_a, self.dept_b})
		first.is_active = 0
		first.save(ignore_permissions=True)
		self.assertIn("TC R12", frappe.get_roles(user))
		self.assertEqual(_dept_permissions(user), {self.dept_b})

	def test_manual_department_permission_is_not_removed(self):
		user = factories.make_user("ksnk-nw-c@example.com")
		frappe.get_doc(
			{"doctype": "User Permission", "user": user, "allow": "Department", "for_value": self.dept_b}
		).insert(ignore_permissions=True)
		member = fx.network_member(fx.employee("Net Three", self.dept_a, user=user), self.dept_a, "Doctor")
		member.is_active = 0
		member.save(ignore_permissions=True)
		self.assertEqual(_dept_permissions(user), {self.dept_b})

	def test_r12_reads_only_own_department(self):
		user = factories.make_user("ksnk-nw-d@example.com")
		mine = fx.network_member(fx.employee("Reader", self.dept_a, user=user), self.dept_a, "Doctor")
		other = fx.network_member(fx.employee("Other Dept"), self.dept_b, "Doctor")
		frappe.set_user(user)
		names = set(frappe.get_list(DOCTYPE, pluck="name"))
		self.assertIn(mine.name, names)
		self.assertNotIn(other.name, names)

	@bru("BRU-ICP-003")
	def test_deactivating_last_doctor_warns_r01(self):
		doctor = fx.network_member(fx.employee("Last Doctor"), self.dept_a, "Doctor")
		fx.network_member(fx.employee("Some Nurse"), self.dept_a, "Nurse")
		with patch.object(network.notification, "emit") as emit:
			doctor.is_active = 0
			doctor.save(ignore_permissions=True)
		emit.assert_called_once()
		self.assertEqual(emit.call_args.args[0], "IC_NETWORK_GAP")
		reasons = frappe.get_all(
			"Audit Log", filters={"ref_doctype": DOCTYPE, "ref_name": doctor.name}, pluck="reason"
		)
		self.assertTrue(any(reason and "IC_NETWORK_GAP" in reason for reason in reasons), reasons)

	@bru("BRU-ICP-003")
	def test_moving_last_nurse_to_other_department_warns(self):
		nurse = fx.network_member(fx.employee("Moving Nurse"), self.dept_a, "Nurse")
		with patch.object(network.notification, "emit") as emit:
			nurse.department = self.dept_b
			nurse.save(ignore_permissions=True)
		emit.assert_called_once()

	def test_no_warning_while_group_still_covered(self):
		first = fx.network_member(fx.employee("Doc One"), self.dept_a, "Doctor")
		fx.network_member(fx.employee("Doc Two"), self.dept_a, "Doctor")
		with patch.object(network.notification, "emit") as emit:
			first.is_active = 0
			first.save(ignore_permissions=True)
		emit.assert_not_called()

	def test_no_warning_for_department_not_required(self):
		frappe.db.set_value("Department", self.dept_a, "tc_ic_network_required", 0)
		doctor = fx.network_member(fx.employee("Free Doctor"), self.dept_a, "Doctor")
		with patch.object(network.notification, "emit") as emit:
			doctor.is_active = 0
			doctor.save(ignore_permissions=True)
		emit.assert_not_called()


class TestICNetworkMemberPermissions(FrappeTestCase):
	def test_permission_matrix(self):
		assert_permission_matrix(self, DOCTYPE)
