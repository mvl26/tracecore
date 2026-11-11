"""Engine chỉ số KSNK: tính, khóa, mở khóa kỳ (FEAT-056 AC-5..AC-8; FR-M9-27, FR-M9-27.1; BRU-RPT-001, BRU-RPT-003;
architecture §6.10; plan D1)."""

from unittest.mock import patch

import frappe

from tracecore.admin_reports import indicator
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase, bru

PERIOD = "2026-10"
# dữ liệu nguồn giả: (source_method, department hoặc None) -> (tử số, mẫu số, cỡ mẫu)
SOURCE: dict = {}


def _calc(key):
	def fn(period, department):
		return SOURCE.get((key, department), (0, 0, 0))

	return fn


REGISTRY = {"T_PCT": _calc("T_PCT"), "T_RATE": _calc("T_RATE"), "T_COUNT": _calc("T_COUNT")}


def _indicator(code, kind, method, **values):
	"""Tạo hoặc đặt lại chỉ số thử (danh mục có Audit, không xóa được)."""
	fields = {
		"indicator_name": code,
		"measure_group": "Hand Hygiene",
		"kind": kind,
		"is_active": 1,
		"source_method": method,
		"min_sample": 0,
		"national_target": 0,
		"target_direction": "",
		**values,
	}
	with patch("tracecore.core.indicators.registry", return_value=REGISTRY):
		if frappe.db.exists("IC Indicator", code):
			doc = frappe.get_doc("IC Indicator", code)
			doc.update(fields)
			return doc.save(ignore_permissions=True)
		return frappe.get_doc({"doctype": "IC Indicator", "code": code, **fields}).insert(
			ignore_permissions=True
		)


def _value(code, department=None, period=PERIOD):
	return frappe.db.get_value(
		"IC Indicator Value",
		{"indicator": code, "period": period, "department": department or ("is", "not set")},
		["name", "numerator", "denominator", "value", "sample_size", "sample_note", "locked"],
		as_dict=True,
	)


class TestIndicatorEngine(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		SOURCE.clear()
		frappe.db.delete("IC Indicator Value")
		frappe.db.set_value("IC Indicator", {"is_active": 1}, "is_active", 0)
		self.dept_a = factories.make_department("KSNK Test A")
		self.dept_b = factories.make_department("KSNK Test B")
		_indicator("T-PCT", "Percentage", "T_PCT", min_sample=30)
		_indicator("T-RATE", "Rate per 1000", "T_RATE")
		_indicator("T-COUNT", "Count", "T_COUNT")
		_indicator("T-OFF", "Count", "T_COUNT", is_active=0)
		self.registry = patch("tracecore.core.indicators.registry", return_value=REGISTRY)
		self.registry.start()
		self.addCleanup(self.registry.stop)
		self.addCleanup(frappe.set_user, "Administrator")

	def test_lock_writes_hospital_and_department_values(self):
		SOURCE[("T_PCT", None)] = (78, 100, 100)
		SOURCE[("T_PCT", self.dept_a)] = (40, 50, 50)
		indicator.lock_period(PERIOD)
		whole = _value("T-PCT")
		self.assertEqual((whole.numerator, whole.denominator, whole.value), (78, 100, 78))
		self.assertEqual(whole.locked, 1)
		self.assertTrue(whole.name.startswith("IV-2026-") or whole.name.startswith("IV-"))
		self.assertEqual(_value("T-PCT", self.dept_a).value, 80)
		self.assertIsNone(_value("T-PCT", self.dept_b))  # khoa không có dữ liệu: không ghi dòng
		self.assertIsNone(_value("T-OFF"))  # chỉ số tắt: không tính
		self.assertTrue(indicator.is_locked(PERIOD))

	def test_kind_formulas(self):
		SOURCE[("T_RATE", None)] = (21, 10000, 10000)
		SOURCE[("T_COUNT", None)] = (7, 0, 0)
		indicator.lock_period(PERIOD)
		self.assertAlmostEqual(_value("T-RATE").value, 2.1)
		count = _value("T-COUNT")
		self.assertEqual((count.value, count.sample_note), (7, ""))

	@bru("BRU-RPT-001")
	def test_zero_denominator_is_not_calculated_not_zero(self):
		SOURCE[("T_RATE", None)] = (0, 0, 0)
		SOURCE[("T_RATE", self.dept_a)] = (1, 0, 0)
		indicator.lock_period(PERIOD)
		row = _value("T-RATE", self.dept_a)
		self.assertEqual(row.sample_note, "Not calculated")
		self.assertEqual(indicator.display_value(row), None)

	def test_small_sample_is_flagged(self):
		SOURCE[("T_PCT", None)] = (9, 10, 10)
		indicator.lock_period(PERIOD)
		row = _value("T-PCT")
		self.assertEqual((row.value, row.sample_note), (90, "Insufficient sample"))

	@bru("BRU-RPT-003")
	def test_locked_period_does_not_change_when_source_changes(self):
		SOURCE[("T_PCT", None)] = (78, 100, 100)
		indicator.lock_period(PERIOD)
		SOURCE[("T_PCT", None)] = (99, 100, 100)
		indicator.compute_period(PERIOD)
		indicator.lock_period(PERIOD)
		self.assertEqual(_value("T-PCT").value, 78)

	def test_unlocked_period_can_be_recomputed_before_lock(self):
		SOURCE[("T_PCT", None)] = (78, 100, 100)
		indicator.compute_period(PERIOD)
		self.assertEqual(_value("T-PCT").locked, 0)
		SOURCE[("T_PCT", None)] = (80, 100, 100)
		indicator.compute_period(PERIOD)
		self.assertEqual(_value("T-PCT").value, 80)
		self.assertFalse(indicator.is_locked(PERIOD))

	@bru("BRU-RPT-003")
	def test_r01_unlock_with_reason_recomputes_and_audits(self):
		SOURCE[("T_PCT", None)] = (78, 100, 100)
		indicator.lock_period(PERIOD)
		frappe.set_user(factories.make_user("ksnk-r01@example.com", ["TC R01"]))
		indicator.unlock_period(PERIOD, "Bổ sung ca NKVM sau ra viện")
		self.assertFalse(indicator.is_locked(PERIOD))
		SOURCE[("T_PCT", None)] = (82, 100, 100)
		indicator.lock_period(PERIOD)
		self.assertEqual(_value("T-PCT").value, 82)
		frappe.set_user("Administrator")
		logs = frappe.get_all(
			"Audit Log",
			filters={"ref_doctype": "IC Indicator Value"},
			fields=["action", "reason", "old_value", "new_value"],
			order_by="creation asc",
		)
		actions = [log.action for log in logs]
		self.assertIn("Override", actions)
		unlock = next(log for log in logs if log.action == "Override")
		self.assertEqual(unlock.reason, "Bổ sung ca NKVM sau ra viện")
		# dòng khác chỉ đổi computed_on cũng có Update; lấy dòng đổi giá trị
		update = next(
			log for log in logs if log.action == "Update" and "value" in frappe.parse_json(log.new_value)
		)
		self.assertEqual(frappe.parse_json(update.old_value)["value"], 78)
		self.assertEqual(frappe.parse_json(update.new_value)["value"], 82)

	def test_unlock_needs_r01_and_reason(self):
		SOURCE[("T_PCT", None)] = (78, 100, 100)
		indicator.lock_period(PERIOD)
		r11 = factories.make_user("ksnk-r11@example.com", ["TC R11"])
		r01 = factories.make_user("ksnk-r01@example.com", ["TC R01"])
		frappe.set_user(r11)
		with self.assertRaises(frappe.PermissionError):
			indicator.unlock_period(PERIOD, "lý do")
		frappe.set_user(r01)
		with self.assertRaises(frappe.ValidationError):
			indicator.unlock_period(PERIOD, "  ")
		self.assertTrue(indicator.is_locked(PERIOD))

	def test_period_format(self):
		for bad in ("2026-13", "2026/10", "10-2026", ""):
			with self.assertRaises(frappe.ValidationError, msg=bad):
				indicator.compute_period(bad)
