"""RPC tracecore.v1.costing.recalculate (FEAT-046 Task 4; UC-29 A1, FR-M7-03.2; A-53 i)."""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, today

from tracecore.costing import sheet
from tracecore.costing.tests.test_sheet import LABOR, SheetCase
from tracecore.tests.factories import make_cost_rate_version, make_user, rate_line
from tracecore.v1 import costing as api


class TestRecalculate(SheetCase):
	def setUp(self):
		super().setUp()
		self.priced()
		self.load_name = self.load()
		self.main = sheet.build("Sterilization Load", self.load_name)
		self.cost_before = frappe.db.get_value("Pack", self.packs[0].name, "cost_total")
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.local.response.pop("http_status_code", None)
		self.addCleanup(frappe.local.response.pop, "http_status_code", None)

	def call(self, version, note="Giá điện mới theo yêu cầu R01"):
		return api.recalculate(
			source_doctype="Sterilization Load", source_name=self.load_name, rate_version=version, note=note
		)

	def test_r09_recalculates_with_another_approved_version(self):
		other = make_cost_rate_version(
			submit=True,
			effective_from=add_days(today(), 1),
			rates=[rate_line(LABOR, "Labor"), rate_line(5000, "Electricity")],
		)
		frappe.set_user(make_user("cs-recalc-r09@example.com", ["TC R09"]))
		result = self.call(other.name)
		self.assertTrue(result["ok"], result)
		doc = frappe.get_doc("Cost Sheet", result["cost_sheet"])
		self.assertEqual((doc.is_recalculation, doc.supersedes, doc.rate_version), (1, self.main, other.name))
		self.assertEqual(doc.recalc_note, "Giá điện mới theo yêu cầu R01")
		self.assertEqual(frappe.db.get_value("Pack", self.packs[0].name, "cost_total"), self.cost_before)
		self.assertTrue(frappe.db.exists("Audit Log", {"ref_doctype": "Cost Sheet", "ref_name": doc.name}))

	def test_draft_version_and_missing_note_are_rejected(self):
		draft = make_cost_rate_version()
		frappe.set_user(make_user("cs-recalc-r01@example.com", ["TC R01"]))
		self.assertEqual(self.call(draft.name)["error"]["code"], "RATE_VERSION_NOT_APPROVED")
		approved = make_cost_rate_version(submit=True, effective_from=add_days(today(), 1))
		self.assertEqual(self.call(approved.name, note="  ")["error"]["code"], "NOTE_REQUIRED")

	def test_r02_cannot_recalculate(self):
		frappe.set_user(make_user("cs-recalc-r02@example.com", ["TC R02"]))
		with self.assertRaises(frappe.PermissionError):
			self.call("DG-X")

	def test_unfinished_load_is_rejected(self):
		"""Mẻ đang chạy chưa có chi phí để tính lại (review #8)."""
		running = self.load(status="Running")
		approved = make_cost_rate_version(submit=True, effective_from=add_days(today(), 1))
		result = api.recalculate(
			source_doctype="Sterilization Load", source_name=running, rate_version=approved.name, note="x"
		)
		self.assertEqual(result["error"]["code"], "COST_SOURCE_NOT_FOUND")

	def test_unknown_source_is_rejected(self):
		with patch.object(sheet, "build") as build:
			result = api.recalculate(
				source_doctype="Wash Batch", source_name="LR-NONE", rate_version="DG-X", note="x"
			)
		self.assertEqual(result["error"]["code"], "COST_SOURCE_NOT_FOUND")
		build.assert_not_called()
