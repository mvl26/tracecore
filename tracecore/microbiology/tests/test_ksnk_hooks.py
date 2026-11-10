"""M14 đăng ký tự đánh giá QĐ 38 (FEAT-065; FR-M9-29; hook ``tracecore_ic_self_checks``; A-145 D8)."""

from tracecore.microbiology import self_checks
from tracecore.microbiology.tests.factories import make_organism, new_isolate
from tracecore.tests.utils import IsolatedTestCase


class TestAmrSelfCheck(IsolatedTestCase):
	def test_isolates_of_the_year_need_r01_confirmation(self):
		self.assertEqual(self_checks.amr_surveillance(1990)["status"], "Not met")
		make_organism()
		new_isolate(collected_on="2026-08-10")
		result = self_checks.amr_surveillance(2026)
		self.assertEqual(result["status"], "Needs confirmation")
		self.assertNotIn("BN", result["source_ref"])
		self.assertIn("amr_surveillance", self_checks.register())
