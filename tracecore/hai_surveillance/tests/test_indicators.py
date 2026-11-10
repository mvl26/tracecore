"""Tỷ suất NKBV theo khoa và kỳ (FEAT-063; FR-M13-10, 10.1, 10.2; BRU-HAI-006; A-144 d)."""

import frappe

from tracecore.core import indicators as registry
from tracecore.hai_surveillance import cases, indicators
from tracecore.hai_surveillance.tests import factories as f
from tracecore.hai_surveillance.tests import hai_fixtures as h
from tracecore.tests.utils import IsolatedTestCase, bru

MONTH = "2026-08"


class TestRates(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		for code in ("TVAP", "TCAUTI"):
			h.clear_definitions(code)
		h.make_definition("TVAP", effective_from="2026-01-01", hours=0, days=0)
		h.make_definition(
			"TCAUTI",
			device="Urinary Catheter",
			site="Catheter-associated Urinary Tract Infection",
			effective_from="2026-01-01",
			hours=0,
			days=0,
		)
		frappe.db.delete("IC Reporting Period", {"month": MONTH})
		self.ward = f.make_ward("KSNK Rate ICU")
		frappe.db.delete("Ward Daily Census", {"department": self.ward})
		frappe.db.delete("HAI Case", {"department": self.ward})
		# 410 ngày thở máy, 820 ngày nằm viện, 0 ngày thông tiểu trong tháng 8
		for day in list(h.month_days(MONTH))[:10]:
			f.make_census(self.ward, census_date=day, patients=82, vent=41, cvc=10, urinary=0)

	def _confirmed(self, code, onset="2026-08-15", def_code="TVAP"):
		doc = h.make_case(
			self.ward, code=code, onset=onset, admitted="2026-08-01 08:00:00", def_code=def_code
		)
		cases.decide(doc.name, cases.CONFIRMED, exception_reason="test")
		return doc.name

	def test_registered_in_hook(self):
		methods = registry.registry()
		for key in indicators.KEYS:
			self.assertIn(key, methods)

	def test_vap_rate_two_cases_on_410_vent_days(self):
		self._confirmed("BN-RATE-0001")
		self._confirmed("BN-RATE-0002")
		h.make_case(
			self.ward, code="BN-RATE-0003", onset="2026-08-16", admitted="2026-08-01 08:00:00"
		)  # Nghi ngờ
		numerator, denominator, _size = indicators.vap_rate(MONTH, self.ward)
		self.assertEqual((numerator, denominator), (2, 410))
		value, note = indicators.measure("Rate per 1000", numerator, denominator)
		self.assertAlmostEqual(value, 4.878, places=3)  # FR-M13-10.1: hiển thị 4,9 ‰
		self.assertEqual(note, "")
		self.assertEqual(indicators.hai_rate(MONTH, self.ward)[:2], (2, 820))

	@bru("BRU-HAI-006")
	def test_zero_denominator_is_not_calculated(self):
		self._confirmed("BN-RATE-0004", def_code="TCAUTI")
		numerator, denominator, _size = indicators.cauti_rate(MONTH, self.ward)
		self.assertEqual((numerator, denominator), (1, 0))
		value, note = indicators.measure("Rate per 1000", numerator, denominator)
		self.assertEqual(note, "Not calculated")  # FR-M13-10.2

	def test_excluded_and_other_month_not_counted(self):
		doc = h.make_case(self.ward, code="BN-RATE-0005", onset="2026-08-15", admitted="2026-08-01 08:00:00")
		cases.decide(doc.name, cases.EXCLUDED, reason="Không đủ tiêu chí")
		self._confirmed("BN-RATE-0006", onset="2026-09-02")
		self.assertEqual(indicators.vap_rate(MONTH, self.ward)[0], 0)

	def test_hospital_wide_sums_wards(self):
		self._confirmed("BN-RATE-0007")
		numerator, denominator, _size = indicators.vap_rate(MONTH, None)
		self.assertGreaterEqual(numerator, 1)
		self.assertGreaterEqual(denominator, 410)

	def test_device_utilization_percentage(self):
		self.assertEqual(indicators.vent_utilization(MONTH, self.ward)[:2], (410, 820))

	def test_department_table(self):
		self._confirmed("BN-RATE-0008")
		rows = {row["department"]: row for row in indicators.by_department(MONTH)}
		row = rows[self.ward]
		self.assertEqual(row["patient_days"], 820)
		self.assertEqual(row["cases"], 1)
		self.assertIsNone(row["cauti"])  # mẫu số 0 → không có giá trị (UI hiện "Không tính")
		self.assertAlmostEqual(row["vap"], 2.439, places=3)
