"""Cửa sổ Ghi đợt quan trắc và Xuất báo cáo trên SCR-67 (FEAT-095; FR-M15-10, .1, FR-M15-12, FR-M15-13, .1;
BRU-ENV-005; A-153 bổ sung 12/11/2026: làm giống bản mẫu)."""

import json
import uuid
from unittest.mock import patch

import frappe

from tracecore.environmental_hygiene.tests import factories as ef
from tracecore.tests.factories import make_user
from tracecore.tests.utils import IsolatedTestCase, bru, request_headers
from tracecore.v1 import wastewater as api

FULL = [
	{"parameter": "pH", "value": 7.1},
	{"parameter": "COD", "value": 48},
	{"parameter": "Coliforms", "value": 3000},
	{"parameter": "Salmonella", "below_detection": 1},
]


class RoundCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.db.delete("Wastewater Point")
		self.point = ef.make_point().name
		ef.make_permit("T-RND", rows=ef.rows_for(self.point))
		self.lab = ef.make_lab()
		self.expired = ef.make_lab("T Công ty Phân tích B", "VIMCERTS 087", "2026-10-01")
		self.r11 = make_user("ww-rnd-r11@example.com", ["TC R11"])
		self.r02 = make_user("ww-rnd-r02@example.com", ["TC R02"])
		self.r08 = make_user("ww-rnd-r08@example.com", ["TC R08"])
		frappe.set_user(self.r11)

	def record(self, results=FULL, submit=1, **values):
		args = {
			"point": self.point,
			"sampled_on": "2026-10-20",
			"supplier": self.lab,
			"report_no": "2611/KQ-QTMT",
			"attachment": ef.ATTACHMENT,
			"results": json.dumps(results),
			"submit": submit,
			**values,
		}
		with request_headers({"X-Idempotency-Key": str(uuid.uuid4())}):
			return api.record_round(client_ts="2026-11-12T09:00:00+07:00", **args)


class TestRecordRound(RoundCase):
	def test_draft_then_post(self):
		draft = self.record(submit=0, attachment="")
		self.assertTrue(draft["ok"])
		self.assertEqual(frappe.db.get_value("Wastewater Monitoring", draft["name"], "docstatus"), 0)
		posted = self.record()
		self.assertEqual((posted["docstatus"], posted["overall_result"]), (1, "Pass"))

	@bru("BRU-ENV-005")
	def test_failed_round_reports_nc_suggestion(self):
		results = [dict(row) for row in FULL]
		results[2]["value"] = 9300
		posted = self.record(results)
		self.assertEqual((posted["overall_result"], posted["nc_status"]), ("Fail", "Suggested"))
		self.assertEqual(posted["failed"], ["Coliforms"])
		self.assertFalse(posted["can_decide"])

	def test_blocks_come_back_inline_and_leave_nothing(self):
		before = frappe.db.count("Wastewater Monitoring")
		blocked = self.record(attachment="")
		self.assertEqual((blocked["ok"], blocked["error"]["code"]), (False, "WW_REPORT_FILE_REQUIRED"))
		blocked = self.record(supplier=self.expired)
		self.assertEqual(blocked["error"]["code"], "WW_VIMCERTS_EXPIRED")
		self.assertEqual(frappe.db.count("Wastewater Monitoring"), before)

	def test_r02_cannot_record(self):
		frappe.set_user(self.r02)
		with self.assertRaises(frappe.PermissionError):
			self.record()

	def test_overview_lists_points_for_the_dialog(self):
		data = api.overview(year="2026", on="2026-11-12")
		self.assertEqual([row["point"] for row in data["points"]], [self.point])
		self.assertTrue(data["can_record"])
		self.assertFalse(data["can_permit"])


class TestExportReport(RoundCase):
	def setUp(self):
		super().setUp()
		self.record()

	def test_excel_file(self):
		api.export_report(scope="2026", point="", fmt="xlsx")
		self.assertEqual(frappe.response["type"], "binary")
		self.assertTrue(frappe.response["filename"].endswith(".xlsx"))
		self.assertTrue(frappe.response["filecontent"].startswith(b"PK"))

	def test_pdf_file_for_a_quarter(self):
		with patch("frappe.utils.pdf.get_pdf", return_value=b"%PDF-1.4 test") as pdf:
			api.export_report(scope="2026-Q4", point=self.point, fmt="pdf")
		self.assertIn("Coliforms", pdf.call_args.args[0])
		self.assertEqual(frappe.response["filecontent"], b"%PDF-1.4 test")
		self.assertTrue(frappe.response["filename"].endswith(".pdf"))

	def test_r08_cannot_export(self):
		frappe.set_user(self.r08)
		with self.assertRaises(frappe.PermissionError):
			api.export_report(scope="2026")
