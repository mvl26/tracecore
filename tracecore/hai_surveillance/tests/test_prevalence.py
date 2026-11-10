"""Tổng hợp điều tra cắt ngang (FEAT-072 AC-8, AC-10; FR-M13-14; UC-50 bước 5, 6, E2; BRU-RPT-001; A-149 Q1).

Phiếu cắt ngang tạo bằng `frappe.get_doc` (không import M12), mẫu có mục ``PREV-HAI`` / ``PREV-ABX``.
"""

import frappe
from frappe.utils import add_days, getdate, today

from tracecore.hai_surveillance import prevalence
from tracecore.hai_surveillance.tests import factories as hf
from tracecore.tests.utils import IsolatedTestCase, bru

test_ignore = ["Item", "Batch", "Supplier", "Incident CAPA", "Department", "User", "Employee"]


def survey_template(code="T-CAT-M13"):
	name = frappe.db.get_value("Audit Template", {"template_code": code, "docstatus": 1}, "name")
	if name:
		return name
	doc = frappe.get_doc(
		{
			"doctype": "Audit Template",
			"template_code": code,
			"title": "Point prevalence survey",
			"audit_type": "Other",
			"scoring_method": "Weighted Score",
			"effective_from": add_days(today(), -60),
			"items": [
				{
					"item_code": item,
					"question": item,
					"answer_type": "Choice",
					"options": "Yes\nNo",
					"weight": 0,
				}
				for item in (prevalence.HAI_ITEM, prevalence.ABX_ITEM)
			],
		}
	).insert(ignore_permissions=True)
	doc.submit()
	return doc.name


def record(department, code, hai="No", abx="No", on=None, episode=None):
	doc = frappe.get_doc(
		{
			"doctype": "Audit Session",
			"audit_template": survey_template(),
			"department": department,
			"audit_date": on or today(),
			"observer": hf.observer(),
			"patient_code": code if not episode else None,
			"device_episode": episode,
			"answers": [
				{"item_code": prevalence.HAI_ITEM, "value": hai},
				{"item_code": prevalence.ABX_ITEM, "value": abx},
			],
		}
	).insert(ignore_permissions=True)
	doc.submit()
	return doc


class TestPrevalence(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.local.lang = "en"
		frappe.db.sql(
			"update `tabAudit Session` set docstatus = 2 where audit_date >= %s and docstatus = 1",
			add_days(today(), -40),
		)
		self.icu = hf.make_ward("KSNK PPS ICU 072")
		self.surg = hf.make_ward("KSNK PPS Ngoại 072")

	@bru("BRU-RPT-001")
	def test_rate_by_department_and_hospital(self):
		record(self.icu, "BN-1000000001", hai="Yes", abx="Yes")
		record(self.icu, "BN-1000000002", hai="No", abx="Yes")
		record(self.icu, "BN-1000000003", hai="Yes", abx="No")
		record(self.icu, "BN-1000000004", hai="No", abx="No")
		record(self.surg, "BN-1000000005", hai="No", abx="Yes")
		data = prevalence.by_department(today())
		rows = {row["department"]: row for row in data["departments"]}
		icu = rows[self.icu]
		self.assertEqual((icu["surveyed"], icu["hai"], icu["antibiotic"]), (4, 2, 2))
		self.assertEqual(icu["rate"], 50.0)
		self.assertEqual(icu["antibiotic_rate"], 50.0)
		self.assertEqual(rows[self.surg]["rate"], 0.0)
		self.assertEqual((data["hospital"]["surveyed"], data["hospital"]["hai"]), (5, 2))
		self.assertEqual(data["hospital"]["rate"], 40.0)

	@bru("BRU-RPT-001")
	def test_no_survey_is_not_calculated(self):
		data = prevalence.by_department(add_days(today(), -20))
		self.assertEqual(data["departments"], [])
		self.assertEqual(data["hospital"]["surveyed"], 0)
		self.assertIsNone(data["hospital"]["rate"])

	def test_survey_dates_newest_first(self):
		record(self.icu, "BN-1000000011", on=add_days(today(), -3))
		record(self.icu, "BN-1000000012")
		record(self.surg, "BN-1000000013")
		self.assertEqual(prevalence.survey_dates()[:2], [getdate(today()), getdate(add_days(today(), -3))])

	def test_candidates_are_open_episodes_not_yet_surveyed(self):
		vent = hf.make_episode(self.icu, code="BN-1000000021", device="Ventilator")
		hf.make_episode(self.icu, code="BN-1000000021", device="Urinary Catheter")
		other = hf.make_episode(self.icu, code="BN-1000000022", device="Central Line")
		hf.make_episode(
			self.icu,
			code="BN-1000000023",
			inserted_on=add_days(today(), -9),
			removed_on=add_days(today(), -3),
			status="Closed",
		)
		hf.make_episode(self.surg, code="BN-1000000024")
		rows = prevalence.candidates(today(), self.icu)
		self.assertEqual(sorted(row["patient_code_masked"] for row in rows), ["***0021", "***0022"])
		first = next(row for row in rows if row["patient_code_masked"] == "***0021")
		self.assertEqual(len(first["episodes"]), 2)
		self.assertNotIn("patient_code_hash", first)
		record(self.icu, None, episode=vent.name)
		rows = prevalence.candidates(today(), self.icu)
		self.assertEqual([row["episodes"][0]["name"] for row in rows], [other.name])

	def test_indicator_by_month(self):
		record(self.icu, "BN-1000000031", hai="Yes")
		record(self.icu, "BN-1000000032")
		record(self.surg, "BN-1000000033")
		period = today()[:7]
		self.assertEqual(prevalence.hai_prevalence(period), (1, 3, 3))
		self.assertEqual(prevalence.hai_prevalence(period, self.icu), (1, 2, 2))
		self.assertEqual(prevalence.hai_prevalence("2001-01"), (0, 0, 0))
		from tracecore.core import indicators

		self.assertIs(indicators.registry()[prevalence.INDICATOR_KEY], prevalence.hai_prevalence)

	def test_regular_audits_are_not_counted(self):
		record(self.icu, "BN-1000000041", hai="Yes")
		hf.post_bundle(hf.make_episode(self.icu, code="BN-1000000042"))
		self.assertEqual(prevalence.by_department(today())["hospital"]["surveyed"], 1)
