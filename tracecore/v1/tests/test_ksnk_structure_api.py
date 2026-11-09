"""RPC tracecore.v1.ksnk_structure.* — màn SCR-47 Cơ cấu KSNK (FEAT-057 AC-11; FR-M11-01..03; plan D6)."""

import frappe

from tracecore.infection_program.tests import ic_fixtures as fx
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase, bru
from tracecore.v1 import ksnk_structure as api


class TestKsnkStructureApi(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		fx.clear_required_departments()
		self.dept = fx.required_department("KSNK API Nội")
		fx.network_member(fx.employee("API Doctor"), self.dept, "Doctor")
		fx.settings(bed_count=420)
		self.users = {
			code: factories.make_user(f"ksnk-structure-{code.lower()}@example.com", [f"TC {code}"])
			for code in ("R01", "R02", "R10", "R11", "R13")
		}

	@bru("BRU-ICP-001")
	def test_status_returns_components_and_rights(self):
		frappe.set_user(self.users["R01"])
		data = api.status()
		self.assertEqual(
			[row["key"] for row in data["components"]],
			["committee", "ic_department", "network", "surveillance"],
		)
		self.assertEqual(data["settings"]["bed_count"], 420)
		self.assertEqual(data["departments"][0]["status_label"], "Missing nurse/midwife/technician")
		self.assertTrue(data["can_edit_settings"])
		self.assertTrue(data["can_submit_committee"])
		self.assertIsNone(data["draft_committee"])

	def test_r13_reads_without_write_rights(self):
		frappe.set_user(self.users["R13"])
		data = api.status()
		self.assertFalse(data["can_edit_settings"])
		self.assertFalse(data["can_submit_committee"])

	def test_role_without_screen_is_rejected(self):
		frappe.set_user(self.users["R02"])
		with self.assertRaises(frappe.PermissionError):
			api.status()

	def test_r10_saves_settings_and_status_follows(self):
		frappe.set_user(self.users["R10"])
		result = api.save_settings({"bed_count": 120, "facility_level": "Basic Level", "has_inpatient": 1})
		self.assertTrue(result["ok"], result)
		self.assertEqual(frappe.db.get_single_value("IC Program Settings", "bed_count"), 120)
		committee = {row["key"]: row for row in result["status"]["components"]}["committee"]
		self.assertEqual(committee["status"], "optional")

	def test_save_settings_ignores_unknown_fields(self):
		frappe.set_user(self.users["R10"])
		api.save_settings({"bed_count": 300, "patient_data_retention_months": 99})
		self.assertNotEqual(
			frappe.db.get_single_value("IC Program Settings", "patient_data_retention_months"), 99
		)

	def test_invalid_settings_return_inline_block(self):
		frappe.set_user(self.users["R10"])
		result = api.save_settings({"bed_count": 300, "surveillance_ratio_beds": 0})
		self.assertFalse(result["ok"])
		self.assertTrue(result["error"]["reason"])
		self.assertTrue(result["error"]["title"])
		self.assertEqual(frappe.get_message_log(), [])  # không bật hộp thoại, lỗi hiện inline
		self.assertEqual(frappe.db.get_single_value("IC Program Settings", "bed_count"), 420)

	def test_r11_cannot_save_settings(self):
		frappe.set_user(self.users["R11"])
		with self.assertRaises(frappe.PermissionError):
			api.save_settings({"bed_count": 10})

	@bru("BRU-ICP-002")
	def test_submit_committee_blocks_inline_when_secretary_missing(self):
		members = [m for m in fx.full_committee_members() if m[1] != "Secretary"]
		draft = fx.committee(members)
		frappe.set_user(self.users["R01"])
		self.assertEqual(api.status()["draft_committee"], draft.name)
		result = api.submit_committee(draft.name)
		self.assertFalse(result["ok"])
		self.assertIn("Missing Secretary", result["error"]["reason"])
		self.assertEqual(frappe.db.get_value("IC Committee", draft.name, "docstatus"), 0)
		self.assertEqual(frappe.get_message_log(), [])

	@bru("BRU-ICP-002")
	def test_submit_committee_returns_warnings(self):
		members = [m for m in fx.full_committee_members() if m[2] != "High-risk Clinical"]
		draft = fx.committee(members)
		frappe.set_user(self.users["R01"])
		result = api.submit_committee(draft.name)
		self.assertTrue(result["ok"])
		self.assertEqual(frappe.db.get_value("IC Committee", draft.name, "docstatus"), 1)
		self.assertTrue(any("High-risk Clinical" in warning for warning in result["warnings"]))
		self.assertEqual(frappe.get_message_log(), [])

	def test_r13_cannot_submit_committee(self):
		draft = fx.committee(fx.full_committee_members())
		frappe.set_user(self.users["R13"])
		with self.assertRaises(frappe.PermissionError):
			api.submit_committee(draft.name)
