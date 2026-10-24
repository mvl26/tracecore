"""Run launcher FrappeTestCase from this clone without altering the active bench checkout.

Run with the bench env Python, from bench/sites. Requires an existing test_site.
"""

import importlib.util
import sys
import unittest
from pathlib import Path

import frappe

source = Path(__file__).resolve().parents[1]
frappe.init(site="test_site", sites_path=str(Path.cwd()))
frappe.connect()
try:
	import tracecore.ui.page
	import tracecore.v1

	spec = importlib.util.spec_from_file_location(
		"tracecore.v1.navigation", source / "tracecore/v1/navigation.py"
	)
	navigation = importlib.util.module_from_spec(spec)
	sys.modules[spec.name] = navigation
	spec.loader.exec_module(navigation)

	tracecore.ui.page.__path__.insert(0, str(source / "tracecore/ui/page"))
	frappe.set_user("Administrator")
	suite = unittest.defaultTestLoader.loadTestsFromName("tracecore.ui.page.tracecore.test_tracecore")
	result = unittest.TextTestRunner(verbosity=2).run(suite)
	frappe.db.rollback()
finally:
	frappe.destroy()
sys.exit(not result.wasSuccessful())
