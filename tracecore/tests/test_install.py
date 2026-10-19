import frappe
from frappe.tests.utils import FrappeTestCase

EXPECTED_MODULES = (
	"TraceCore",
	"Instrument",
	"Reprocessing",
	"Linen",
	"Equipment",
	"Inventory",
	"Costing",
	"Par",
	"Admin Reports",
	"Waste",
	"UI",
)


class TestInstall(FrappeTestCase):
	def test_module_defs_registered(self):
		for module in EXPECTED_MODULES:
			self.assertEqual(
				frappe.db.get_value("Module Def", module, "app_name"), "tracecore", msg=module
			)
		# "Core" thuộc frappe, "HR" thuộc hrms — tracecore không được chiếm (amendment 2026-10-19)
		self.assertEqual(frappe.db.get_value("Module Def", "Core", "app_name"), "frappe")
		self.assertNotEqual(frappe.db.get_value("Module Def", "HR", "app_name"), "tracecore")

	def test_roles_exist(self):
		expected = [f"TC R{n:02d}" for n in range(1, 11)] + ["TC Agent"]
		for role in expected:
			self.assertTrue(frappe.db.exists("Role", role), msg=role)

	def test_system_settings_localized(self):
		settings = frappe.get_single("System Settings")
		self.assertEqual(settings.language, "vi")
		self.assertEqual(settings.time_zone, "Asia/Ho_Chi_Minh")
		self.assertEqual(settings.date_format, "dd/mm/yyyy")
		self.assertEqual(settings.time_format, "HH:mm")
