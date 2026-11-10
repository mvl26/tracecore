"""IC Committee — Hội đồng KSNK (FEAT-057 AC-4..AC-6; FEAT-094 AC-094-10..13; FR-M11-02; BRU-ICP-002; UC-40 A3, E1, E1a)."""

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
			[
				"Functional Unit",
				"Microbiology and Laboratory",
				"Pharmacy",
				"High-risk Clinical",
				"Other",
				# FEAT-094 (A-138 f): thêm cuối danh sách
				"Nursing",
				"Quality Management",
				"Planning and General",
				"Infrastructure",
				"Medical Equipment",
			],
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
		fx.approved_profile()
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


# --- FEAT-094 (A-138): Chủ tịch, Thư ký, khối bắt buộc theo bộ tiêu chí ---------------------------------------------


def _audit_reasons(name):
	return " ".join(
		reason or ""
		for reason in frappe.get_all(
			"Audit Log", filters={"ref_doctype": DOCTYPE, "ref_name": name}, pluck="reason"
		)
	)


class TestICCommitteeProfileRules(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.db.sql("update `tabIC Structure Profile` set status = 'Draft'")
		self.members = fx.full_committee_members("BTC")
		self.chair, self.secretary = self.members[0][0], self.members[1][0]
		fx.settings(staff=[(self.secretary, 1, 1, "Head")])
		frappe.db.set_single_value("IC Program Settings", "director", self.chair)

	def _problems(self, members):
		return [row["code"] for row in structure.committee_problems(fx.committee(members))]

	@bru("BRU-ICP-002")
	def test_ac10_missing_functional_unit_warns_and_logs(self):
		fx.approved_profile()
		members = [
			(emp, role, "Other" if rep == "Functional Unit" else rep) for emp, role, rep in self.members
		]
		frappe.clear_messages()
		doc = fx.committee(members, submit=True)
		self.assertEqual(doc.docstatus, 1)
		self.assertEqual(structure.missing_representatives(doc), ["Functional Unit"])
		self.assertIn("Functional Unit", " ".join(str(m) for m in frappe.get_message_log()))
		self.assertIn("REPRESENTATIVE:Functional Unit", _audit_reasons(doc.name))

	@bru("BRU-ICP-002")
	def test_complete_committee_has_no_problem(self):
		fx.approved_profile()
		self.assertEqual(self._problems(self.members), [])

	@bru("BRU-ICP-002")
	def test_ac11_chair_not_director_and_secretary_not_lead_warn(self):
		fx.approved_profile()
		other = fx.employee("BTC GĐ khác")
		fx.settings(staff=[(self.secretary, 1, 1, "Surveillance Officer")])
		frappe.db.set_single_value("IC Program Settings", "director", other)
		frappe.clear_messages()
		doc = fx.committee(self.members, submit=True)
		self.assertEqual(doc.docstatus, 1)
		codes = [row["code"] for row in structure.committee_problems(doc)]
		self.assertEqual(codes, ["CHAIR_NOT_DIRECTOR", "SECRETARY_NOT_IC_LEAD"])
		reasons = _audit_reasons(doc.name)
		self.assertIn("CHAIR_NOT_DIRECTOR", reasons)
		self.assertIn("SECRETARY_NOT_IC_LEAD", reasons)

	@bru("BRU-ICP-002")
	def test_ac11_director_not_set_skips_chair_check_and_reminds(self):
		fx.approved_profile()
		frappe.db.set_single_value("IC Program Settings", "director", None)
		problems = structure.committee_problems(fx.committee(self.members))
		self.assertEqual([row["code"] for row in problems], ["DIRECTOR_NOT_SET"])
		self.assertEqual(problems[0]["blocking"], 0)

	@bru("BRU-ICP-002")
	def test_ac11_block_severity_rejects_submit(self):
		fx.approved_profile(committee_rule_severity="Block")
		members = [m for m in self.members if m[2] != "Pharmacy"]
		doc = fx.committee(members)
		with self.assertRaises(frappe.ValidationError) as caught:
			doc.submit()
		self.assertIn("Pharmacy", str(caught.exception))
		self.assertEqual(frappe.db.get_value(DOCTYPE, doc.name, "docstatus"), 0)

	@bru("BRU-ICP-002")
	def test_block_severity_allows_complete_committee(self):
		fx.approved_profile(committee_rule_severity="Block")
		doc = fx.committee(self.members, submit=True)
		self.assertEqual(doc.docstatus, 1)

	@bru("BRU-ICP-002")
	def test_ac12_one_chair_one_secretary_always_blocks(self):
		fx.approved_profile()
		members = [m for m in self.members if m[1] != "Chair"]
		with self.assertRaises(frappe.ValidationError) as caught:
			fx.committee(members).submit()
		self.assertIn("Missing Chair", str(caught.exception))

	@bru("BRU-ICP-002")
	def test_ac13_profile_requires_extra_groups_and_vice_chair(self):
		from tracecore.infection_program import structure_seed

		requirements = [
			*structure_seed.default_profile()["committee_requirements"],
			{"requirement_type": "Representing", "representing": "Nursing", "min_count": 1},
			{"requirement_type": "Representing", "representing": "Quality Management", "min_count": 1},
			{"requirement_type": "Role", "committee_role": "Vice Chair", "min_count": 1},
		]
		fx.approved_profile(committee_requirements=requirements)
		self.assertEqual(self._problems(self.members), ["REPRESENTATIVE", "REPRESENTATIVE", "ROLE"])
		members = [
			*self.members,
			(fx.employee("BTC ĐD"), "Vice Chair", "Nursing"),
			(fx.employee("BTC QLCL"), "Ordinary Member", "Quality Management"),
		]
		self.assertEqual(self._problems(members), [])
