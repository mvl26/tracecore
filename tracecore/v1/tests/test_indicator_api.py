"""RPC chỉ đọc tracecore.v1.indicator.values (FEAT-056 AC-9; FR-M9-27; NFR-SEC-09, NFR-PERF-05)."""

from unittest.mock import patch

import frappe

from tracecore.admin_reports import indicator
from tracecore.admin_reports.tests.test_indicator import REGISTRY, SOURCE, _indicator
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase, assert_permission_matrix
from tracecore.v1 import indicator as api


def _r12_user(email, department):
	user = factories.make_user(email, ["TC R12"])
	if not frappe.db.exists(
		"User Permission", {"user": user, "allow": "Department", "for_value": department}
	):
		frappe.get_doc(
			{"doctype": "User Permission", "user": user, "allow": "Department", "for_value": department}
		).insert(ignore_permissions=True)
	return user


class TestIndicatorValuesApi(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		SOURCE.clear()
		frappe.db.delete("IC Indicator Value")
		frappe.db.set_value("IC Indicator", {"is_active": 1}, "is_active", 0)
		self.dept_a = factories.make_department("KSNK Test A")
		self.dept_b = factories.make_department("KSNK Test B")
		_indicator("T-PCT", "Percentage", "T_PCT", national_target=80, target_direction="Higher is better")
		_indicator("T-RATE", "Rate per 1000", "T_RATE", national_target=3, target_direction="Lower is better")
		self.registry = patch("tracecore.core.indicators.registry", return_value=REGISTRY)
		self.registry.start()
		self.addCleanup(self.registry.stop)
		self.addCleanup(frappe.set_user, "Administrator")
		for period, pct, rate in (("2026-08", 75, 26), ("2026-09", 78, 24), ("2026-10", 84, 0)):
			SOURCE[("T_PCT", None)] = (pct, 100, 100)
			SOURCE[("T_PCT", self.dept_a)] = (pct - 10, 100, 100)
			SOURCE[("T_PCT", self.dept_b)] = (pct + 1, 100, 100)
			SOURCE[("T_RATE", None)] = (rate, 10000 if rate else 0, 10000)
			indicator.lock_period(period)

	def _row(self, result, code):
		return next(row for row in result["rows"] if row["code"] == code)

	def test_reads_stored_values_for_last_periods_without_recompute(self):
		frappe.set_user(factories.make_user("ksnk-r13@example.com", ["TC R13"]))
		with patch("tracecore.core.indicators.registry", side_effect=AssertionError("no recompute")):
			result = api.values(period="2026-10", periods=3)
		self.assertEqual(result["periods"], ["2026-08", "2026-09", "2026-10"])
		pct = self._row(result, "T-PCT")
		self.assertEqual(pct["values"]["2026-10"]["value"], 84)
		self.assertEqual(pct["values"]["2026-10"]["status"], "Met")
		self.assertEqual(pct["values"]["2026-09"]["status"], "Not met")
		rate = self._row(result, "T-RATE")
		self.assertEqual(rate["values"]["2026-09"]["value"], 2.4)
		self.assertEqual(rate["values"]["2026-09"]["status"], "Met")
		self.assertIsNone(rate["values"]["2026-10"]["value"])
		self.assertEqual(rate["values"]["2026-10"]["status"], "Not calculated")

	def test_department_filter(self):
		result = api.values(period="2026-10", department=self.dept_a, periods=1)
		self.assertEqual(self._row(result, "T-PCT")["values"]["2026-10"]["value"], 74)

	def test_r12_sees_only_own_department_and_hospital(self):
		frappe.set_user(_r12_user("ksnk-r12a@example.com", self.dept_a))
		own = api.values(period="2026-10", department=self.dept_a, periods=1)
		self.assertEqual(self._row(own, "T-PCT")["values"]["2026-10"]["value"], 74)
		whole = api.values(period="2026-10", periods=1)
		self.assertEqual(self._row(whole, "T-PCT")["values"]["2026-10"]["value"], 84)
		other = api.values(period="2026-10", department=self.dept_b, periods=1)
		self.assertEqual(self._row(other, "T-PCT")["values"], {})

	def test_roles_without_read_are_rejected(self):
		frappe.set_user(factories.make_user("ksnk-r02@example.com", ["TC R02"]))
		with self.assertRaises(frappe.PermissionError):
			api.values(period="2026-10")

	def test_default_period_is_latest_stored(self):
		result = api.values(periods=1)
		self.assertEqual(result["periods"], ["2026-10"])

	def test_bad_period_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			api.values(period="10/2026")

	def test_permission_matrix(self):
		assert_permission_matrix(self, "IC Indicator Value")
