"""Phiếu điều tra cắt ngang trên engine M12 (FEAT-072 AC-9, AC-11; FR-M13-14, FR-M13-14.1; UC-50 bước 5, 6, E3;
BRU-HAI-005, NFR-PRIV-01; A-149 Q1).

Mỗi người bệnh = 1 `Audit Session` của mẫu có mục ``PREV-HAI``; mã BN ở bộ ba trường Password/che/hash của phiếu, hoặc
chép từ `Device Episode` cùng khoa đang đặt vào ngày điều tra.
"""

import json
import pathlib
from unittest.mock import patch

import frappe
from frappe.utils import add_days, today

from tracecore.compliance_audit import pda, prevalence, seed, sessions
from tracecore.compliance_audit.tests import factories as af
from tracecore.core.errors import BlockedError
from tracecore.hai_surveillance.tests import factories as hf
from tracecore.tests.utils import IsolatedTestCase, bru

test_ignore = ["Item", "Batch", "Supplier", "Incident CAPA", "Department", "User", "Employee"]

SURVEY_ITEMS = [
	{
		"item_code": prevalence.HAI_ITEM,
		"section": "Survey",
		"question": "HAI",
		"answer_type": "Choice",
		"options": "Yes\nNo",
		"weight": 0,
	},
	{
		"item_code": prevalence.ABX_ITEM,
		"section": "Survey",
		"question": "Antibiotics",
		"answer_type": "Choice",
		"options": "Yes\nNo",
		"weight": 0,
	},
]


def survey_template(code="T-CAT-072"):
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
			"effective_from": add_days(today(), -30),
			"items": SURVEY_ITEMS,
		}
	).insert(ignore_permissions=True)
	doc.submit()
	return doc.name


def session(
	department, hai="No", abx="No", code="BN-0000009001", episode=None, on=None, submit=True, **values
):
	doc = frappe.get_doc(
		{
			"doctype": "Audit Session",
			"audit_template": survey_template(),
			"department": department,
			"audit_date": on or today(),
			"observer": hf.observer(),
			"patient_code": code,
			"device_episode": episode,
			"answers": [
				{"item_code": prevalence.HAI_ITEM, "value": hai},
				{"item_code": prevalence.ABX_ITEM, "value": abx},
			],
			**values,
		}
	).insert(ignore_permissions=True)
	if submit:
		doc.submit()
	return doc


class TestPrevalenceSession(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.local.lang = "en"
		self.ward = hf.make_ward("KSNK CN Hồi sức 072")

	def test_patient_fields_on_audit_session(self):
		meta = frappe.get_meta("Audit Session")
		self.assertEqual(meta.get_field("patient_code").fieldtype, "Password")
		self.assertTrue(meta.get_field("patient_code_masked").read_only)
		self.assertTrue(meta.get_field("patient_code_hash").hidden)

	@bru("BRU-HAI-005")
	def test_no_patient_name_field(self):
		path = pathlib.Path(frappe.get_app_path("tracecore", "compliance_audit", "doctype", "audit_session"))
		fields = {row["fieldname"] for row in json.loads((path / "audit_session.json").read_text())["fields"]}
		self.assertFalse({name for name in fields if "patient_name" in name or "full_name" in name})

	@bru("BRU-HAI-005")
	def test_patient_code_is_encrypted_hashed_and_masked(self):
		doc = session(self.ward, code="bn-0000009001")
		self.assertEqual(doc.patient_code_masked, "***9001")
		self.assertTrue(doc.patient_code_hash)
		stored = frappe.db.get_value("Audit Session", doc.name, "patient_code")
		self.assertNotIn("9001", str(stored or ""))
		self.assertEqual(doc.docstatus, 1)
		self.assertIsNone(doc.result)

	def test_is_prevalence_by_item(self):
		doc = session(self.ward, submit=False)
		self.assertTrue(prevalence.is_prevalence(doc))
		template = af.make_template("T-PNC-072")
		self.assertTrue(prevalence.is_prevalence_template(survey_template()))
		self.assertFalse(prevalence.is_prevalence_template(template.name))

	@bru("BRU-HAI-005")
	def test_regular_audit_rejects_patient_code(self):
		template = af.make_template("T-PNC-072")
		with self.assertRaises(BlockedError) as ctx:
			frappe.get_doc(
				{
					"doctype": "Audit Session",
					"audit_template": template.name,
					"department": self.ward,
					"observer": hf.observer(),
					"patient_code": "BN-0000009001",
				}
			).insert(ignore_permissions=True)
		self.assertEqual(ctx.exception.block.code, "PREVALENCE_PATIENT_NOT_ALLOWED")

	def test_patient_required(self):
		with self.assertRaises(BlockedError) as ctx:
			session(self.ward, code=None)
		self.assertEqual(ctx.exception.block.code, "PREVALENCE_PATIENT_REQUIRED")

	def test_patient_from_open_device_episode(self):
		episode = hf.make_episode(self.ward, code="BN-0000009002")
		doc = session(self.ward, code=None, episode=episode.name, hai="Yes")
		self.assertEqual(doc.patient_code_masked, "***9002")
		self.assertEqual(
			doc.patient_code_hash, frappe.db.get_value("Device Episode", episode.name, "patient_code_hash")
		)

	def test_episode_of_other_department_or_closed_rejected(self):
		other = hf.make_ward("KSNK CN Ngoại 072")
		episode = hf.make_episode(other, code="BN-0000009003")
		with self.assertRaises(BlockedError) as ctx:
			session(self.ward, code=None, episode=episode.name)
		self.assertEqual(ctx.exception.block.code, "PREVALENCE_EPISODE_INVALID")
		closed = hf.make_episode(
			self.ward,
			code="BN-0000009004",
			inserted_on=add_days(today(), -9),
			removed_on=add_days(today(), -2),
			status="Closed",
		)
		with self.assertRaises(BlockedError):
			session(self.ward, code=None, episode=closed.name)

	def test_episode_of_other_patient_rejected(self):
		episode = hf.make_episode(self.ward, code="BN-0000009005")
		with self.assertRaises(BlockedError) as ctx:
			session(self.ward, code="BN-0000009006", episode=episode.name)
		self.assertEqual(ctx.exception.block.code, "PREVALENCE_EPISODE_INVALID")

	def test_same_patient_same_day_is_duplicate(self):
		session(self.ward, code="BN-0000009007")
		with self.assertRaises(BlockedError) as ctx:
			session(self.ward, code="BN-0000009007")
		self.assertEqual(ctx.exception.block.code, "PREVALENCE_DUPLICATE")
		# ngày khác thì được
		self.assertTrue(session(self.ward, code="BN-0000009007", on=add_days(today(), -1)).name)

	def test_hai_answer_required_to_post(self):
		doc = session(self.ward, hai="", submit=False)
		with self.assertRaises(BlockedError) as ctx:
			doc.submit()
		self.assertEqual(ctx.exception.block.code, "PREVALENCE_ANSWER_MISSING")

	def test_invalid_choice_rejected(self):
		with self.assertRaises(BlockedError) as ctx:
			session(self.ward, hai="Maybe")
		self.assertEqual(ctx.exception.block.code, "PREVALENCE_ANSWER_MISSING")

	def test_no_department_feedback_for_survey(self):
		with patch.object(sessions.feedback, "after_submit") as feedback:
			session(self.ward)
		feedback.assert_not_called()
		with patch.object(sessions.feedback, "after_submit") as feedback:
			doc = frappe.get_doc(
				{
					"doctype": "Audit Session",
					"audit_template": af.make_template("T-PNC-072").name,
					"department": self.ward,
					"observer": hf.observer(),
					"answers": af.answers(**{f"PNC-0{i}": "Pass" for i in range(1, 6)}),
				}
			).insert(ignore_permissions=True)
			doc.submit()
		feedback.assert_called_once()

	def test_pda_does_not_offer_survey_templates(self):
		name = survey_template()
		self.assertNotIn(name, [row.name for row in pda.active_templates(today())])

	def test_month_sample_still_counts(self):
		doc = session(self.ward)
		self.assertEqual(sessions.month_sample(doc.template_code, self.ward, today()), 1)


class TestSurveySeed(IsolatedTestCase):
	def test_seed_has_two_draft_survey_templates(self):
		seed.ensure_seed()
		rows = {
			row.template_code: row
			for row in frappe.get_all(
				"Audit Template",
				filters={"template_code": ["in", list(seed.SURVEY_TEMPLATES)]},
				fields=["name", "template_code", "audit_type", "docstatus", "legal_ref"],
			)
		}
		self.assertEqual(set(rows), {"TDG-KSNK", "CAT-NGANG"})
		self.assertEqual(rows["TDG-KSNK"].audit_type, "Quality Self-Assessment")
		self.assertEqual(rows["CAT-NGANG"].audit_type, "Other")
		self.assertEqual({row.docstatus for row in rows.values()}, {0})
		self.assertTrue(prevalence.is_prevalence_template(rows["CAT-NGANG"].name))
		self.assertFalse(prevalence.is_prevalence_template(rows["TDG-KSNK"].name))

	def test_survey_texts_translated(self):
		missing = [text for text in seed.survey_source_texts() if frappe._(text, "vi") == text]
		self.assertEqual([text for text in missing if not text.startswith(("TT ", "QD "))], [])
