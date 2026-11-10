"""Cơ cấu KSNK bắt buộc và danh sách thiếu (FEAT-057 AC-1..AC-3, AC-7, AC-10; FR-M11-01, FR-M11-03; BRU-ICP-001, 003)."""

import frappe

from tracecore.infection_program import structure
from tracecore.infection_program.report.ic_structure_gaps import ic_structure_gaps
from tracecore.infection_program.tests import ic_fixtures as fx
from tracecore.tests.utils import IsolatedTestCase, bru, local_context


def _by_key(result):
	return {row["key"]: row for row in result["components"]}


class TestRequiredSurveillance(IsolatedTestCase):
	@bru("BRU-ICP-001")
	def test_rounds_up_with_minimum_one(self):
		self.assertEqual(structure.required_surveillance(420, 150), 3)
		self.assertEqual(structure.required_surveillance(450, 150), 3)
		self.assertEqual(structure.required_surveillance(150, 150), 1)
		self.assertEqual(structure.required_surveillance(151, 150), 2)
		self.assertEqual(structure.required_surveillance(40, 150), 1)
		self.assertEqual(structure.required_surveillance(0, 150), 1)


class TestStructure(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		fx.clear_required_departments()
		self.ic_dept = fx.required_department("KSNK Test Khoa KSNK")
		frappe.db.set_value("Department", self.ic_dept, "tc_ic_network_required", 0)
		self.dept_a = fx.required_department("KSNK Test Hồi sức")
		self.dept_b = fx.required_department("KSNK Test Nội 1")
		fx.network_member(fx.employee("NW A Doctor"), self.dept_a, "Doctor")
		fx.network_member(fx.employee("NW A Nurse"), self.dept_a, "Nurse")
		fx.network_member(fx.employee("NW B Nurse"), self.dept_b, "Nurse")
		self.staff = [fx.employee(f"GSV {n}") for n in range(4)]

	@bru("BRU-ICP-001")
	def test_large_hospital_requires_four_components(self):
		fx.settings(
			bed_count=420,
			ic_department=self.ic_dept,
			staff=[
				(self.staff[0], 1, 1),
				(self.staff[1], 1, 1),
				(self.staff[2], 1, 0),
				(self.staff[3], 0, 1),
			],
		)
		result = structure.compute()
		parts = _by_key(result)
		self.assertEqual(list(parts), ["committee", "ic_department", "network", "surveillance"])
		self.assertEqual(parts["committee"]["status"], "missing")
		self.assertEqual(parts["ic_department"]["status"], "ok")
		self.assertEqual(parts["surveillance"]["required"], 3)
		self.assertEqual(parts["surveillance"]["actual"], 2)  # chỉ chuyên trách đang hiệu lực
		self.assertEqual(parts["surveillance"]["status"], "missing")
		self.assertEqual(parts["surveillance"]["missing_count"], 1)
		self.assertEqual(parts["surveillance"]["status_label"], "Missing 1")
		self.assertEqual(parts["network"]["status"], "missing")
		self.assertEqual(parts["network"]["status_label"], "Missing 1 departments")
		self.assertEqual(result["missing_total"], 3)

	@bru("BRU-ICP-001")
	def test_small_hospital_committee_not_required(self):
		fx.settings(bed_count=120, ic_department=self.ic_dept, staff=[(self.staff[0], 1, 1)])
		parts = _by_key(structure.compute())
		self.assertEqual(parts["committee"]["status"], "optional")
		self.assertEqual(parts["committee"]["status_label"], "Not required")
		self.assertEqual(parts["ic_department"]["label"], "Infection Control Unit")
		self.assertEqual(parts["surveillance"]["required"], 1)
		self.assertEqual(parts["surveillance"]["status"], "ok")
		self.assertEqual(parts["surveillance"]["status_label"], "Sufficient")

	@bru("BRU-ICP-001")
	def test_outpatient_only_needs_one_person_in_charge(self):
		fx.settings(bed_count=10, has_inpatient=0, staff=[(self.staff[0], 0, 1)])
		result = structure.compute()
		parts = _by_key(result)
		for key in ("committee", "ic_department", "network"):
			self.assertEqual(parts[key]["status"], "na", key)
			self.assertEqual(parts[key]["status_label"], "Not applicable", key)
		self.assertEqual(parts["surveillance"]["label"], "IC Person in Charge")
		self.assertEqual(parts["surveillance"]["status"], "ok")  # người phụ trách không cần chuyên trách
		self.assertEqual(result["missing_total"], 0)
		self.assertEqual(result["departments"], [])

	@bru("BRU-ICP-003")
	def test_department_with_only_nurse_misses_doctor(self):
		fx.settings(bed_count=420, ic_department=self.ic_dept)
		departments = {row["department"]: row for row in structure.compute()["departments"]}
		self.assertNotIn(self.ic_dept, departments)  # khoa không có cờ không bị kiểm
		self.assertEqual(departments[self.dept_a]["status"], "ok")
		self.assertEqual((departments[self.dept_a]["doctors"], departments[self.dept_a]["nurses"]), (1, 1))
		self.assertEqual(departments[self.dept_b]["status"], "missing")
		self.assertEqual(departments[self.dept_b]["missing"], ["doctor"])
		self.assertEqual(departments[self.dept_b]["status_label"], "Missing doctor")

	@bru("BRU-ICP-003")
	def test_inactive_member_does_not_count(self):
		fx.settings(bed_count=420, ic_department=self.ic_dept)
		dept_c = fx.required_department("KSNK Test CĐHA")
		fx.network_member(fx.employee("NW C Doctor"), dept_c, "Doctor")
		fx.network_member(fx.employee("NW C Tech"), dept_c, "Technician", is_active=0)
		row = {r["department"]: r for r in structure.compute()["departments"]}[dept_c]
		self.assertEqual(row["missing"], ["nurse"])
		self.assertEqual(row["status_label"], "Missing nurse/midwife/technician")

	def test_missing_label_in_vietnamese_has_thieu(self):
		fx.settings(bed_count=420, ic_department=None)
		with local_context(lang="vi"):
			result = structure.compute()
		for row in result["components"]:
			if row["status"] == "missing":
				self.assertIn("Thiếu", row["status_label"], row["key"])
		for row in result["departments"]:
			if row["status"] == "missing":
				self.assertIn("Thiếu", row["status_label"], row["department"])

	def test_badges_count_missing_components(self):
		fx.settings(bed_count=420, ic_department=self.ic_dept)
		self.assertEqual(structure.badges("Administrator"), {"co-cau": 3})


class TestStructureGapsReport(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		fx.clear_required_departments()
		self.dept = fx.required_department("KSNK Test Sơ sinh")
		fx.network_member(fx.employee("Gap Nurse"), self.dept, "Nurse")

	@bru("BRU-ICP-001", "BRU-ICP-003")
	def test_each_gap_is_a_row_with_missing_word(self):
		fx.settings(bed_count=420)
		with local_context(lang="vi"):
			columns, data = ic_structure_gaps.execute({})
		codes = [row["issue_code"] for row in data]
		self.assertIn("COMMITTEE", codes)
		self.assertIn("IC_DEPARTMENT", codes)
		self.assertIn("SURVEILLANCE", codes)
		self.assertIn("NETWORK_DOCTOR", codes)
		self.assertNotIn("NETWORK", codes)  # khoa thiếu liệt kê từng khoa, không lặp dòng tổng
		for row in data:
			self.assertIn("Thiếu", row["issue"], row)
		self.assertIn("issue", [column["fieldname"] for column in columns])

	def test_complete_structure_has_no_rows(self):
		fx.network_member(fx.employee("Gap Doctor"), self.dept, "Doctor")
		ic_dept = fx.required_department("KSNK Test KSNK 2")
		frappe.db.set_value("Department", ic_dept, "tc_ic_network_required", 0)
		fx.settings(bed_count=120, ic_department=ic_dept, staff=[(fx.employee("Gap GSV"), 1, 1)])
		_columns, data = ic_structure_gaps.execute({})
		self.assertEqual(data, [])


# --- FEAT-094 (A-138): bộ tiêu chí cơ cấu TT 16/2018 ---------------------------------------------------------------


def _set_rounding(value):
	frappe.db.set_single_value("IC Program Settings", "surveillance_rounding", value)


class TestStructureRounding(IsolatedTestCase):
	@bru("BRU-ICP-001")
	def test_rounds_down_with_minimum_one(self):
		self.assertEqual(structure.required_surveillance(420, 150, "Down"), 2)
		self.assertEqual(structure.required_surveillance(449, 150, "Down"), 2)
		self.assertEqual(structure.required_surveillance(100, 150, "Down"), 1)
		self.assertEqual(structure.required_surveillance(420, 150, "Up"), 3)


class TestStructureWithoutProfile(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.db.sql("update `tabIC Structure Profile` set status = 'Draft'")
		fx.clear_required_departments()

	@bru("BRU-ICP-001")
	def test_counts_only_and_shows_notice(self):
		fx.settings(bed_count=420, staff=[(fx.employee("NP GSV"), 1, 1)])
		with local_context(lang="vi"):
			result = structure.compute()
		self.assertIsNone(result["profile"])
		self.assertEqual(result["profile_notice"], "Chưa duyệt bộ tiêu chí cơ cấu")
		self.assertEqual([row["key"] for row in result["components"]][-1], "surveillance")
		self.assertNotIn("head", [row["key"] for row in result["components"]])

	@bru("BRU-ICP-002")
	def test_committee_groups_not_checked_without_profile(self):
		members = [m for m in fx.full_committee_members("NP") if m[2] != "Pharmacy"]
		committee = fx.committee(members, submit=True)
		self.assertEqual(structure.missing_representatives(committee), [])
		fx.settings(bed_count=420)
		parts = _by_key(structure.compute())
		self.assertEqual(parts["committee"]["status"], "ok")

	def test_rounding_shown_in_requirement(self):
		fx.settings(bed_count=420)
		_set_rounding("Down")
		parts = _by_key(structure.compute())
		self.assertEqual(parts["surveillance"]["required"], 2)
		self.assertIn("rounded down", parts["surveillance"]["requirement"])


class TestStructureProfile(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		fx.clear_required_departments()
		self.ic_dept = fx.required_department("KSNK BTC Khoa KSNK")
		frappe.db.set_value("Department", self.ic_dept, "tc_ic_network_required", 0)
		self.ward = fx.required_department("KSNK BTC Nội")
		fx.network_member(fx.employee("BTC Doctor"), self.ward, "Doctor")
		fx.network_member(fx.employee("BTC Nurse"), self.ward, "Nurse")
		self.profile = fx.approved_profile()

	def _large(self, officers, extra=()):
		head = fx.qualified_employee("BTC Trưởng khoa")
		nurse = fx.qualified_employee("BTC ĐD trưởng")
		staff = [(head, 1, 1, "Head"), (nurse, 1, 1, "Head Nurse")]
		staff += [(emp, 1, 1, "Surveillance Officer") for emp in officers]
		fx.settings(bed_count=420, ic_department=self.ic_dept, staff=staff + list(extra))
		return head, nurse

	@bru("BRU-ICP-001", "BRU-ICP-006")
	def test_large_components_from_profile(self):
		self._large([fx.qualified_employee(f"BTC GSV {n}", "College") for n in range(3)])
		result = structure.compute()
		parts = _by_key(result)
		self.assertEqual(
			list(parts), ["committee", "ic_department", "network", "head", "head_nurse", "surveillance"]
		)
		self.assertEqual(result["profile"]["name"], self.profile.name)
		self.assertIsNone(result["profile_notice"])
		for key in ("head", "head_nurse", "surveillance"):
			self.assertEqual(parts[key]["status"], "ok", key)
		self.assertIn("Bachelor or higher", parts["head"]["requirement"])

	@bru("BRU-ICP-001")
	def test_ac04_rounding_up_and_down(self):
		self._large([fx.qualified_employee(f"BTC R {n}", "College") for n in range(2)])
		parts = _by_key(structure.compute())
		self.assertEqual(parts["surveillance"]["required"], 3)
		self.assertEqual(parts["surveillance"]["status_label"], "Missing 1")
		self.assertIn("rounded up", parts["surveillance"]["requirement"])
		_set_rounding("Down")
		parts = _by_key(structure.compute())
		self.assertEqual(parts["surveillance"]["required"], 2)
		self.assertEqual(parts["surveillance"]["status_label"], "Sufficient")

	@bru("BRU-ICP-006")
	def test_ac07_unqualified_head_not_counted_with_reason(self):
		head = fx.certified(fx.qualify(fx.employee("BTC TK Cao đẳng"), level="College"))
		fx.settings(bed_count=420, ic_department=self.ic_dept, staff=[(head, 1, 1, "Head")])
		with local_context(lang="vi"):
			part = _by_key(structure.compute())["head"]
		self.assertEqual(part["status"], "missing")
		self.assertIn("Thiếu", part["status_label"])
		self.assertEqual(part["people"][0]["status"], "fail")
		self.assertIn("Chưa đạt", part["reasons"])

	@bru("BRU-ICP-006")
	def test_ac09_unverified_not_counted_and_not_missing(self):
		officers = [fx.qualified_employee(f"BTC U {n}", "College") for n in range(2)]
		officers.append(fx.certified(fx.employee("BTC U chưa khai")))
		self._large(officers)
		with local_context(lang="vi"):
			result = structure.compute()
		part = _by_key(result)["surveillance"]
		self.assertEqual(part["actual"], 2)
		self.assertEqual(part["status"], "unverified")
		self.assertEqual(part["status_label"], "Chưa xác minh")
		self.assertEqual(part["missing_count"], 0)
		self.assertEqual(result["missing_total"], 1)  # chỉ Hội đồng thiếu

	@bru("BRU-ICP-007")
	def test_ac05_small_needs_person_in_charge_and_officer(self):
		pic = fx.qualified_employee("BTC Người phụ trách")
		fx.settings(bed_count=120, ic_department=self.ic_dept, staff=[(pic, 1, 1, "Person in Charge")])
		parts = _by_key(structure.compute())
		self.assertEqual(
			list(parts), ["committee", "ic_department", "network", "person_in_charge", "surveillance"]
		)
		self.assertEqual(parts["person_in_charge"]["status_label"], "Sufficient")
		self.assertEqual(parts["surveillance"]["status_label"], "Missing 1")
		self.assertEqual(parts["person_in_charge"]["label"], "IC Person in Charge (full-time)")

	@bru("BRU-ICP-007")
	def test_ac06_one_person_counted_for_one_role(self):
		pic = fx.qualified_employee("BTC Kiêm", "College")
		staff = [(pic, 1, 1, "Person in Charge"), (pic, 1, 1, "Surveillance Officer")]
		fx.settings(bed_count=120, ic_department=self.ic_dept, staff=staff)
		parts = _by_key(structure.compute())
		self.assertEqual(parts["person_in_charge"]["status"], "ok")
		self.assertEqual(parts["surveillance"]["status"], "missing")
		self.assertIn("Already counted for role", parts["surveillance"]["people"][0]["reasons"][0])

	@bru("BRU-ICP-007")
	def test_one_person_both_roles_when_allowed(self):
		frappe.db.sql("update `tabIC Structure Profile` set status = 'Draft'")
		fx.approved_profile(allow_one_person_both_roles=1)
		pic = fx.qualified_employee("BTC Kiêm OK", "College")
		staff = [(pic, 1, 1, "Person in Charge"), (pic, 1, 1, "Surveillance Officer")]
		fx.settings(bed_count=120, ic_department=self.ic_dept, staff=staff)
		self.assertEqual(_by_key(structure.compute())["surveillance"]["status"], "ok")

	def test_outpatient_person_in_charge_from_profile(self):
		fx.settings(
			bed_count=0, has_inpatient=0, staff=[(fx.employee("BTC PT NT"), 0, 1, "Person in Charge")]
		)
		parts = _by_key(structure.compute())
		self.assertEqual(parts["person_in_charge"]["status"], "ok")
		self.assertEqual(parts["person_in_charge"]["label"], "IC Person in Charge")
		self.assertNotIn("surveillance", parts)

	@bru("BRU-ICP-001", "BRU-ICP-003")
	def test_ac13_new_profile_applies_without_code_change(self):
		frappe.db.sql("update `tabIC Structure Profile` set status = 'Draft'")
		fx.approved_profile(committee_min_beds=0, network_rule="Any One Member")
		ward = fx.required_department("KSNK BTC Ngoại")
		fx.network_member(fx.employee("BTC Ngoại ĐD"), ward, "Nurse")
		fx.settings(bed_count=120, ic_department=self.ic_dept)
		result = structure.compute()
		parts = _by_key(result)
		self.assertEqual(parts["committee"]["status"], "missing")  # 0 = mọi cơ sở có nội trú
		self.assertEqual(parts["committee"]["requirement"], "Required (every facility with inpatient care)")
		self.assertEqual(result["scale"], "small")
		departments = {row["department"]: row for row in result["departments"]}
		self.assertEqual(departments[ward]["status"], "ok")
		self.assertEqual(parts["network"]["requirement"], "Each department ≥ 1 network member")

	def test_any_one_member_rule_lists_empty_department(self):
		frappe.db.sql("update `tabIC Structure Profile` set status = 'Draft'")
		fx.approved_profile(network_rule="Any One Member")
		empty = fx.required_department("KSNK BTC Trống")
		fx.settings(bed_count=420)
		row = {r["department"]: r for r in structure.compute()["departments"]}[empty]
		self.assertEqual(row["missing"], ["member"])
		self.assertEqual(row["status_label"], "Missing network member")

	def test_duplicate_staff_only_blocked_for_same_role(self):
		emp = fx.employee("BTC Trùng")
		fx.settings(staff=[(emp, 1, 1, "Head"), (emp, 1, 1, "Surveillance Officer")])
		with self.assertRaises(frappe.ValidationError):
			fx.settings(staff=[(emp, 1, 1, "Head"), (emp, 1, 1, "Head")])

	@bru("BRU-ICP-006")
	def test_ac14_report_lists_reason_per_person(self):
		head = fx.qualify(fx.certified(fx.employee("BTC BC TK")), level="College")
		fx.settings(bed_count=420, ic_department=self.ic_dept, staff=[(head, 1, 1, "Head")])
		with local_context(lang="vi"):
			columns, data = ic_structure_gaps.execute({})
		rows = [row for row in data if row["issue_code"] == "PERSON_FAIL"]
		self.assertEqual(len(rows), 1)
		self.assertIn("Chưa đạt", rows[0]["reason"])
		self.assertIn("HEAD", [row["issue_code"] for row in data])
		self.assertIn("reason", [column["fieldname"] for column in columns])
