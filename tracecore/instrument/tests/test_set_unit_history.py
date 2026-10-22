"""Vòng đời, lịch sử và thanh lý Set Unit (FEAT-016 Task 6; FR-M1-06, FR-M1-06.2, FR-M1-05.2; BRU-ID-001;
AC-3, AC-6, AC-7; A-09 G13, G14)."""

from unittest.mock import patch

import frappe
from frappe.utils import now_datetime

from tracecore.core import audit, code_registry, gs1, print_server, step_gate
from tracecore.core import print as core_print
from tracecore.core.errors import BlockedError
from tracecore.instrument import bom_versions, set_tags, set_units
from tracecore.tests.factories import (
	BOM_INSTRUMENT_METHODS,
	deactivate_printers,
	make_department,
	make_instrument,
	make_label_items,
	make_pack,
	make_printer,
	make_set_type,
	next_free_test_cycle_id,
)
from tracecore.tests.utils import IsolatedTestCase, allow_local_printers, bru

# Set Unit -> Department, Zone Station, Instrument Set Type (-> Item), User; Print Job -> Printer -> Item, User;
# Pack -> Item, Batch, Employee, User
test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

STATION = "TR-004"


def _blocked(test, fn, *args, **kwargs):
	with test.assertRaises(BlockedError) as raised:
		fn(*args, **kwargs)
	return raised.exception.block


class SetUnitLifecycleCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		deactivate_printers(STATION)
		self.label_item = make_label_items()[0]
		allow_local_printers(self)
		enqueue = patch.object(frappe, "enqueue")
		enqueue.start()
		self.addCleanup(enqueue.stop)
		make_instrument("SU-THIST", max_cycles=500, methods=BOM_INSTRUMENT_METHODS)
		self.set_type = make_set_type("THIST", set_type_name="History set", bom=[("SU-THIST", 1)]).name
		self.department = make_department()
		self.printer = make_printer(STATION, self.label_item, host="127.0.0.1")

	def unit(self, origin="New", cycles_used=0, max_cycles=300):
		return set_units._create_units(
			self.set_type, 1, self.department, max_cycles, origin=origin, cycles_used=cycles_used
		)[0]

	def print_tag(self, unit, reason=None, status="Printed"):
		job = set_tags.queue_prints([unit], ["tag"], {"tag": self.printer}, reason)["jobs"][0]["print_job"]
		if status:
			core_print.ack(job, status, "Printer", error=None if status == "Printed" else "x")
		return job


class TestSetUnitSummary(SetUnitLifecycleCase):
	def test_summary_cycles_and_active_cycle(self):
		unit = self.unit(origin="Existing", cycles_used=120)
		summary = set_units.summary(unit)
		self.assertEqual(summary["set_id"], unit)
		self.assertEqual(summary["set_type"], self.set_type)
		self.assertEqual(summary["set_type_name"], "History set")
		self.assertEqual(summary["department"], self.department)
		self.assertEqual(summary["status"], "New")
		self.assertEqual(
			(summary["cycles_used"], summary["max_cycles"], summary["remaining"]), (120, 300, 180)
		)
		self.assertEqual(summary["cycles_source"], "Estimated")
		self.assertIsNone(summary["active_cycle_id"])
		self.assertIsNone(summary["current_station"])
		# chưa ghim: phiên bản áp dụng = phiên bản hiệu lực hôm nay, "sẽ ghim khi tiếp nhận"
		self.assertFalse(summary["bom_pinned"])
		self.assertEqual(summary["cycle_bom_version"], 0)
		self.assertEqual(summary["bom_version_applied"], bom_versions.effective_version(self.set_type))
		self.assertEqual(summary["code_status"], "Active")
		self.assertIsNone(summary["tag_verified_on"])
		self.assertIsNone(summary["tag_verified_by"])
		self.assertEqual(summary["print_counts"], set_tags.print_counts(unit))

		# đã dùng vượt cơ số → còn lại 0, không âm
		step_gate._save_lifecycle(frappe.get_doc("Set Unit", unit), "test", cycles_used=350)
		self.assertEqual(set_units.summary(unit)["remaining"], 0)

		# tiếp nhận ghim BOM; đóng gói gắn Cycle ID hiệu lực
		step_gate.start_cycle(unit)
		step_gate.bind_cycle(unit, "CY-261019-0042", STATION)
		summary = set_units.summary(unit)
		self.assertTrue(summary["bom_pinned"])
		self.assertEqual(summary["cycle_bom_version"], 1)
		self.assertEqual(summary["bom_version_applied"], 1)
		self.assertEqual(summary["active_cycle_id"], "CY-261019-0042")
		self.assertEqual(summary["current_station"], STATION)
		self.assertEqual(summary["status"], "Processing")

		self.print_tag(unit)
		set_tags.verify(unit, unit)
		summary = set_units.summary(unit)
		self.assertEqual(summary["print_counts"]["tag"]["printed"], 1)
		self.assertEqual(summary["tag_verified_by"], "Administrator")
		self.assertTrue(summary["tag_verified_on"])

		new_unit = self.unit()
		self.assertEqual(set_units.summary(new_unit)["cycles_source"], "Actual")
		self.assertEqual(set_units.summary(new_unit)["remaining"], 300)
		for bad in ("9520000THIST999999", "", None, 5):
			self.assertEqual(_blocked(self, set_units.summary, bad).code, "SET_NOT_FOUND")


class TestSetUnitHistory(SetUnitLifecycleCase):
	def test_history_merges_lifecycle_gates_prints_packs(self):
		unit = self.unit()
		step_gate.start_cycle(unit)
		step_gate.record(unit, "T1", "Pass")
		step_gate.record(unit, "T2", "Fail")
		step_gate.record(unit, "T2", "Pass")
		step_gate.record(unit, "T3", "Pass")
		step_gate.record(unit, "T4", "Pass")
		first = self.print_tag(unit)
		again = self.print_tag(unit, reason="Tag lost in washer")
		cycle_id = next_free_test_cycle_id()
		pack = make_pack(unit, cycle_id=cycle_id)
		step_gate.bind_cycle(unit, pack.name, STATION)

		events = set_units.history(unit)["events"]
		self.assertIsNone(set_units.history(unit)["next_before"])
		times = [event["at"] for event in events]
		self.assertEqual(times, sorted(times, reverse=True))  # mới → cũ
		for event in events:
			self.assertEqual(
				set(event) >= {"at", "kind", "title", "detail", "user", "reason", "event", "ref"}, True
			)

		lifecycle = [e["event"] for e in events if e["kind"] == "audit"]
		self.assertEqual(
			lifecycle, ["bind_cycle", "gate T2 Pass", "gate T2 Fail", "start_cycle", step_gate.ISSUE_EVENT]
		)
		gates = [e for e in events if e["kind"] == "gate"]
		self.assertEqual([g["event"] for g in gates], ["T4 Pass", "T3 Pass", "T2 Pass", "T1 Pass"])
		self.assertIn("1", next(g for g in gates if g["event"] == "T2 Pass")["detail"])  # số lần làm lại
		prints = [e for e in events if e["kind"] == "print"]
		self.assertEqual([p["ref"] for p in prints], [again, first])
		self.assertEqual(prints[0]["reason"], "Tag lost in washer")
		self.assertEqual(prints[0]["event"], "tag reprint")
		self.assertEqual(prints[1]["event"], "tag print")
		self.assertIsNone(prints[1]["reason"])
		packs = [e for e in events if e["kind"] == "pack"]
		self.assertEqual([p["ref"] for p in packs], [cycle_id])
		self.assertIn(cycle_id, packs[0]["title"])

		kinds = [e["kind"] for e in events]
		order = [
			kinds.index("pack"),
			events.index(prints[0]),
			events.index(prints[1]),
			events.index(gates[0]),
			len(events) - 1,
		]
		self.assertEqual(order, sorted(order))
		self.assertEqual(events[0]["event"], "bind_cycle")
		self.assertIn(cycle_id, events[0]["detail"])
		self.assertEqual(events[-1]["event"], step_gate.ISSUE_EVENT)
		self.assertTrue(all(e["user"] == "Administrator" for e in events))

	def test_history_paging_and_constant_queries(self):
		unit = self.unit()
		step_gate.start_cycle(unit)
		for step in ("T1", "T2", "T3"):
			step_gate.record(unit, step, "Pass")
		self.print_tag(unit)
		self.print_tag(unit, reason="again", status="Failed")
		make_pack(unit, cycle_id=next_free_test_cycle_id())
		# 150 dòng Audit cùng một thời điểm: con trỏ phải phân định bằng (thời điểm, loại, tên), không chỉ thời điểm
		same = now_datetime()
		with patch("tracecore.core.audit.now_datetime", return_value=same):
			for index in range(150):
				audit.log("Update", "Set Unit", unit, new={"note": index}, reason="test")
		for index in range(150):
			audit.log("Update", "Set Unit", unit, new={"note": 1000 + index}, reason="test")

		expected = (
			frappe.db.count("Audit Log", {"ref_doctype": "Set Unit", "ref_name": unit})
			+ frappe.db.count("Step Gate Result", {"set_unit": unit})
			+ frappe.db.count("Print Job", {"ref_doctype": "Set Unit", "ref_name": unit})
			+ frappe.db.count("Pack", {"set_unit": unit})
		)
		self.assertGreaterEqual(expected, 300)

		seen, pages, before = [], 0, None
		while True:
			with patch.object(frappe.db, "sql", wraps=frappe.db.sql) as sql:
				page = set_units.history(unit, before=before, limit=50)
			self.assertLessEqual(sql.call_count, 5, msg=f"page {pages}")
			self.assertLessEqual(len(page["events"]), 50)
			seen.extend((e["kind"], str(e["ref"])) for e in page["events"])
			pages += 1
			before = page["next_before"]
			if not before:
				break
			self.assertEqual(len(page["events"]), 50)
		self.assertEqual(len(seen), expected)
		self.assertEqual(len(set(seen)), expected)  # không trùng, không sót
		self.assertEqual(pages, -(-expected // 50))
		full = set_units.history(unit, limit=200)
		self.assertEqual(len(full["events"]), 200)
		self.assertEqual([(e["kind"], str(e["ref"])) for e in full["events"]], seen[:200])

		# con trỏ chỉ là thời điểm: mọi sự kiện trước thời điểm đó
		older = set_units.history(unit, before=str(same), limit=200)["events"]
		self.assertTrue(older)
		self.assertTrue(all(e["at"] < same for e in older))

		for bad_limit in (0, 201, -1, "x", True, None):
			with self.assertRaises(frappe.ValidationError, msg=repr(bad_limit)):
				set_units.history(unit, limit=bad_limit)
		for bad_before in ("nope", "2026-10-19 09:00:00|zzz|1", 5):
			with self.assertRaises(frappe.ValidationError, msg=repr(bad_before)):
				set_units.history(unit, before=bad_before)
		self.assertEqual(_blocked(self, set_units.history, "9520000THIST999999").code, "SET_NOT_FOUND")


class TestSetUnitDispose(SetUnitLifecycleCase):
	@bru("BRU-ID-001")
	def test_dispose_from_new_disables_code_never_reissued(self):
		unit = self.unit()
		pending = self.print_tag(unit, status=None)  # job Queued từ trước khi thanh lý
		result = set_units.dispose(unit, "  Issued by mistake  ")
		self.assertEqual(result, {"set_unit": unit, "status": "Disposed"})
		self.assertEqual(frappe.db.get_value("Set Unit", unit, "status"), "Disposed")
		code = frappe.db.get_value("Code Registry", unit, ["status", "disabled_reason"], as_dict=True)
		self.assertEqual(code.status, "Disabled")
		self.assertEqual(code.disabled_reason, "Issued by mistake")
		log = frappe.get_all(
			"Audit Log",
			filters={"ref_doctype": "Set Unit", "ref_name": unit, "action": "Update"},
			fields=["reason", "new_value"],
			order_by="name desc",
			limit=1,
		)[0]
		self.assertEqual(log.reason, "dispose: Issued by mistake")
		self.assertEqual(frappe.parse_json(log.new_value), {"status": "Disposed"})
		history = set_units.history(unit)["events"]
		self.assertEqual(history[0]["event"], "dispose")
		self.assertEqual(history[0]["reason"], "Issued by mistake")
		self.assertEqual(set_units.summary(unit)["code_status"], "Disabled")

		# không bao giờ cấp lại: kéo bộ đếm series lùi về trước số đã thanh lý, mã kế tiếp vẫn khác
		prefix, serial = gs1.split_set_id(unit, "THIST")
		key = f"{prefix}THIST"
		frappe.db.sql("update `tabSeries` set `current` = %s where name = %s", (int(serial) - 1, key))
		self.assertNotEqual(code_registry.next_set_id("THIST"), unit)

		# vẫn tra được
		self.assertEqual(gs1.parse_scan(unit), {"type": "set", "id": unit, "raw": unit})
		self.assertEqual(gs1.parse_scan("(8004)" + unit)["id"], unit)

		# không in được, kể cả job đã xếp hàng trước khi thanh lý (kiểm lại lúc gửi)
		self.assertEqual(
			_blocked(self, set_tags.queue_prints, [unit], ["tray"], {"tray": self.printer}).code,
			"SET_DISPOSED",
		)
		# worker commit thật sẽ phá savepoint cách ly của test: giả commit
		with patch.object(print_server, "_send") as send, patch.object(frappe.db, "commit"):
			print_server.dispatch_job(pending)
		send.assert_not_called()
		job = frappe.db.get_value("Print Job", pending, ["status", "error"], as_dict=True)
		self.assertEqual(job.status, "Failed")
		self.assertIn(unit, job.error)

	def test_send_time_refuses_disposed_set_even_if_code_active(self):
		unit = self.unit()
		pending = self.print_tag(unit, status=None)
		step_gate.dispose(unit, "x")  # chỉ đổi trạng thái (vd nhánh T3 sau này), mã còn Active
		self.assertEqual(frappe.db.get_value("Code Registry", unit, "status"), "Active")
		# worker commit thật sẽ phá savepoint cách ly của test: giả commit
		with patch.object(print_server, "_send") as send, patch.object(frappe.db, "commit"):
			print_server.dispatch_job(pending)
		send.assert_not_called()
		self.assertEqual(frappe.db.get_value("Print Job", pending, "status"), "Failed")

	def test_dispose_state_rules(self):
		processing = self.unit()
		step_gate.start_cycle(processing)
		self.assertEqual(_blocked(self, set_units.dispose, processing, "x").code, "STATUS_INVALID_FOR_ACTION")
		sterile = self.unit()
		step_gate.start_cycle(sterile)
		for step in step_gate.STEPS:
			step_gate.record(sterile, step, "Pass")
		self.assertEqual(_blocked(self, set_units.dispose, sterile, "x").code, "STATUS_INVALID_FOR_ACTION")
		with_cycle = self.unit()
		step_gate.start_cycle(with_cycle)
		step_gate.bind_cycle(with_cycle, "CY-261019-0043", None)
		step_gate._save_lifecycle(frappe.get_doc("Set Unit", with_cycle), "end_of_life", status="End of Life")
		self.assertEqual(_blocked(self, set_units.dispose, with_cycle, "x").code, "STATUS_INVALID_FOR_ACTION")
		for unit in (processing, sterile, with_cycle):
			self.assertEqual(frappe.db.get_value("Code Registry", unit, "status"), "Active")

		end_of_life = self.unit()
		step_gate.start_cycle(end_of_life)
		step_gate._save_lifecycle(
			frappe.get_doc("Set Unit", end_of_life), "end_of_life", status="End of Life"
		)
		self.assertEqual(set_units.dispose(end_of_life, "Worn out")["status"], "Disposed")
		self.assertEqual(frappe.db.get_value("Code Registry", end_of_life, "status"), "Disabled")

		fresh = self.unit()
		for reason in ("", "   ", None, 5, "x" * 501):
			self.assertEqual(
				_blocked(self, set_units.dispose, fresh, reason).code, "REASON_REQUIRED", msg=repr(reason)
			)
		self.assertEqual(frappe.db.get_value("Set Unit", fresh, "status"), "New")
		self.assertEqual(set_units.dispose(fresh, "x" * 500)["status"], "Disposed")
		self.assertEqual(_blocked(self, set_units.dispose, fresh, "again").code, "STATUS_INVALID_FOR_ACTION")
		for missing in ("9520000THIST999999", "", None):
			self.assertEqual(_blocked(self, set_units.dispose, missing, "x").code, "SET_NOT_FOUND")

	def test_dispose_rolls_back_status_when_code_disable_fails(self):
		unit = self.unit()
		with patch.object(code_registry, "disable", side_effect=frappe.ValidationError("boom")):
			with self.assertRaises(frappe.ValidationError):
				set_units.dispose(unit, "x")
		self.assertEqual(frappe.db.get_value("Set Unit", unit, "status"), "New")

	def test_dispose_legacy_set_without_registry_row(self):
		unit = self.unit()
		frappe.db.delete("Code Registry", {"name": unit})  # bộ cũ chưa có dòng sổ
		self.assertEqual(set_units.dispose(unit, "x")["status"], "Disposed")
		self.assertIsNone(set_units.summary(unit)["code_status"])
