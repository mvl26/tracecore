"""Điều kiện từng người theo vai trò (FEAT-094 AC-094-07..09; FR-M11-01.5; BRU-ICP-006; OQ-V12-12, 14)."""

import frappe
from frappe.utils import add_days, today

from tracecore.infection_program import qualification, structure_seed
from tracecore.infection_program import training as training_service
from tracecore.infection_program.tests import ic_fixtures as fx
from tracecore.infection_program.tests import training_fixtures as tfx
from tracecore.tests.utils import IsolatedTestCase, bru


def _requirement(role, applies_to):
	for row_role, row_applies, conditions in structure_seed.ROLES:
		if (row_role, row_applies) == (role, applies_to):
			return frappe._dict(ic_role=role, applies_to=applies_to, certificate_types="", **conditions)
	raise AssertionError(role)


def _row(employee, full_time=1):
	return frappe._dict(employee=employee, employee_name=None, full_time=full_time, is_active=1)


def _one(employee, requirement, full_time=1):
	return qualification.evaluate([_row(employee, full_time)], requirement)[0]


class TestQualification(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		tfx.accept_certificates("Chứng chỉ KSNK")
		self.head = _requirement("Head", "Large")
		self.officer = _requirement("Surveillance Officer", "Large")

	@bru("BRU-ICP-006")
	def test_head_with_bachelor_health_certificate_full_time_is_ok(self):
		person = _one(fx.qualified_employee("TK Đạt"), self.head)
		self.assertEqual((person["status"], person["reasons"]), ("ok", []))

	@bru("BRU-ICP-006")
	def test_head_below_bachelor_fails_with_reason(self):
		employee = fx.qualified_employee("TK Cao đẳng", level="College")
		person = _one(employee, self.head)
		self.assertEqual(person["status"], "fail")
		self.assertEqual(person["reasons"], ["Not met: education below Bachelor"])

	@bru("BRU-ICP-006")
	def test_head_not_health_field_or_not_full_time_fails(self):
		employee = fx.certified(fx.qualify(fx.employee("TK Ngoài ngành"), health=0))
		person = _one(employee, self.head, full_time=0)
		self.assertEqual(person["status"], "fail")
		self.assertEqual(
			person["reasons"], ["Not met: not full-time", "Not met: not a health-field graduate"]
		)

	@bru("BRU-ICP-006")
	def test_expired_certificate_fails(self):
		employee = fx.qualify(fx.employee("TK Hết hạn"))
		tfx.certificate(employee, "Chứng chỉ KSNK", expires_on=add_days(today(), -1))
		person = _one(employee, self.head)
		self.assertEqual(person["status"], "fail")
		self.assertEqual(person["reasons"], ["Not met: IC certificate no longer valid"])

	@bru("BRU-ICP-006")
	def test_surveillance_officer_college_with_core_training_is_ok(self):
		employee = fx.qualify(fx.employee("GSV Cao đẳng"), level="College")
		tfx.trained([employee], training_service.CORE_STAFF, on=add_days(today(), -100))
		self.assertEqual(_one(employee, self.officer)["status"], "ok")

	@bru("BRU-ICP-006")
	def test_surveillance_officer_vocational_fails(self):
		employee = fx.qualified_employee("GSV Trung cấp", level="Vocational")
		person = _one(employee, self.officer)
		self.assertEqual(person["reasons"], ["Not met: education below College"])

	@bru("BRU-ICP-006")
	def test_missing_education_level_is_unverified(self):
		employee = fx.certified(fx.employee("GSV Chưa khai"))
		person = _one(employee, self.officer)
		self.assertEqual(person["status"], "unverified")
		self.assertEqual(person["reasons"], ["Not verified: no education level"])

	@bru("BRU-ICP-006")
	def test_missing_certificate_is_unverified(self):
		person = _one(fx.qualify(fx.employee("GSV Chưa CC"), level="College"), self.officer)
		self.assertEqual(person["status"], "unverified")
		self.assertEqual(person["reasons"], ["Not verified: no IC certificate"])

	@bru("BRU-ICP-006")
	def test_fail_wins_over_unverified(self):
		person = _one(fx.qualify(fx.employee("GSV Kiêm nhiệm"), level="College"), self.officer, full_time=0)
		self.assertEqual(person["status"], "fail")
		self.assertEqual(person["reasons"], ["Not met: not full-time", "Not verified: no IC certificate"])

	def test_requirement_certificate_types_override_settings(self):
		employee = fx.qualify(fx.employee("GSV Loại riêng"), level="College")
		tfx.certificate(employee, "Chứng chỉ giám sát")
		requirement = frappe._dict(self.officer, certificate_types="Chứng chỉ giám sát")
		self.assertEqual(_one(employee, requirement)["status"], "ok")
		self.assertEqual(_one(employee, self.officer)["status"], "unverified")

	def test_outpatient_person_in_charge_has_no_condition(self):
		person = _one(
			fx.employee("PT Ngoại trú"), _requirement("Person in Charge", "Outpatient"), full_time=0
		)
		self.assertEqual(person["status"], "ok")

	def test_education_rank_order(self):
		ranks = [qualification.education_rank(level) for level in qualification.EDUCATION_ORDER]
		self.assertEqual(ranks, sorted(ranks))
		self.assertEqual(qualification.education_rank(None), -1)
