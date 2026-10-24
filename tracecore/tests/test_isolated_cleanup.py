import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.tests.utils import TEST_SAVEPOINT, rollback_to_test_savepoint


class TestIsolatedCleanup(FrappeTestCase):
	def test_rollback_survives_a_savepoint_lost_to_an_implicit_commit(self):
		frappe.db.savepoint(TEST_SAVEPOINT)
		frappe.db.commit()  # nosemgrep: commit ngầm hủy savepoint như DDL hay luồng đăng nhập
		rollback_to_test_savepoint()  # không ném OperationalError 1305

	def test_rollback_still_undoes_work_after_the_savepoint(self):
		frappe.db.savepoint(TEST_SAVEPOINT)
		frappe.db.set_single_value("System Settings", "session_expiry", "03:00:00")
		rollback_to_test_savepoint()
		self.assertNotEqual(frappe.db.get_single_value("System Settings", "session_expiry"), "03:00:00")
