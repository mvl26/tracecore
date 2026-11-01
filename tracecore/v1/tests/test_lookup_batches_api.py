"""RPC `lookup.batches` (A-87, #1818, #1819): chọn tay lô/mẻ chờ dỡ, không còn mã bộ ở bước dỡ; chọn tay ghi Audit Log."""

import re

import frappe

from tracecore.core.errors import BlockedError
from tracecore.reprocessing import sterilizing, washing
from tracecore.tests.factories import (
	make_equipment,
	make_load,
	make_load_ready_pack,
	make_sterilize_program,
	make_user,
	make_wash_batch,
	make_wash_machine,
	make_wash_program,
	make_wash_ready_set,
)
from tracecore.v1 import load as load_api
from tracecore.v1 import lookup as lookup_api
from tracecore.v1 import release as release_api
from tracecore.v1 import wash as wash_api
from tracecore.v1.tests.station_fixtures import make_station_session
from tracecore.v1.tests.test_lookup_api import TOKENS, LookupCase, call, ids, station_of

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


def _asset(*parts):
	with open(frappe.get_app_path("tracecore", *parts), encoding="utf-8") as handle:
		return handle.read()


class BatchCase(LookupCase):
	def washing(self, status="Running", machine=None):
		machine = machine or make_wash_machine()
		program = make_wash_program(machine)
		return make_wash_batch(machine, program, [make_wash_ready_set()], status=status)

	def sterilizing(self, status="Running", machine=None):
		machine = machine or make_equipment(
			"Hấp mẻ", "Steam Sterilizer", serial="SN-" + frappe.generate_hash(length=6)
		)
		program = make_sterilize_program(machine)
		return make_load(machine, program, [make_load_ready_pack()], status=status)


class TestBatchesList(BatchCase):
	def test_t2_lists_only_open_batches_with_columns(self):
		running = self.washing()
		awaiting = self.washing(status="Awaiting Result")
		closed = self.washing(status="Passed")
		result = call(lookup_api.batches, self.login("T2"), screen="wash")
		self.assertTrue(result["ok"])
		found = ids(result)
		self.assertIn(running.name, found)
		self.assertIn(awaiting.name, found)
		self.assertNotIn(closed.name, found)
		self.assertFalse([code for code in found if not code.startswith("LR-")])
		row = next(item for item in result["items"] if item["id"] == running.name)
		self.assertEqual(row["raw"], running.name)
		self.assertEqual(row["equipment"], running.equipment)
		self.assertEqual(row["program"], running.program)
		self.assertEqual(row["status"], "Running")
		self.assertTrue(row["started_at"])
		self.assertEqual(row["count"], 1)
		self.assertIn(running.equipment, row["label"])

	def test_t5_unload_lists_open_loads_of_the_scanned_machine(self):
		wanted = self.sterilizing()
		complete = self.sterilizing(status="Cycle Complete")
		quarantine = self.sterilizing(status="Quarantine")
		station = self.login("T5")
		found = ids(call(lookup_api.batches, station, screen="sterilize", purpose="unload"))
		self.assertIn(wanted.name, found)
		self.assertIn(complete.name, found)
		self.assertNotIn(quarantine.name, found)
		only = call(
			lookup_api.batches, station, screen="sterilize", purpose="unload", equipment=wanted.equipment
		)
		self.assertEqual(ids(only), [wanted.name])
		self.assertEqual(only["items"][0]["requires_bi"], 0)

	def test_t5_bi_lists_only_quarantine_loads(self):
		quarantine = self.sterilizing(status="Quarantine")
		running = self.sterilizing()
		found = ids(call(lookup_api.batches, self.login("T5"), screen="sterilize", purpose="bi"))
		self.assertIn(quarantine.name, found)
		self.assertNotIn(running.name, found)

	def test_search_and_pagination(self):
		first = self.washing()
		self.washing()
		station = self.login("T2")
		self.assertEqual(ids(call(lookup_api.batches, station, screen="wash", q=first.name)), [first.name])
		page = call(lookup_api.batches, station, screen="wash", page_length=1)
		self.assertEqual(len(page["items"]), 1)
		self.assertGreaterEqual(page["total"], 2)

	def test_screen_without_batches_is_refused_and_is_read_only(self):
		before = frappe.db.count("Audit Log", {"action": "Manual Entry"})
		result = call(lookup_api.batches, self.login("T1"), screen="receive")
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "STATION_WRONG_STEP")
		self.assertEqual(frappe.db.count("Audit Log", {"action": "Manual Entry"}), before)

	def test_unload_only_role_can_list_wash_batches(self):
		user = make_user("pick-r04-unload@tracecore.test", roles=["TC R04"])
		station = station_of("T2")
		TOKENS[(user, station)] = make_station_session(user, station=station)["token"]
		frappe.set_user(user)
		self.assertTrue(call(lookup_api.batches, station, screen="wash")["ok"])

	def test_release_role_can_list_loads(self):
		user = make_user("pick-r01-release@tracecore.test", roles=["TC R01"])
		station = station_of("T5")
		TOKENS[(user, station)] = make_station_session(user, station=station)["token"]
		frappe.set_user(user)
		self.assertTrue(call(lookup_api.batches, station, screen="sterilize", purpose="bi")["ok"])


class TestManualUnloadAudit(BatchCase):
	def audit(self, name):
		return frappe.db.get_value(
			"Audit Log", {"action": "Manual Entry", "ref_name": name}, ["reason", "entry_mode"], as_dict=True
		)

	def test_wash_unload_logs_manual_entry(self):
		batch = self.washing()
		station = self.login("T2")
		result = call(
			wash_api.unload,
			station,
			batch=batch.name,
			raw=batch.name,
			entry_mode="Manual",
			manual_reason="Scanner broken",
		)
		self.assertEqual(result["kind"], "wash_batch")
		self.assertEqual(self.audit(batch.name).reason, "Scanner broken")

	def test_manual_entry_needs_a_reason(self):
		batch = self.washing()
		result = call(
			wash_api.unload, self.login("T2"), batch=batch.name, raw=batch.name, entry_mode="Manual"
		)
		self.assertEqual(result["error"]["code"], "MANUAL_REASON_REQUIRED")

	def test_scan_writes_no_manual_entry(self):
		batch = self.washing()
		call(wash_api.unload, self.login("T2"), batch=batch.name, raw=batch.name)
		self.assertIsNone(self.audit(batch.name))

	def test_load_data_scan_logs_manual_entry(self):
		load = self.sterilizing()
		result = call(
			load_api.data_scan,
			self.login("T5"),
			load=load.name,
			raw=load.name,
			entry_mode="Manual",
			manual_reason="Other",
		)
		self.assertEqual(result["kind"], "load")
		self.assertEqual(self.audit(load.name).reason, "Other")

	def test_release_context_logs_manual_entry(self):
		load = self.sterilizing()
		result = call(
			release_api.context,
			self.login("T5"),
			load=load.name,
			equipment_raw=load.equipment,
			load_raw=load.name,
			entry_mode="Manual",
			manual_reason="Label unreadable or torn",
		)
		self.assertTrue(result["ok"])
		self.assertEqual(self.audit(load.name).reason, "Label unreadable or torn")


class TestSetCodeAtUnload(BatchCase):
	def test_wash_unload_explains_a_set_code(self):
		batch = self.washing()
		unit = make_wash_ready_set()
		with self.assertRaises(BlockedError) as caught:
			washing._scan_kind(batch, unit.name)
		self.assertEqual(caught.exception.block.code, "SCAN_INVALID")
		self.assertIn("LR-", str(caught.exception.block.title))

	def test_load_explains_a_pack_code(self):
		load = self.sterilizing()
		pack = make_load_ready_pack()
		with self.assertRaises(BlockedError) as caught:
			sterilizing._scan_kind(load, pack.name)
		self.assertEqual(caught.exception.block.code, "SCAN_INVALID")
		self.assertIn("ME-", str(caught.exception.block.title))


class TestPickerAssets(frappe.tests.utils.FrappeTestCase):
	def test_picker_uses_the_screen_context(self):
		picker = _asset("public", "js", "station_picker.js")
		self.assertIn("pickContext", picker)
		self.assertIn('"batches"', picker)
		for method in (
			"tracecore.v1.wash.unload",
			"tracecore.v1.load.data_scan",
			"tracecore.v1.release.context",
		):
			self.assertIn(f'"{method}"', picker)

	def test_unload_screens_define_context_and_codes(self):
		for name in ("station_t2.js", "station_t5.js", "station_t5b.js"):
			script = _asset("public", "js", name)
			self.assertIn("pickContext()", script, name)
			self.assertIn("pickCodes(item)", script, name)
			self.assertIn("tcIsSetOrPackCode", script, name)

	def test_t2_keeps_indicator_lot_before_the_set_code_hint(self):
		script = _asset("public", "js", "station_t2.js")
		lot = script.index('code.kind === "set" && this.indicator')
		hint = script.index("tcIsSetOrPackCode(raw)", lot)
		self.assertLess(lot, hint)

	def test_set_code_message_is_translated(self):
		text = _asset("translations", "vi.csv")
		self.assertIn("Đây là mã bộ dụng cụ – vui lòng quét mã mẻ (ME-…)", text)  # noqa: RUF001
		self.assertIn("Đây là mã bộ dụng cụ – vui lòng quét mã lô (LR-…)", text)  # noqa: RUF001

	def test_t5b_has_a_waiting_list(self):
		script = _asset("public", "js", "station_t5b.js")
		self.assertTrue(re.search(r"waitingHtml\(\)", script))
