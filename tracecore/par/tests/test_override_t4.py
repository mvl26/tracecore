"""Luồng T4 ↔ ghi đè cơ số (FEAT-032, UC-31, FR-M8-03, FR-M8-04): chặn, đề nghị, duyệt, đóng gói trong phạm vi.

M2 (`reprocessing.packing`) chỉ gọi hook; M8 (`par`) thay stub của FEAT-018 sau cùng interface (P-5).
"""

import frappe
from frappe.utils import add_days, today

from tracecore.core import step_gate
from tracecore.par import check, override
from tracecore.par.tests.test_override import OverrideCase, blocked
from tracecore.reprocessing import packing
from tracecore.reprocessing.tests.test_packing import STATION, _generate, _packs_of
from tracecore.tests.factories import make_ci_batch, make_t4_ready_set
from tracecore.tests.utils import bru

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


def _exhausted(max_cycles=5):
	"""Bộ sẵn sàng T4 đã dùng hết cơ số (bộ đếm do fixture đặt, FEAT-023 làm bộ đếm thật)."""
	ready = make_t4_ready_set(max_cycles=max_cycles)
	frappe.db.set_value("Set Unit", ready.set_id, "cycles_used", max_cycles)
	return ready


class TestT4OverrideFlow(OverrideCase):
	@bru("BRU-PAR-002")
	def test_first_block_moves_set_to_end_of_life_then_every_station_refuses(self):
		ready = _exhausted()
		block = blocked(self, packing.get_context, ready.set_id, STATION)
		self.assertEqual(block.code, "PAR_EXCEEDED")
		self.assertEqual(frappe.db.get_value("Set Unit", ready.set_id, "status"), "End of Life")
		again = blocked(self, packing.get_context, ready.set_id, STATION)
		self.assertEqual((again.code, again.http_status), ("SET_END_OF_LIFE", 409))
		self.assertEqual(blocked(self, _generate, ready).code, "SET_END_OF_LIFE")
		self.assertEqual(_packs_of(ready.set_id), [])
		for step in step_gate.STEPS:
			self.assertEqual(step_gate.check(ready.set_id, step).code, "SET_END_OF_LIFE")

	@bru("BRU-PAR-002")
	def test_generate_blocked_when_par_exceeded_names_instrument_and_rolls_back(self):
		ready = make_t4_ready_set(max_cycles=300)
		frappe.db.set_value("Instrument", "KC-01", {"max_cycles": 5})
		frappe.db.set_value("Set Unit", ready.set_id, "cycles_used", 5)
		block = blocked(self, _generate, ready)
		self.assertEqual(block.code, "PAR_EXCEEDED")
		self.assertEqual([item["instrument"] for item in block.items], ["KC-01"])
		self.assertEqual(_packs_of(ready.set_id), [])
		# generate hoàn tác về savepoint: bộ chưa chuyển Hết vòng đời, màn T4 quét (get_context) mới chuyển
		self.assertEqual(frappe.db.get_value("Set Unit", ready.set_id, "status"), "Processing")

	@bru("BRU-PAR-004")
	def test_request_approve_then_pack_within_extra_cycles(self):
		ready = _exhausted()
		blocked(self, packing.get_context, ready.set_id, STATION)
		name = override.request(ready.set_id, "Ca mổ cấp cứu", station=STATION).name
		self.approve(name, extra=1, valid_until=add_days(today(), 2))

		context = packing.get_context(ready.set_id, STATION)
		self.assertEqual(context["par"]["state"], "override")
		self.assertEqual(context["par"]["override"]["name"], name)
		self.assertEqual(context["set"]["status"], "Processing")

		result = _generate(ready)
		self.assertTrue(result["pack"]["cycle_id"].startswith("CY-"))
		row = frappe.db.get_value(
			"Par Override", name, ["status", "cycles_consumed", "last_cycle_no", "expiry_cause"], as_dict=True
		)
		self.assertEqual(
			(row.status, row.cycles_consumed, row.last_cycle_no, row.expiry_cause),
			("Expired", 1, 1, "Cycles Used"),
		)

	@bru("BRU-PAR-004")
	def test_void_and_pack_again_in_same_cycle_does_not_consume_more(self):
		ready = _exhausted()
		blocked(self, packing.get_context, ready.set_id, STATION)
		name = override.request(ready.set_id, "Ca mổ cấp cứu").name
		self.approve(name, extra=1)
		first = _generate(ready)["pack"]["cycle_id"]
		packing.void(first, "Label Damaged", STATION)
		second = _generate(ready, ci_batch=make_ci_batch("Steam"))["pack"]["cycle_id"]
		self.assertNotEqual(first, second)
		self.assertEqual(frappe.db.get_value("Par Override", name, "cycles_consumed"), 1)

	@bru("BRU-PAR-004")
	def test_expired_override_blocks_again_at_next_cycle(self):
		ready = _exhausted()
		blocked(self, packing.get_context, ready.set_id, STATION)
		name = override.request(ready.set_id, "Cần gấp").name
		self.approve(name, extra=1)
		_generate(ready)
		# chu trình kế tiếp: bộ đã Expired → chặn lại và về Hết vòng đời (UC-31 A2, FR-M2-18.1)
		step_gate.start_cycle(ready.set_id)
		for step in ("T1", "T2", "T3"):
			step_gate.record(ready.set_id, step, "Pass")
		self.assertEqual(blocked(self, packing.get_context, ready.set_id, STATION).code, "PAR_EXCEEDED")
		self.assertEqual(frappe.db.get_value("Set Unit", ready.set_id, "status"), "End of Life")

	def test_pending_request_is_named_in_the_block_action(self):
		ready = _exhausted()
		blocked(self, packing.get_context, ready.set_id, STATION)
		name = override.request(ready.set_id, "Chờ").name
		frappe.db.set_value("Set Unit", ready.set_id, "status", "Processing")
		block = blocked(self, packing.get_context, ready.set_id, STATION)
		self.assertEqual(block.code, "PAR_EXCEEDED")
		self.assertIn(name, block.action)

	def test_stub_replaced_action_text_no_longer_mentions_feat_032(self):
		ready = _exhausted()
		block = blocked(self, packing.get_context, ready.set_id, STATION)
		self.assertNotIn("FEAT-032", block.action)
		self.assertEqual(check.evaluate(ready.set_id)["state"], "blocked")
