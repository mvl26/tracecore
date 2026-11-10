"""RPC màn SCR-54 Hóa chất KSNK & đơn vị thuê ngoài (FEAT-066 AC-3, AC-4, AC-10; FR-M12-12, FR-M12-13; A-142 Q4)."""

import json
import uuid

import frappe
from frappe.utils import today

from tracecore.compliance_audit import chemicals
from tracecore.compliance_audit.tests import chemical_factories as cf
from tracecore.tests.factories import make_department, make_user
from tracecore.tests.utils import IsolatedTestCase, request_headers
from tracecore.ui import ksnk
from tracecore.v1 import ic_chemical

TS = "2026-11-10T10:00:00+07:00"


def _key():
	return {"X-Idempotency-Key": str(uuid.uuid4())}


class TestIcChemicalApi(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		self.department = make_department("KSNK Test Khoa API hóa chất")
		self.item = cf.make_chemical("TC-HC-API", "Hand Rub")
		self.period = today()[:7]
		self.r09 = make_user("ic-chem-r09@example.com", ["TC R09"])
		self.r13 = make_user("ic-chem-r13@example.com", ["TC R13"])
		self.r12 = make_user("ic-chem-r12@example.com", ["TC R12"])

	def values(self, **extra):
		return json.dumps(
			{
				"period": self.period,
				"department": self.department,
				"item": self.item,
				"qty": 4.5,
				"source_note": "Sổ khoa tháng này",
				**extra,
			}
		)

	def test_screen_registered_for_r09_and_r02_but_not_r12(self):
		screen = next(item for item in ksnk.SCREENS if item["slug"] == "hoa-chat")
		self.assertEqual((screen["scr"], screen["uc"], screen["group"]), ("SCR-54", "UC-46", "compliance"))
		for role in ("TC R02", "TC R09"):
			self.assertIn(role, ksnk.PAGE_ROLES)
			self.assertIn(role, ksnk.OFFICE_ROLES)
		frappe.set_user(self.r09)
		nav = ksnk.nav()
		slugs = [item["slug"] for group in nav["groups"] for item in group["items"]]
		self.assertEqual(slugs, ["hoa-chat"])
		self.assertFalse(nav["read_only"])
		frappe.set_user(self.r12)
		with self.assertRaises(frappe.PermissionError):
			ic_chemical.overview()

	def test_overview_by_role(self):
		cf.record(self.item, self.department, 3)
		cf.make_vendor("KSNK Test API vendor", license_expiry="2026-01-01")
		frappe.set_user(self.r09)
		data = ic_chemical.overview()
		self.assertTrue(data["can_write"])
		self.assertTrue(data["can_import"])
		self.assertIn(self.item, [item.name for item in data["items"]])
		dept = next(d for d in data["summary"]["departments"] if d["department"] == self.department)
		self.assertEqual(dept["litres"]["Hand Rub"], 3)
		vendor = next(v for v in data["vendors"] if v["name"] == "KSNK Test API vendor")
		self.assertEqual(vendor["state"], "Expired")
		frappe.set_user(self.r13)
		data = ic_chemical.overview()
		self.assertFalse(data["can_write"] or data["can_import"])
		self.assertEqual(data["items"], [])

	def test_manual_entry_needs_source_and_confirmation(self):
		frappe.set_user(self.r09)
		bad = ic_chemical.manual_preview(self.values(source_note=""))
		self.assertFalse(bad["ok"])
		preview = ic_chemical.manual_preview(self.values())
		self.assertTrue(preview["ok"])
		self.assertEqual(preview["preview"]["litres"], 4.5)
		with request_headers(_key()):
			refused = ic_chemical.manual_entry(values=self.values(), confirm=0, client_ts=TS)
		self.assertFalse(refused["ok"])
		with request_headers(_key()):
			saved = ic_chemical.manual_entry(values=self.values(), confirm=1, client_ts=TS)
		self.assertTrue(saved["ok"])
		doc = frappe.get_doc(chemicals.DOCTYPE, saved["name"])
		self.assertEqual((doc.source, doc.confirmed_by, doc.docstatus), (chemicals.MANUAL, self.r09, 1))
		self.assertTrue(frappe.db.exists("Audit Log", {"ref_name": doc.name, "action": "Manual Entry"}))

	def test_r13_cannot_write(self):
		frappe.set_user(self.r13)
		with self.assertRaises(frappe.PermissionError):
			ic_chemical.manual_preview(self.values())
		with request_headers(_key()), self.assertRaises(frappe.PermissionError):
			ic_chemical.choose_source(
				self.period, self.department, self.item, chemicals.MANUAL, "x", client_ts=TS
			)

	def test_choose_source_after_duplicate(self):
		cf.record(self.item, self.department, 2)
		cf.record(
			self.item, self.department, 5, source=chemicals.IMPORT, source_ref="PX-API", source_row="api-1"
		)
		frappe.set_user(self.r09)
		with request_headers(_key()):
			missing = ic_chemical.choose_source(
				self.period, self.department, self.item, chemicals.IMPORT, "", client_ts=TS
			)
		self.assertFalse(missing["ok"])
		with request_headers(_key()):
			done = ic_chemical.choose_source(
				self.period,
				self.department,
				self.item,
				chemicals.IMPORT,
				"Pharmacy file complete",
				client_ts=TS,
			)
		self.assertTrue(done["ok"])
		self.assertEqual(len(done["cancelled"]), 1)
