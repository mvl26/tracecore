"""Sổ hàm tính chỉ số KSNK qua hook ``tracecore_ic_indicators`` (FEAT-056, A-113, architecture §5.2)."""

from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from tracecore.core import indicators


def _fake(period, department):
	return (1, 2, 2)


class TestIndicatorRegistry(FrappeTestCase):
	def test_registry_merges_modules_and_resolves_paths(self):
		results = [
			{"HH_RATE": _fake},
			{"HAI_RATE": "tracecore.core.tests.test_indicators._fake"},
		]
		with patch("tracecore.core.indicators.extension.run", return_value=results):
			registry = indicators.registry()
		self.assertEqual(set(registry), {"HH_RATE", "HAI_RATE"})
		self.assertIs(registry["HAI_RATE"], _fake)

	def test_duplicate_key_from_two_modules_is_rejected(self):
		with patch("tracecore.core.indicators.extension.run", return_value=[{"X": _fake}, {"X": _fake}]):
			with self.assertRaises(ValueError):
				indicators.registry()

	def test_no_module_registered_yet_is_empty(self):
		with patch("tracecore.core.indicators.extension.run", return_value=[]):
			self.assertEqual(indicators.registry(), {})
