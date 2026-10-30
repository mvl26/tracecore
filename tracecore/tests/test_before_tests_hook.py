import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.setup import install


class TestBeforeTestsHook(FrappeTestCase):
	def test_hook_is_registered_for_the_app(self):
		# `bench run-tests --app tracecore` chỉ chạy before_tests của chính app (frappe.test_runner)
		hooks = frappe.get_hooks("before_tests", app_name="tracecore")
		self.assertIn("tracecore.setup.install.before_tests", hooks)

	def test_before_tests_creates_transit_warehouse_type_once(self):
		# Company test record của ERPNext cần Warehouse Type "Transit"; chạy lại không lỗi, không nhân đôi
		frappe.db.delete("Warehouse Type", {"name": "Transit"})
		install.before_tests()
		install.before_tests()
		self.assertEqual(frappe.db.count("Warehouse Type", {"name": "Transit"}), 1)

	def test_before_tests_creates_genders_used_by_station_fixtures(self):
		frappe.db.delete("Gender", {"name": ["in", list(install.TEST_GENDERS)]})
		install.before_tests()
		self.assertEqual(
			set(frappe.get_all("Gender", filters={"name": ["in", list(install.TEST_GENDERS)]}, pluck="name")),
			set(install.TEST_GENDERS),
		)

	def test_before_tests_does_not_run_the_erpnext_setup_wizard(self):
		companies = frappe.db.count("Company")
		install.before_tests()
		self.assertEqual(frappe.db.count("Company"), companies)
