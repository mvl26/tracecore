from frappe.tests.utils import FrappeTestCase

from tracecore.par import check
from tracecore.tests.utils import bru


def _ctx(cycles_used, max_cycles=300):
	return {
		"set_unit": {
			"name": "SU-TEST-0001",
			"set_type": "TST",
			"status": "Clean",
			"cycles_used": cycles_used,
			"max_cycles": max_cycles,
			"active_cycle_id": None,
			"current_cycle_no": 1,
			"is_loaner": 0,
		},
		"set_type": {"name": "TST"},
		"station": "T4",
		"maint_actions": [],
	}


class TestParCheck(FrappeTestCase):
	@bru("BRU-PAR-002")
	def test_par_blocks_at_max(self):
		block = check.check_pack(_ctx(300, 300))
		self.assertIsNotNone(block)
		self.assertEqual(block.code, "PAR_EXCEEDED")
		self.assertEqual(block.http_status, 409)
		self.assertTrue(block.title)
		self.assertIn("SU-TEST-0001", block.reason)
		self.assertIn("300", block.reason)
		# hành động nêu đề nghị ghi đè (FEAT-032) thay vì cho đóng gói
		self.assertIn("FEAT-032", block.action)

		self.assertIsNone(check.check_pack(_ctx(299, 300)))
		self.assertIsNone(check.check_pack(_ctx(0, 300)))

	@bru("BRU-PAR-002")
	def test_par_blocks_beyond_max(self):
		# vượt cơ số (ghi đè đã hết hạn, dữ liệu cũ…) vẫn chặn
		block = check.check_pack(_ctx(305, 300))
		self.assertEqual(block.code, "PAR_EXCEEDED")
		self.assertIn("305", block.reason)

	def test_par_context_state(self):
		cases = [
			(0, 300, 0, "ok"),
			(100, 300, 33, "ok"),
			(269, 300, 89, "ok"),
			(270, 300, 90, "warn"),
			(299, 300, 99, "warn"),
			(300, 300, 100, "blocked"),
			(450, 300, 150, "blocked"),
			(2, 3, 66, "ok"),  # làm tròn xuống, không làm tròn lên
			(9, 10, 90, "warn"),
		]
		for used, limit, percent, state in cases:
			result = check.pack_context(_ctx(used, limit))
			self.assertEqual(
				result,
				{"par": {"cycles_used": used, "max_cycles": limit, "percent": percent, "state": state}},
				msg=(used, limit),
			)

	def test_par_context_percent_is_an_integer(self):
		par = check.pack_context(_ctx(270, 300))["par"]
		self.assertIs(type(par["percent"]), int)
		self.assertEqual(par["percent"], 90)

	def test_missing_limit_is_not_a_limit(self):
		# Set Unit luôn có cơ số > 0; thiếu/0 thì không chia cho 0 và không chặn
		for limit in (0, None):
			self.assertIsNone(check.check_pack(_ctx(50, limit)))
			self.assertEqual(
				check.pack_context(_ctx(50, limit)),
				{"par": {"cycles_used": 50, "max_cycles": 0, "percent": 0, "state": "ok"}},
			)
