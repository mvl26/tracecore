"""Ca NKBV Nghi ngờ → Xác định / Loại trừ, kiểm ngưỡng thời gian, che mã BN (FEAT-063; FR-M13-05, 05.1, 05.2, 06,
06.1, 15, 15.1; BRU-HAI-001, BRU-HAI-005; NFR-PRIV-01; A-144 Q2)."""

import json
import pathlib

import frappe

from tracecore.core.errors import BlockedError
from tracecore.hai_surveillance import cases
from tracecore.hai_surveillance.tests import factories as f
from tracecore.hai_surveillance.tests import hai_fixtures as h
from tracecore.tests.utils import IsolatedTestCase, bru

DOCTYPE_DIR = pathlib.Path(frappe.get_app_path("tracecore", "hai_surveillance", "doctype"))
NAME_WORDS = ("patient_name", "full_name", "ho_ten", "first_name", "last_name")


class CaseTestBase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		h.clear_definitions("TVAP")
		self.v1 = h.make_definition("TVAP", effective_from="2026-01-01")
		self.ward = f.make_ward("KSNK Case ICU")
		self.r11 = f.factories.make_user("case-r11@test.local", [h.R11])
		self.r01 = f.factories.make_user("case-r01@test.local", [h.R01])
		self.r12 = f.make_dept_user("case-r12@test.local", h.R12, self.ward)

	def block(self, fn, *args, **kwargs):
		with self.assertRaises(BlockedError) as caught:
			fn(*args, **kwargs)
		return caught.exception.block


class TestCaseDefinitionSnapshot(CaseTestBase):
	@bru("BRU-HAI-001")
	def test_case_gets_version_effective_at_onset(self):
		v2 = h.make_definition("TVAP", effective_from="2026-10-15", hours=72)
		before = h.make_case(self.ward, onset="2026-10-10", admitted="2026-10-01 08:00:00")
		after = h.make_case(self.ward, onset="2026-10-20", code="BN-0000009999")
		self.assertEqual(before.case_definition, self.v1.name)  # FR-M13-01.1
		self.assertEqual(after.case_definition, v2.name)
		self.assertEqual(after.reporting_period, "2026-10")

	def test_no_approved_definition_blocks(self):
		block = self.block(h.make_case, self.ward, onset="2025-06-01", admitted="2025-05-20 08:00:00")
		self.assertEqual(block.code, "HAI_CASE_DEFINITION_MISSING")

	def test_onset_before_admission_day_blocked(self):
		block = self.block(h.make_case, self.ward, onset="2026-10-10", admitted="2026-10-12 08:00:00")
		self.assertEqual(block.code, "HAI_CASE_DATE_INVALID")

	def test_draft_is_suspected(self):
		doc = h.make_case(self.ward)
		self.assertEqual(doc.status, cases.SUSPECTED)
		self.assertEqual(doc.docstatus, 0)


class TestTimeCheck(CaseTestBase):
	@bru("BRU-HAI-001")
	def test_met_with_device_days_and_hours_from_definition(self):
		episode = h.make_episode(self.ward, inserted_on="2026-10-16")
		doc = h.make_case(self.ward, onset="2026-10-20", device_episode=episode.name)
		self.assertEqual(doc.time_check, cases.MET)
		self.assertIn("4", doc.time_check_note)

	@bru("BRU-HAI-001")
	def test_not_met_hours_after_admission(self):
		doc = h.make_case(self.ward, onset="2026-10-20", admitted="2026-10-19 20:00:00")
		self.assertEqual(doc.time_check, cases.NOT_MET)

	def test_threshold_comes_from_definition_not_code(self):
		h.make_definition("TVAP", effective_from="2026-10-01", hours=6, days=0)
		doc = h.make_case(self.ward, onset="2026-10-20", admitted="2026-10-19 08:00:00")
		self.assertEqual(doc.time_check, cases.MET)  # FR-M13-06.1: ngưỡng 6 giờ của V2

	def test_missing_device_episode_when_definition_needs_device(self):
		doc = h.make_case(self.ward, onset="2026-10-20")
		self.assertEqual(doc.time_check, cases.NOT_MET)

	def test_episode_of_other_patient_rejected(self):
		episode = h.make_episode(self.ward, inserted_on="2026-10-16", code="BN-OTHER-0001")
		block = self.block(h.make_case, self.ward, device_episode=episode.name)
		self.assertEqual(block.code, "HAI_CASE_EPISODE_INVALID")


class TestDecision(CaseTestBase):
	def _met_case(self, **values):
		episode = h.make_episode(self.ward, inserted_on="2026-10-16")
		return h.make_case(self.ward, device_episode=episode.name, **values)

	def test_r11_confirms_and_records_confirmer(self):
		doc = self._met_case()
		frappe.set_user(self.r11)
		cases.decide(doc.name, cases.CONFIRMED)
		frappe.set_user("Administrator")
		doc.reload()
		self.assertEqual(doc.docstatus, 1)
		self.assertEqual(doc.status, cases.CONFIRMED)
		self.assertEqual(doc.confirmed_by, self.r11)
		self.assertTrue(doc.confirmed_on)

	def test_r12_cannot_confirm(self):
		doc = self._met_case()
		frappe.set_user(self.r12)
		block = self.block(cases.decide, doc.name, cases.CONFIRMED)
		self.assertEqual(block.code, "HAI_CASE_NOT_ALLOWED")  # FR-M13-05.1
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("HAI Case", doc.name, "docstatus"), 0)

	def test_exclude_requires_reason(self):
		doc = self._met_case()
		frappe.set_user(self.r11)
		block = self.block(cases.decide, doc.name, cases.EXCLUDED, reason="  ")
		self.assertEqual(block.code, "HAI_CASE_REASON_REQUIRED")  # FR-M13-05.2
		cases.decide(doc.name, cases.EXCLUDED, reason="Viêm phổi cộng đồng")
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("HAI Case", doc.name, "status"), cases.EXCLUDED)

	@bru("BRU-HAI-001")
	def test_not_met_needs_exception_reason(self):
		doc = h.make_case(self.ward, onset="2026-10-20", admitted="2026-10-19 20:00:00")
		frappe.set_user(self.r11)
		block = self.block(cases.decide, doc.name, cases.CONFIRMED)
		self.assertEqual(block.code, "HAI_CASE_EXCEPTION_REQUIRED")
		cases.decide(doc.name, cases.CONFIRMED, exception_reason="Ca chuyển viện, giờ nhập viện ghi sai")
		frappe.set_user("Administrator")
		self.assertTrue(
			frappe.db.exists(
				"Audit Log", {"ref_doctype": "HAI Case", "ref_name": doc.name, "action": "Override"}
			)
		)

	def test_plain_submit_without_decision_blocked(self):
		doc = self._met_case()
		block = self.block(doc.submit)
		self.assertEqual(block.code, "HAI_CASE_DECISION_REQUIRED")

	def test_outcome_editable_after_submit_but_not_onset(self):
		doc = self._met_case()
		cases.decide(doc.name, cases.CONFIRMED)
		doc.reload()
		doc.outcome = "Recovered"
		doc.save(ignore_permissions=True)
		doc.reload()
		doc.onset_date = "2026-10-21"
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)


class TestIsolatesAndPrivacy(CaseTestBase):
	def test_link_isolate_of_same_patient_merges_flags(self):
		doc = h.make_case(self.ward)
		isolate = h.make_isolate(self.ward, flags="CRE")
		cases.link_isolate(doc.name, isolate.name)
		doc.reload()
		self.assertEqual([row.isolate for row in doc.isolates], [isolate.name])
		self.assertEqual(doc.mdro_flags, "CRE")

	def test_resistance_report_rate_of_confirmed_cases_with_pathogen(self):
		"""A-136 Q8 / A-144 i: báo cáo kháng thuốc M14 đọc ca qua frappe.db (gọi bằng đường dẫn, không import M14)."""
		rate = frappe.get_attr("tracecore.microbiology.resistance.hai_with_pathogen_rate")
		frappe.db.delete("HAI Case", {"reporting_period": ["in", ["2026-10", "2026-11", "2026-12"]]})
		self.assertIsNone(rate(2026, 4))
		episode = h.make_episode(self.ward, inserted_on="2026-10-16")
		with_isolate = h.make_case(self.ward, device_episode=episode.name)
		cases.link_isolate(with_isolate.name, h.make_isolate(self.ward, lab="L-063-5").name)
		cases.decide(with_isolate.name, cases.CONFIRMED)
		other = h.make_case(
			self.ward, code="BN-0000003333", onset="2026-10-25", admitted="2026-10-01 08:00:00"
		)
		cases.decide(other.name, cases.CONFIRMED, exception_reason="test")
		self.assertEqual(rate(2026, 4), 50.0)

	def test_link_isolate_of_other_patient_blocked(self):
		doc = h.make_case(self.ward)
		isolate = h.make_isolate(self.ward, patient="BN-OTHER-0002", lab="L-063-9")
		block = self.block(cases.link_isolate, doc.name, isolate.name)
		self.assertEqual(block.code, "HAI_CASE_ISOLATE_INVALID")

	def test_mdro_hook_labels_cases_of_patient(self):
		doc = h.make_case(self.ward)
		isolate = h.make_isolate(self.ward, lab="L-063-2", flags="MRSA")
		cases.on_mdro_detected(isolate)
		self.assertEqual(frappe.db.get_value("HAI Case", doc.name, "mdro_flags"), "MRSA")
		self.assertIn(
			"tracecore.hai_surveillance.cases.on_mdro_detected", frappe.get_hooks("tracecore_mdro_detected")
		)

	@bru("BRU-HAI-005")
	def test_only_masked_code_in_list(self):
		doc = h.make_case(self.ward, code="BN-0000004821")
		row = frappe.db.get_value("HAI Case", doc.name, ["patient_code", "patient_code_masked"], as_dict=True)
		self.assertNotIn("4821", row.patient_code or "")
		self.assertEqual(row.patient_code_masked, "***4821")
		rows = cases.list_rows({"department": self.ward})
		self.assertNotIn("BN-0000004821", json.dumps(rows, default=str))

	@bru("BRU-HAI-005")
	def test_no_patient_name_field_in_m13_doctypes(self):
		for path in DOCTYPE_DIR.glob("*/*.json"):
			meta = json.loads(path.read_text(encoding="utf-8"))
			for field in meta.get("fields", []):
				self.assertFalse(
					any(word in field["fieldname"] for word in NAME_WORDS), (path.name, field["fieldname"])
				)
		self.assertEqual(frappe.get_meta("HAI Case").get_field("patient_code").fieldtype, "Password")

	def test_r12_sees_only_own_department_cases(self):
		other = f.make_ward("KSNK Case Khoa Khac")
		mine = h.make_case(self.ward).name
		theirs = h.make_case(other, code="BN-0000001111").name
		frappe.set_user(self.r12)
		names = frappe.get_list("HAI Case", filters={"name": ["in", [mine, theirs]]}, pluck="name")
		self.assertEqual(names, [mine])

	def test_r13_cannot_read_cases(self):
		r13 = f.factories.make_user("case-r13@test.local", [h.R13])
		frappe.set_user(r13)
		self.assertFalse(frappe.has_permission("HAI Case", "read"))  # FR-M13-15.3, UC-48 E4
