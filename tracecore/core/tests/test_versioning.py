"""Mã phiên bản dùng chung `<TIỀN TỐ>-<mã>-V<n>` (architecture §5.3.3, A-132; FEAT-060)."""

from frappe.tests.utils import FrappeTestCase

from tracecore.core import versioning


class TestVersioning(FrappeTestCase):
	def test_make_versioned_code(self):
		self.assertEqual(versioning.make_versioned_code("MP", "PNC", 2), "MP-PNC-V2")

	def test_code_is_normalized(self):
		self.assertEqual(versioning.normalize_code(" pnc-01 "), "PNC-01")

	def test_invalid_code_rejected(self):
		for raw in ("", "PNC 01", "PNC/1", "Ư-1", "-PNC"):
			with self.subTest(raw=raw), self.assertRaises(ValueError):
				versioning.normalize_code(raw)

	def test_version_must_be_positive(self):
		with self.assertRaises(ValueError):
			versioning.make_versioned_code("MP", "PNC", 0)
