"""A-154 (FEAT-096): T4 kiểm lô chỉ thị theo loại chỉ thị của loại bộ (FR-M2-07.2, FR-M2-07.3)."""

from datetime import datetime, timezone

import frappe
from frappe.utils import getdate

from tracecore.core.errors import BlockedError
from tracecore.reprocessing import packing
from tracecore.tests.factories import make_ci_batch, make_t4_ready_set
from tracecore.tests.utils import IsolatedTestCase, bru

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

STATION = "TR-004"


def _utc_now():
	return datetime.now(timezone.utc).replace(tzinfo=None)


def _ready(ci_class):
	ready = make_t4_ready_set()
	frappe.db.set_value("Instrument Set Type", ready.set_type, "ci_class", ci_class)
	return ready


def _generate(ready, ci_batch):
	return packing.generate(
		set_id=ready.set_id,
		station=STATION,
		confirmed=list(ready.instruments),
		ci_batch=ci_batch,
		pack_type=ready.pack_type,
		maint_actions=[],
		client_ts=_utc_now(),
	)


class TestCiBlockByClass(IsolatedTestCase):
	def test_declared_class_limits_the_lots(self):
		four = make_ci_batch("Steam", "4", expiry_days=40)
		five = make_ci_batch("Steam", "5", expiry_days=41)
		ready = _ready("4")
		block = packing.get_context(ready.set_id, STATION)["ci"]
		self.assertIs(block["required"], True)
		self.assertEqual(block["ci_class"], "4")
		self.assertEqual(block["classes"], ["4"])
		batches = [lot["batch"] for lot in block["lots"]]
		self.assertIn(four, batches)
		self.assertNotIn(five, batches)

	def test_blank_class_keeps_5_and_6(self):
		ready = _ready("")
		block = packing.get_context(ready.set_id, STATION)["ci"]
		self.assertIs(block["required"], True)
		self.assertEqual(block["classes"], ["5", "6"])

	def test_not_required_has_no_lots(self):
		ready = _ready("Not Needed")
		block = packing.get_context(ready.set_id, STATION)["ci"]
		self.assertIs(block["required"], False)
		self.assertEqual(block["classes"], [])
		self.assertEqual(block["lots"], [])


class TestResolveByClass(IsolatedTestCase):
	@bru("BRU-REP-013")
	def test_lot_of_another_class_is_refused_naming_the_needed_class(self):
		five = make_ci_batch("Steam", "5", expiry_days=30)
		with self.assertRaises(BlockedError) as raised:
			packing.resolve_ci_batch(five, "Steam", getdate(), ("4",))
		self.assertEqual(raised.exception.block.code, "CI_LOT_INVALID")
		self.assertIn("4", raised.exception.block.reason)

	def test_class_4_lot_is_accepted_when_the_set_needs_class_4(self):
		four = make_ci_batch("Steam", "4", expiry_days=30)
		self.assertEqual(packing.resolve_ci_batch(four, "Steam", getdate(), ("4",))["ci_class"], "4")


class TestGenerateByClass(IsolatedTestCase):
	@bru("BRU-REP-013")
	def test_generate_refuses_a_lot_of_the_wrong_class(self):
		ready = _ready("6")  # ready.ci_batch là lô loại 5
		with self.assertRaises(BlockedError) as raised:
			_generate(ready, ready.ci_batch)
		self.assertEqual(raised.exception.block.code, "CI_LOT_INVALID")
		self.assertFalse(frappe.get_all("Pack", filters={"set_unit": ready.set_id}))

	def test_generate_with_the_declared_class(self):
		ready = _ready("4")
		four = make_ci_batch("Steam", "4", expiry_days=30)
		cycle_id = _generate(ready, four)["pack"]["cycle_id"]
		self.assertEqual(frappe.db.get_value("Pack", cycle_id, "ci_batch"), four)

	def test_not_required_packs_without_a_lot(self):
		ready = _ready("Not Needed")
		cycle_id = _generate(ready, None)["pack"]["cycle_id"]
		self.assertFalse(frappe.db.get_value("Pack", cycle_id, "ci_batch"))

	def test_not_required_ignores_a_lot_sent_anyway(self):
		ready = _ready("Not Needed")
		cycle_id = _generate(ready, ready.ci_batch)["pack"]["cycle_id"]
		self.assertFalse(frappe.db.get_value("Pack", cycle_id, "ci_batch"))
