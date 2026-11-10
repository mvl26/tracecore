"""Tự đánh giá năm theo QĐ 38 (FEAT-065 AC-065-14; FR-M9-29, FR-M9-29.1; NFR-MAINT-04)."""

from unittest.mock import patch

import frappe

from tracecore.admin_reports import self_assessment as service
from tracecore.admin_reports import self_assessment_seed
from tracecore.admin_reports.tests.test_ic_board import YEAR, BoardCase
from tracecore.v1 import indicator as api

CHECKS = {
	"t_met": lambda year: {"status": "Met", "source_ref": f"KH-{year}"},
	"t_needs": lambda year: {"status": "Needs confirmation", "source_ref": "12 isolates"},
	"t_bad": lambda year: {"status": "Weird"},
}


def _criterion(code, check_method="", indicator=None, order=0, active=1):
	frappe.get_doc(
		{
			"doctype": "IC QD38 Criterion",
			"criterion_code": code,
			"criterion": f"Criterion {code}",
			"source_hint": "Test",
			"check_method": check_method,
			"indicator": indicator,
			"sort_order": order,
			"is_active": active,
		}
	).insert(ignore_permissions=True)


class TestSelfAssessment(BoardCase):
	def setUp(self):
		super().setUp()
		frappe.db.delete("IC Self Assessment Item")
		frappe.db.delete("IC Self Assessment")
		frappe.db.set_value("IC QD38 Criterion", {"is_active": 1}, "is_active", 0)
		_criterion("T-MET", "t_met", order=1)
		_criterion("T-NEEDS", "t_needs", order=2)
		_criterion("T-MANUAL", order=3)
		_criterion("T-IND", indicator="FB-HH", order=4)
		_criterion("T-BAD", "t_bad", order=5)
		_criterion("T-OFF", "t_met", order=6, active=0)
		self.checks = patch.object(service, "registry", return_value=CHECKS)
		self.checks.start()
		self.addCleanup(self.checks.stop)

	def _rows(self, data):
		return {row["criterion"]: row for row in data["rows"]}

	def test_prepare_fills_auto_rows_and_leaves_the_rest_manual(self):
		frappe.set_user(self.r01)
		rows = self._rows(api.self_assessment_prepare(YEAR))
		self.assertEqual(list(rows), ["T-MET", "T-NEEDS", "T-MANUAL", "T-IND", "T-BAD"])
		self.assertEqual((rows["T-MET"]["source"], rows["T-MET"]["status"]), ("Auto", "Met"))
		self.assertEqual(rows["T-MET"]["source_ref"], f"KH-{YEAR}")
		self.assertEqual(rows["T-NEEDS"]["status"], "Needs confirmation")
		self.assertEqual((rows["T-MANUAL"]["source"], rows["T-MANUAL"]["status"]), ("Manual", "Not assessed"))
		self.assertEqual((rows["T-BAD"]["source"], rows["T-BAD"]["status"]), ("Manual", "Not assessed"))
		# FB-HH năm YEAR: (75 + 78 + 84) / 300 = 79 % < 80 % chỉ tiêu quốc gia
		self.assertEqual((rows["T-IND"]["source"], rows["T-IND"]["status"]), ("Auto", "Not met"))

	def test_indicator_uses_plan_target(self):
		self.approved_plan([("FB-HH", 70, 75)])
		self.assertEqual(self._rows(api.self_assessment_prepare(YEAR))["T-IND"]["status"], "Met")

	def test_indicator_without_locked_values_stays_manual(self):
		frappe.db.set_value("IC Indicator Value", {"indicator": "FB-HH"}, "locked", 0)
		self.assertEqual(self._rows(api.self_assessment_prepare(YEAR))["T-IND"]["source"], "Manual")

	def test_manual_edit_marks_source_manual_and_survives_refresh(self):
		frappe.set_user(self.r01)
		api.self_assessment_prepare(YEAR)
		data = api.self_assessment_set(YEAR, "T-MET", "Not met", evidence="Plan late", note="R01")
		row = self._rows(data)["T-MET"]
		self.assertEqual((row["source"], row["status"], row["evidence"]), ("Manual", "Not met", "Plan late"))
		self.assertEqual(self._rows(api.self_assessment_prepare(YEAR))["T-MET"]["status"], "Not met")

	def test_submit_requires_confirmation_then_locks(self):
		frappe.set_user(self.r01)
		api.self_assessment_prepare(YEAR)
		blocked = api.self_assessment_submit(YEAR)
		self.assertFalse(blocked["ok"])
		self.assertIn("T-NEEDS", blocked["error"]["reason"])
		api.self_assessment_set(YEAR, "T-NEEDS", "Met", evidence="WHONET file sent")
		data = api.self_assessment_submit(YEAR)
		self.assertEqual(data["docstatus"], 1)
		self.assertFalse(data["can_manage"])
		self.assertFalse(api.self_assessment_set(YEAR, "T-MET", "Met")["ok"])
		self.assertFalse(api.self_assessment_prepare(YEAR)["ok"])

	def test_r13_reads_only(self):
		api.self_assessment_prepare(YEAR)
		frappe.set_user(self.r13)
		data = api.self_assessment(YEAR)
		self.assertFalse(data["can_manage"])
		self.assertEqual(len(data["rows"]), 5)
		for call in (
			lambda: api.self_assessment_prepare(YEAR),
			lambda: api.self_assessment_set(YEAR, "T-MET", "Met"),
			lambda: api.self_assessment_submit(YEAR),
		):
			with self.assertRaises(frappe.PermissionError):
				call()

	def test_roles_without_read_are_rejected(self):
		from tracecore.infection_program.tests import ic_fixtures as fx

		frappe.set_user(fx.user("R02", prefix="ksnk-sa"))
		with self.assertRaises(frappe.PermissionError):
			api.self_assessment(YEAR)

	def test_empty_year_view(self):
		data = api.self_assessment(YEAR + 1)
		self.assertIsNone(data["name"])
		self.assertEqual(data["rows"], [])

	def test_validation(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({"doctype": "IC Self Assessment", "year": 1999}).insert(ignore_permissions=True)
		doc = frappe.get_doc(
			{
				"doctype": "IC Self Assessment",
				"year": YEAR + 2,
				"items": [{"criterion": "T-MET"}, {"criterion": "T-MET"}],
			}
		)
		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)

	def test_bad_status_and_unknown_criterion(self):
		api.self_assessment_prepare(YEAR)
		for args in (("T-MET", "Great"), ("NOPE", "Met")):
			self.assertFalse(api.self_assessment_set(YEAR, *args)["ok"])
		self.assertFalse(api.self_assessment_set(YEAR + 3, "T-MET", "Met")["ok"])
		with self.assertRaises(frappe.ValidationError):
			service.submit(YEAR + 3)

	def test_print_context(self):
		name = service.prepare(YEAR)
		context = service.tc_ic_self_assessment_context(name)
		self.assertTrue(context["draft"])
		self.assertEqual(context["rows"][0]["source"], "Auto")
		html = frappe.get_print(
			"IC Self Assessment", name, print_format=service.PRINT_FORMAT, no_letterhead=1
		)
		self.assertIn("Criterion T-MET", html)

	def test_registry_rejects_duplicate_keys(self):
		self.checks.stop()
		with patch("tracecore.core.extension.run", return_value=[{"k": print}, {"k": print}]):
			with self.assertRaises(ValueError):
				service.registry()
		self.checks.start()

	def test_registry_merges_module_checks(self):
		self.checks.stop()
		keys = set(service.registry())
		self.checks.start()
		self.assertTrue(
			{"ic_plan_approved", "ic_chemical_quarterly", "hai_surveillance_active", "amr_surveillance"}
			<= keys
		)


class TestSeed(BoardCase):
	def test_seed_inserts_missing_codes_only(self):
		code = self_assessment_seed.CRITERIA[0][0]
		if not frappe.db.exists("IC QD38 Criterion", code):
			self_assessment_seed.ensure_seed()
		frappe.db.set_value("IC QD38 Criterion", code, {"criterion": "Hospital wording", "is_active": 0})
		self_assessment_seed.ensure_seed()
		self.assertEqual(frappe.db.get_value("IC QD38 Criterion", code, "criterion"), "Hospital wording")
		self.assertEqual(frappe.db.get_value("IC QD38 Criterion", code, "is_active"), 0)
		for row in self_assessment_seed.CRITERIA:
			self.assertTrue(frappe.db.exists("IC QD38 Criterion", row[0]))
