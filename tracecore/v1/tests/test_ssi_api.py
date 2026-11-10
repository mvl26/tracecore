"""RPC tracecore.v1.ssi.* và tracecore.v1.exports.* (FEAT-064; SCR-57, SCR-58; FR-M13-07..09, 12; BRU-RPT-002; A-147
j, k)."""

import frappe

from tracecore.hai_surveillance import ssi
from tracecore.hai_surveillance.tests import factories as f
from tracecore.hai_surveillance.tests import hai_fixtures as h
from tracecore.hai_surveillance.tests import ssi_fixtures as s
from tracecore.tests.utils import IsolatedTestCase, bru
from tracecore.v1 import exports as export_api
from tracecore.v1 import ssi as api


class TestSSIApi(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		self.ward = f.make_ward("KSNK SSI API")
		self.group = s.make_group(
			"T-HPRO", t=120, implant=1, followups=((7, "Phone"), (30, "Phone"), (90, "Revisit"))
		)
		s.set_threshold(60)
		self.r11 = f.factories.make_user("ssi-api-r11@test.local", [h.R11])
		self.r13 = f.factories.make_user("ssi-api-r13@test.local", [h.R13])
		self.r10 = f.factories.make_user("ssi-api-r10@test.local", [h.R10])
		h.clear_definitions("TSSI")
		h.make_definition("TSSI", device=None, hours=0, days=0, site="Superficial Incisional SSI")

	def _register(self, **extra):
		values = {k: v for k, v in s.ssi_values(self.ward, self.group.name, **extra).items()}
		values["surgery_date"] = str(values["surgery_date"])
		return api.save(frappe.as_json(values))

	@bru("BRU-HAI-005")
	def test_register_and_screen_show_masked_code_only(self):
		frappe.set_user(self.r11)
		result = self._register(discharge_date="2026-11-02")
		self.assertTrue(result["ok"])
		detail = result["detail"]
		self.assertEqual((detail["nnis_index"], str(detail["window_end"])), ("2", "2027-01-26"))
		self.assertEqual(len(detail["followups"]), 3)
		data = api.screen(detail["name"])
		self.assertIn("TSSI", [row["def_code"] for row in data["definitions"]])
		self.assertNotIn("BN-0000006612", frappe.as_json(data))
		self.assertEqual(data["detail"]["patient_code_masked"], "***6612")
		self.assertIn(self.group.name, [row["name"] for row in data["groups"]])

	def test_blocked_save_returns_alert_body(self):
		frappe.set_user(self.r11)
		result = self._register(asa_score=7)
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "SSI_VALUE_INVALID")

	def test_update_keeps_patient_code(self):
		frappe.set_user(self.r11)
		name = self._register()["detail"]["name"]
		result = api.save(frappe.as_json({"asa_score": 1, "patient_code": ""}), name)
		self.assertEqual(result["detail"]["patient_code_masked"], "***6612")
		self.assertEqual(result["detail"]["nnis_index"], "1")

	def test_followup_close_and_case(self):
		frappe.set_user(self.r11)
		detail = self._register(discharge_date="2026-11-02")["detail"]
		row = detail["followups"][0]["name"]
		result = api.record_followup(detail["name"], row, "2026-11-04", "SSI suspected", "Sưng đỏ vết mổ")
		self.assertEqual(result["detail"]["followups"][0]["result"], "SSI suspected")
		self.assertEqual(api.due()["ok"], True)
		created = api.create_case(detail["name"], "TSSI", "2026-11-04")
		self.assertTrue(created["case"].startswith("CA-"))
		closed = api.close(detail["name"], ssi.NO_SSI)
		self.assertEqual(closed["error"]["code"], "SSI_WINDOW_OPEN")

	def test_roles(self):
		frappe.set_user(self.r13)
		with self.assertRaises(frappe.PermissionError):
			api.screen()
		summary = api.summary("2026-10")
		self.assertTrue(summary["ok"])
		self.assertFalse(summary["can_export"])
		with self.assertRaises(frappe.PermissionError):
			export_api.download("ssi_summary", "2026-10")
		frappe.set_user(self.r10)
		self.assertTrue(api.summary()["ok"])

	@bru("BRU-RPT-002")
	def test_download_and_kinds(self):
		frappe.set_user(self.r11)
		self._register()
		keys = {row["key"] for row in export_api.kinds()["kinds"]}
		self.assertTrue({"ssi_cases", "ssi_summary", "icu_hai_cases", "icu_hai_summary"} <= keys)
		export_api.download("ssi_cases", "2026-10", "2026-10")
		self.assertEqual(frappe.response["type"], "binary")
		self.assertTrue(frappe.response["filename"].endswith(".xlsx"))
		self.assertNotIn(b"BN-0000006612", frappe.response["filecontent"])
