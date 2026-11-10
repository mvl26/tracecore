"""RPC tracecore.v1.hai_prevalence.* — điều tra cắt ngang trên SCR-58 (FEAT-072 AC-8..AC-12; FR-M13-14; UC-50 bước 5,
6, E2, E3; BRU-HAI-005, BRU-RPT-001; NFR-PRIV-01; A-149 Q1)."""

import json

import frappe
from frappe.utils import add_days, today

from tracecore.compliance_audit import prevalence as survey
from tracecore.hai_surveillance.tests import factories as hf
from tracecore.hai_surveillance.tests.test_prevalence import survey_template
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase, bru
from tracecore.v1 import hai_prevalence

CODE = "BN-2000000001"


class TestHaiPrevalenceApi(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.local.lang = "en"
		frappe.db.sql(
			"update `tabAudit Session` set docstatus = 2 where docstatus = 1 and audit_date >= %s",
			add_days(today(), -40),
		)
		self.ward = hf.make_ward("KSNK PPS Api 072")
		survey_template()
		self.r11 = factories.make_user("api072-r11@test.local", [hf.R11])
		factories.make_employee(first_name="PPS 072 R11", user_id=self.r11)
		self.r13 = factories.make_user("api072-r13@test.local", [hf.R13])
		self.r12 = factories.make_user("api072-r12@test.local", [hf.R12])

	@bru("BRU-HAI-005")
	def test_record_by_patient_code_and_overview_masked(self):
		frappe.set_user(self.r11)
		body = hai_prevalence.record(today(), self.ward, hai="Yes", antibiotic="Yes", patient_code=CODE)
		self.assertTrue(body["ok"], body)
		self.assertEqual(body["patient_code_masked"], "***0001")
		self.assertEqual(frappe.db.get_value("Audit Session", body["name"], "docstatus"), 1)
		data = hai_prevalence.overview(today())
		self.assertTrue(data["can_record"])
		row = next(row for row in data["departments"] if row["department"] == self.ward)
		self.assertEqual((row["surveyed"], row["hai"], row["rate"]), (1, 1, 100.0))
		self.assertNotIn(CODE, json.dumps(data, default=str))

	def test_record_from_episode_and_candidates(self):
		episode = hf.make_episode(self.ward, code="BN-2000000002")
		frappe.set_user(self.r11)
		rows = hai_prevalence.candidates(today(), self.ward)["candidates"]
		self.assertEqual([row["patient_code_masked"] for row in rows], ["***0002"])
		self.assertNotIn("BN-2000000002", json.dumps(rows, default=str))
		body = hai_prevalence.record(today(), self.ward, hai="No", device_episode=episode.name)
		self.assertTrue(body["ok"], body)
		self.assertEqual(hai_prevalence.candidates(today(), self.ward)["candidates"], [])

	def test_duplicate_is_rejected_inline(self):
		frappe.set_user(self.r11)
		hai_prevalence.record(today(), self.ward, hai="No", patient_code=CODE)
		body = hai_prevalence.record(today(), self.ward, hai="Yes", patient_code=CODE)
		self.assertFalse(body["ok"])
		self.assertEqual(body["error"]["code"], "PREVALENCE_DUPLICATE")
		self.assertTrue(body["error"]["action"])

	def test_future_date_rejected(self):
		frappe.set_user(self.r11)
		body = hai_prevalence.record(add_days(today(), 1), self.ward, hai="No", patient_code=CODE)
		self.assertFalse(body["ok"])
		self.assertEqual(body["error"]["code"], "PREVALENCE_NOT_ALLOWED")

	def test_no_approved_template(self):
		frappe.set_user(self.r11)
		codes = survey.template_codes()
		frappe.db.sql(
			"update `tabAudit Template` set docstatus = 0 where template_code in %(codes)s", {"codes": codes}
		)
		body = hai_prevalence.record(today(), self.ward, hai="No", patient_code=CODE)
		self.assertEqual(body["error"]["code"], "PREVALENCE_TEMPLATE_MISSING")
		self.assertIsNone(hai_prevalence.overview(today())["template"])

	def test_user_without_employee_rejected(self):
		user = factories.make_user("api072-r01@test.local", ["TC R01"])
		frappe.set_user(user)
		body = hai_prevalence.record(today(), self.ward, hai="No", patient_code=CODE)
		self.assertEqual(body["error"]["code"], "PREVALENCE_NOT_ALLOWED")

	def test_r13_reads_overview_but_cannot_record(self):
		frappe.set_user(self.r13)
		data = hai_prevalence.overview()
		self.assertFalse(data["can_record"])
		with self.assertRaises(frappe.PermissionError):
			hai_prevalence.record(today(), self.ward, hai="No", patient_code=CODE)
		with self.assertRaises(frappe.PermissionError):
			hai_prevalence.candidates(today(), self.ward)

	def test_r12_cannot_open(self):
		frappe.set_user(self.r12)
		with self.assertRaises(frappe.PermissionError):
			hai_prevalence.overview()

	def test_overview_defaults_to_latest_survey_date(self):
		frappe.set_user(self.r11)
		hai_prevalence.record(add_days(today(), -2), self.ward, hai="No", patient_code=CODE)
		data = hai_prevalence.overview()
		self.assertEqual(str(data["date"]), add_days(today(), -2))
		self.assertIn(str(data["dates"][0]), (add_days(today(), -2), today()))
