"""IC Committee — Hội đồng KSNK (FEAT-057 AC-4..AC-6; FR-M11-02; BRU-ICP-002; UC-40 A3, E1)."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, getdate, today

from tracecore.infection_program import structure
from tracecore.infection_program.tests import ic_fixtures as fx
from tracecore.tests.utils import IsolatedTestCase, assert_permission_matrix, bru

DOCTYPE = "IC Committee"


class TestICCommittee(IsolatedTestCase):
	def test_meta(self):
		meta = frappe.get_meta(DOCTYPE)
		self.assertTrue(meta.is_submittable)
		self.assertEqual(meta.module, "Infection Program")
		self.assertEqual(meta.autoname, "HDK-.YYYY.-.##")
		child = frappe.get_meta("IC Committee Member")
		self.assertTrue(child.istable)
		self.assertEqual(
			child.get_field("committee_role").options.split("\n"),
			["Chair", "Vice Chair", "Secretary", "Ordinary Member"],
		)
		self.assertEqual(
			child.get_field("representing").options.split("\n"),
			["Functional Unit", "Microbiology and Laboratory", "Pharmacy", "High-risk Clinical", "Other"],
		)

	@bru("BRU-ICP-002")
	def test_submit_with_one_chair_and_one_secretary(self):
		doc = fx.committee(fx.full_committee_members(), submit=True)
		self.assertEqual(doc.docstatus, 1)
		self.assertTrue(doc.name.startswith(f"HDK-{getdate().year}-"))

	@bru("BRU-ICP-002")
	def test_missing_secretary_blocks_submit_and_names_role(self):
		members = [m for m in fx.full_committee_members() if m[1] != "Secretary"]
		doc = fx.committee(members)  # Nháp lưu được
		with self.assertRaises(frappe.ValidationError) as caught:
			doc.submit()
		self.assertIn("Missing Secretary", str(caught.exception))
		self.assertNotIn("Chair", str(caught.exception).split(":", 1)[-1].replace("Missing Secretary", ""))

	@bru("BRU-ICP-002")
	def test_two_chairs_blocks_submit(self):
		members = fx.full_committee_members()
		members.append((fx.employee("HD Chair 2"), "Chair", "Functional Unit"))
		doc = fx.committee(members)
		with self.assertRaises(frappe.ValidationError) as caught:
			doc.submit()
		self.assertIn("2 Chair", str(caught.exception))

	@bru("BRU-ICP-002")
	def test_missing_representatives_warns_and_logs_audit(self):
		members = [m for m in fx.full_committee_members() if m[2] != "Pharmacy"]
		frappe.clear_messages()
		doc = fx.committee(members, submit=True)
		self.assertEqual(doc.docstatus, 1)
		self.assertEqual(structure.missing_representatives(doc), ["Pharmacy"])
		messages = " ".join(str(m) for m in frappe.get_message_log())
		self.assertIn("Pharmacy", messages)
		reasons = frappe.get_all(
			"Audit Log", filters={"ref_doctype": DOCTYPE, "ref_name": doc.name}, pluck="reason"
		)
		self.assertTrue(any(reason and "Pharmacy" in reason for reason in reasons), reasons)

	def test_valid_to_before_valid_from_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			fx.committee(fx.full_committee_members(), valid_from=today(), valid_to=fx.yesterday())

	def test_duplicate_employee_rejected(self):
		members = fx.full_committee_members()
		members.append((members[2][0], "Ordinary Member", "Other"))
		with self.assertRaises(frappe.ValidationError):
			fx.committee(members)

	def test_active_committee_is_latest_valid_submitted(self):
		old = fx.committee(
			fx.full_committee_members("Old"),
			valid_from=add_days(today(), -400),
			valid_to=fx.yesterday(),
			submit=True,
		)
		current = fx.committee(
			fx.full_committee_members("Cur"), valid_from=add_days(today(), -10), submit=True
		)
		fx.committee(fx.full_committee_members("Draft"), valid_from=today())  # Nháp không tính
		active = structure.active_committee()
		self.assertEqual(active.name, current.name)
		self.assertNotEqual(active.name, old.name)
		self.assertEqual(frappe.db.get_value(DOCTYPE, old.name, "docstatus"), 1)  # lịch sử giữ nguyên


class TestICCommitteePermissions(FrappeTestCase):
	def test_permission_matrix(self):
		assert_permission_matrix(self, DOCTYPE)
