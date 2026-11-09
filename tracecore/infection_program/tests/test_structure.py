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
