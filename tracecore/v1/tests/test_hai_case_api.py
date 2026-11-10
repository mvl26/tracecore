"""RPC tracecore.v1.hai_case.* (FEAT-063; FR-M13-05, 10, 11, 15, 15.2, 15.3; NFR-PRIV-01; BRU-HAI-005, BRU-RPT-003;
UC-48; A-144)."""

import json

import frappe

from tracecore.hai_surveillance import cases
from tracecore.hai_surveillance.tests import factories as f
from tracecore.hai_surveillance.tests import hai_fixtures as h
from tracecore.tests.utils import IsolatedTestCase, bru
from tracecore.v1 import hai_case, patient_code

CODE = "BN-0000004821"


class TestHaiCaseApi(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		h.clear_definitions("TVAP")
		h.make_definition("TVAP", effective_from="2026-01-01", hours=0, days=0)
		frappe.db.delete("IC Reporting Period", {"month": "2026-10"})
		self.ward = f.make_ward("KSNK Api ICU")
		frappe.db.delete("Ward Daily Census", {"department": self.ward})
		self.case = h.make_case(self.ward, code=CODE)
		self.r01 = f.factories.make_user("api063-r01@test.local", [h.R01])
		self.r11 = f.factories.make_user("api063-r11@test.local", [h.R11])
		self.r13 = f.factories.make_user("api063-r13@test.local", [h.R13])

	@bru("BRU-HAI-005")
	def test_screen_lists_masked_code_only(self):
		frappe.set_user(self.r11)
		data = hai_case.screen()
		self.assertTrue(data["can_decide"])
		self.assertTrue(data["can_reveal"])
		self.assertFalse(data["can_lock"])
		self.assertIn(self.case.name, [row["name"] for row in data["cases"]])
		self.assertNotIn(CODE, json.dumps(data, default=str))
		detail = hai_case.detail(self.case.name)["detail"]
		self.assertEqual(detail["patient_code_masked"], "***4821")
		self.assertNotIn(CODE, json.dumps(detail, default=str))

	def test_r13_cannot_open_cases_but_reads_report(self):
		frappe.set_user(self.r13)
		with self.assertRaises(frappe.PermissionError):
			hai_case.screen()
		data = hai_case.report("2026-10")
		self.assertTrue(data["ok"])
		self.assertEqual(len(data["trend"]), 12)
		self.assertNotIn(CODE, json.dumps(data, default=str))

	def test_reveal_needs_reason_and_audits(self):
		frappe.set_user(self.r11)
		body = patient_code.reveal("HAI Case", self.case.name, reason="")
		self.assertFalse(body["ok"])
		body = patient_code.reveal("HAI Case", self.case.name, reason="Đối chiếu hồ sơ bệnh án")
		self.assertEqual(body["patient_code"], CODE)  # FR-M13-15.2
		self.assertTrue(
			frappe.db.exists(
				"Audit Log",
				{"ref_doctype": "HAI Case", "ref_name": self.case.name, "action": "View Patient Code"},
			)
		)

	def test_decide_returns_block_body(self):
		frappe.set_user(self.r11)
		body = hai_case.decide(self.case.name, cases.EXCLUDED, reason="")
		self.assertFalse(body["ok"])
		self.assertEqual(body["error"]["code"], "HAI_CASE_REASON_REQUIRED")
		body = hai_case.decide(self.case.name, cases.CONFIRMED)
		self.assertTrue(body["ok"])
		self.assertEqual(body["detail"]["status"], cases.CONFIRMED)

	def test_link_isolate_and_options(self):
		isolate = h.make_isolate(self.ward, lab="L-API-063")
		frappe.set_user(self.r11)
		options = hai_case.isolate_options(self.case.name)["isolates"]
		self.assertIn(isolate.name, [row["name"] for row in options])
		body = hai_case.link_isolate(self.case.name, isolate.name)
		self.assertTrue(body["ok"])
		self.assertEqual([row["isolate"] for row in body["detail"]["isolates"]], [isolate.name])

	@bru("BRU-RPT-003")
	def test_lock_period_locks_indicator_values(self):
		f.make_census(self.ward, census_date="2026-10-05", patients=10, vent=5, cvc=0, urinary=0)
		frappe.set_user(self.r11)
		with self.assertRaises(frappe.PermissionError):
			hai_case.lock_period("2026-10")
		frappe.set_user(self.r01)
		body = hai_case.lock_period("2026-10")
		self.assertTrue(body["ok"])
		row = next(row for row in body["periods"] if row["month"] == "2026-10")
		self.assertEqual(row["locked"], 1)
		frappe.set_user("Administrator")
		if frappe.db.exists("IC Indicator Value", {"period": "2026-10"}):
			self.assertFalse(frappe.db.exists("IC Indicator Value", {"period": "2026-10", "locked": 0}))
		frappe.set_user(self.r01)
		body = hai_case.unlock_period("2026-10", "")
		self.assertEqual(body["error"]["code"], "HAI_CASE_REASON_REQUIRED")
		self.assertTrue(hai_case.unlock_period("2026-10", "Bổ sung ca")["ok"])

	def test_invalid_period_rejected(self):
		frappe.set_user(self.r01)
		self.assertEqual(hai_case.lock_period("2026-13")["error"]["code"], "HAI_PERIOD_INVALID")

	@bru("BRU-HAI-005")
	def test_desk_export_has_no_clear_patient_code(self):
		"""NFR-PRIV-01: danh sách/xuất Desk của HAI Case chỉ có mã che (trường Password không lưu mã rõ)."""
		frappe.set_user(self.r11)
		rows = frappe.get_list("HAI Case", filters={"name": self.case.name}, fields=["*"])
		self.assertTrue(rows)
		self.assertNotIn(CODE, json.dumps(rows, default=str))
		from frappe.desk.reportview import get

		frappe.local.form_dict = frappe._dict(
			doctype="HAI Case", fields=json.dumps(["name", "patient_code", "patient_code_masked"])
		)
		self.assertNotIn(CODE, json.dumps(get(), default=str))
