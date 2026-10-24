"""Run current-clone Home tests in the existing bench without editing its checkout."""
import sys
import unittest
from pathlib import Path

import frappe

source = Path('/mnt/d/tracecore')
frappe.init(site='test_site', sites_path=str(Path.cwd()))
frappe.connect()
try:
    import tracecore.v1
    import tracecore.v1.tests
    import tracecore.ui.page

    tracecore.v1.__path__.insert(0, str(source / 'tracecore/v1'))
    tracecore.v1.tests.__path__.insert(0, str(source / 'tracecore/v1/tests'))
    tracecore.ui.page.__path__.insert(0, str(source / 'tracecore/ui/page'))
    frappe.set_user('Administrator')
    suite = unittest.defaultTestLoader.loadTestsFromNames(sys.argv[1:] or ['tracecore.v1.tests.test_home_api'])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    frappe.db.rollback()
finally:
    frappe.destroy()
sys.exit(not result.wasSuccessful())
