"""In thẻ kim loại / nhãn khay Set ID qua hàng đợi server (FEAT-016 Task 4; FR-M1-05, .3, .4; EI-HW-008; A-09 G9-G12).

Máy in giả là socket TCP cục bộ trên 127.0.0.1 nhận nhiều kết nối (mỗi nhãn một kết nối), worker
`print_server.dispatch_many` gọi đồng bộ; `frappe.db.commit/rollback` giả bằng savepoint như `test_print_server.py`.
"""

import socket
import threading
import time
from datetime import timedelta
from unittest.mock import patch

import frappe
from frappe.utils import now_datetime

from tracecore.core import code_registry, gs1, print_server
from tracecore.core import print as core_print
from tracecore.core.errors import BlockedError
from tracecore.core.tests.test_code_registry import production_site
from tracecore.core.tests.test_print_server import FakeTransactions, closed_port
from tracecore.instrument import set_tags, set_units
from tracecore.tests.factories import (
	deactivate_printers,
	make_department,
	make_label_items,
	make_printer,
	make_set_type,
)
from tracecore.tests.utils import IsolatedTestCase, allow_local_printers, bru

# Set Unit → Department, Zone Station, Instrument Set Type (→ Item), User; Print Job → Printer → Item, User
test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

STATION = "TR-004"
REAL_PREFIX = "8931234"


class MultiFakePrinter:
	"""Máy in nhãn giả nhận nhiều kết nối TCP lần lượt (mỗi nhãn một kết nối), lưu byte của từng kết nối theo thứ tự."""

	def __init__(self):
		self.server = socket.create_server(("127.0.0.1", 0))
		self.server.settimeout(0.1)
		self.port = self.server.getsockname()[1]
		self.received = []
		self.stopping = threading.Event()
		self.thread = threading.Thread(target=self._serve, daemon=True)
		self.thread.start()

	def _serve(self):
		while True:
			try:
				conn, _addr = self.server.accept()
			except TimeoutError:
				if self.stopping.is_set():  # hàng chờ kết nối đã trống
					return
				continue
			except OSError:
				return
			with conn:
				conn.settimeout(2)
				chunks = []
				while chunk := conn.recv(4096):
					chunks.append(chunk)
				self.received.append(b"".join(chunks))

	def stop(self):
		"""Nhận nốt các kết nối đang chờ rồi đóng cổng (kết nối sau đó bị từ chối)."""
		self.stopping.set()
		self.thread.join(timeout=5)
		self.server.close()


class SetTagPrintingCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		deactivate_printers(STATION)
		self.label_item = make_label_items()[0]
		self.tx = FakeTransactions(self)
		allow_local_printers(self)
		enqueue = patch.object(frappe, "enqueue")
		self.enqueue = enqueue.start()
		self.addCleanup(enqueue.stop)
		self.set_type = make_set_type("TPRN").name
		self.department = make_department()

	def units(self, count):
		return set_units._create_units(self.set_type, count, self.department, 300)

	def printer(self, port=9100, host="127.0.0.1"):
		name = make_printer(STATION, self.label_item, host=host)
		frappe.db.set_value("Printer", name, "port", port)
		return name

	def fake(self):
		fake = MultiFakePrinter()
		self.addCleanup(fake.stop)
		return fake

	def queue(self, units, kinds=("tag",), printer=None, reason=None):
		printer = printer or self.printer()
		result = set_tags.queue_prints(list(units), list(kinds), dict.fromkeys(kinds, printer), reason)
		self.tx.commit()  # request đã commit trước khi worker chạy
		return result

	def jobs(self, result):
		return [row["print_job"] for row in result["jobs"]]

	def payloads(self, jobs):
		return [frappe.db.get_value("Print Job", job, "payload").encode("utf-8") for job in jobs]

	def state(self, job):
		row = frappe.db.get_value("Print Job", job, ["status", "attempts"], as_dict=True)
		return row.status, row.attempts

	def age(self, jobs):
		for job in jobs:
			frappe.db.set_value(
				"Print Job", job, "modified", now_datetime() - timedelta(minutes=2), update_modified=False
			)
		self.tx.commit()

	def block_code(self, call, *args, **kwargs):
		with self.assertRaises(BlockedError) as raised:
			call(*args, **kwargs)
		return raised.exception.block

	def mark(self, job, status):
		core_print.ack(job, status, "File", output_ref="test.zpl", error=None if status == "Printed" else "x")


class TestBatchDispatch(SetTagPrintingCase):
	@bru("BRU-ID-001")
	def test_batch_print_reaches_fake_printer_in_order(self):
		fake = self.fake()
		units = self.units(3)
		tag_printer, tray_printer = self.printer(fake.port), self.printer(fake.port)

		result = set_tags.queue_prints(units, ["tray", "tag"], {"tag": tag_printer, "tray": tray_printer})
		self.tx.commit()

		expected = [(unit, kind) for unit in units for kind in ("tag", "tray")]
		self.assertEqual([(row["set_unit"], row["kind"]) for row in result["jobs"]], expected)
		self.assertEqual({row["status"] for row in result["jobs"]}, {"Queued"})
		self.assertEqual(result["warnings"], [])
		jobs = self.jobs(result)
		self.enqueue.assert_called_once()
		args, kwargs = self.enqueue.call_args
		self.assertEqual(args, ("tracecore.core.print_server.dispatch_many",))
		self.assertEqual(kwargs["jobs"], jobs)
		for job, (unit, kind) in zip(jobs, expected, strict=True):
			row = frappe.get_doc("Print Job", job)
			self.assertEqual((row.ref_doctype, row.ref_name, row.station), ("Set Unit", unit, STATION))
			self.assertEqual(row.printer, tag_printer if kind == "tag" else tray_printer)
			data = frappe.parse_json(row.data)
			self.assertEqual(
				data,
				{
					"label_object": set_tags.KINDS[kind],
					"set_unit": unit,
					"kind": kind,
					"reprint": False,
					"dispatch": "server",
				},
			)
			self.assertIn(f"^FD_18004{unit}^FS", row.payload)
			self.assertEqual(row.template, core_print.active_template(set_tags.KINDS[kind], None).name)
			audit = frappe.get_all(
				"Audit Log",
				filters={"ref_doctype": "Print Job", "ref_name": str(job), "action": "Create"},
				fields=["new_value", "reason"],
			)
			self.assertEqual(len(audit), 1)
			self.assertEqual(
				frappe.parse_json(audit[0].new_value),
				{"set_unit": unit, "kind": kind, "reprint": False, "printer": row.printer},
			)
			self.assertIsNone(audit[0].reason)

		results = print_server.dispatch_many(jobs)
		fake.stop()

		self.assertEqual(results, [{"status": "Printed", "attempts": 1}] * 6)
		self.assertEqual(fake.received, self.payloads(jobs))

	@bru("BRU-ID-001")
	def test_printer_down_keeps_set_ids_and_queues(self):
		units = self.units(3)
		registry_before = frappe.db.count("Code Registry")
		result = self.queue(units, ("tag", "tray"), self.printer(closed_port()))
		jobs = self.jobs(result)

		results = print_server.dispatch_many(jobs)

		self.assertEqual(results[0], {"status": "Queued", "attempts": 1})
		self.assertEqual(results[1:], [{"status": "Queued", "attempts": 0}] * 5)
		self.assertTrue(frappe.db.get_value("Print Job", jobs[0], "error"))
		for _round in range(2):  # lượt 2, 3 của worker: job đầu hết lần thử
			print_server.dispatch_many(jobs)
		self.assertEqual(self.state(jobs[0]), ("Failed", 3))
		self.assertEqual([self.state(job) for job in jobs[1:]], [("Queued", 0)] * 5)
		for _round in range(3):  # cron thử lại mọi job còn Queued
			self.age(jobs)
			print_server.dispatch_pending(limit=20)
		self.assertEqual({self.state(job) for job in jobs}, {("Failed", 3)})
		# FR-M1-05.4: Set ID đã cấp còn nguyên, không cấp mã mới
		self.assertEqual(len(frappe.get_all("Set Unit", filters={"name": ["in", units]}, pluck="name")), 3)
		self.assertEqual(frappe.db.count("Code Registry"), registry_before)
		self.assertEqual({frappe.db.get_value("Code Registry", unit, "status") for unit in units}, {"Active"})

	@bru("BRU-ID-001")
	def test_partial_failure_resumes_without_duplicates(self):
		fake = MultiFakePrinter()
		printer = self.printer(fake.port)
		jobs = self.jobs(self.queue(self.units(100), printer=printer))
		real_send = print_server._send
		calls = []

		def flaky(host, port, payload):
			calls.append(payload)
			if len(calls) == 38:  # máy in nhận 37 nhãn rồi tắt
				fake.stop()
			real_send(host, port, payload)

		with patch.object(print_server, "_send", side_effect=flaky):
			print_server.dispatch_many(jobs)

		self.assertEqual(len(calls), 38)
		self.assertEqual(fake.received, self.payloads(jobs[:37]))
		self.assertEqual({self.state(job) for job in jobs[:37]}, {("Printed", 1)})
		self.assertEqual(self.state(jobs[37]), ("Queued", 1))
		self.assertEqual({self.state(job) for job in jobs[38:]}, {("Queued", 0)})
		self.assertEqual(len(jobs[38:]), 62)

		again = self.fake()  # máy in bật lại
		frappe.db.set_value("Printer", printer, "port", again.port)
		self.age(jobs)
		self.assertEqual(print_server.dispatch_pending(limit=100), 63)
		again.stop()

		self.assertEqual(again.received, self.payloads(jobs[37:]))
		self.assertFalse(set(again.received) & set(fake.received))
		self.assertEqual({self.state(job)[0] for job in jobs}, {"Printed"})

	def test_batch_worker_bounded_time(self):
		jobs = self.jobs(self.queue(self.units(100), printer=self.printer()))

		def unresponsive(address, timeout):
			time.sleep(timeout)
			raise TimeoutError("timed out")

		with (
			patch.object(print_server, "SEND_TIMEOUT_S", 0.2),
			patch.object(print_server.socket, "create_connection", side_effect=unresponsive) as connect,
		):
			started = time.monotonic()
			results = print_server.dispatch_many(jobs)
			elapsed = time.monotonic() - started

		connect.assert_called_once()
		self.assertLess(elapsed, 0.2 * 3)
		self.assertEqual(results[0], {"status": "Queued", "attempts": 1})
		self.assertEqual(len(results), 100)
		self.assertEqual({self.state(job) for job in jobs[1:]}, {("Queued", 0)})

	def test_batch_stops_only_the_printer_that_failed(self):
		fake = self.fake()
		units = self.units(2)
		down, up = self.printer(closed_port()), self.printer(fake.port)
		result = set_tags.queue_prints(units, ["tag", "tray"], {"tag": down, "tray": up})
		self.tx.commit()
		jobs = self.jobs(result)

		results = print_server.dispatch_many(jobs)
		fake.stop()

		# thẻ (máy in hỏng): lần thử đầu tính 1, thẻ sau giữ nguyên; nhãn khay (máy in khác) vẫn in
		self.assertEqual(
			results,
			[
				{"status": "Queued", "attempts": 1},
				{"status": "Printed", "attempts": 1},
				{"status": "Queued", "attempts": 0},
				{"status": "Printed", "attempts": 1},
			],
		)
		self.assertEqual(fake.received, self.payloads([jobs[1], jobs[3]]))

	def test_printer_without_network_address_refused(self):
		"""Ruling Task 4/5: thẻ/nhãn khay chỉ in qua đường server; máy in chỉ qua agent (host rỗng) hoặc host bị chặn
		→ ``PRINTER_NOT_NETWORK`` trước mọi ghi, không tạo job ``Waiting`` (không ai giải phóng → chặn bộ mãi mãi)."""
		units = self.units(2)
		agent = self.printer(host="")
		network = self.printer()
		jobs_before = frappe.db.count("Print Job")

		block = self.block_code(
			set_tags.queue_prints, units, ["tag", "tray"], {"tag": network, "tray": agent}
		)

		self.assertEqual(block.code, "PRINTER_NOT_NETWORK")
		self.assertEqual(block.http_status, 422)
		self.assertEqual(block.items, [agent])
		self.assertIn(agent, block.reason)
		self.assertEqual(frappe.db.count("Print Job"), jobs_before)
		self.enqueue.assert_not_called()
		frappe.conf.pop("tracecore_allow_local_printers")  # 127.0.0.1 bị chặn khi site không bật cờ
		block = self.block_code(set_tags.queue_prints, units, ["tag"], {"tag": network})
		self.assertEqual(block.code, "PRINTER_NOT_NETWORK")

	def test_dispatch_refuses_demo_prefix_set_label_on_real_site(self):
		"""DB dev (Set ID tiền tố demo, job Queued) chép sang site thật: worker không gửi, job Failed có lý do."""
		unit = self.units(1)[0]
		jobs = self.jobs(self.queue([unit], ("tag", "tray")))
		conf, flags = production_site(tc_gs1_company_prefix=REAL_PREFIX)
		with conf, flags, patch.object(print_server.socket, "create_connection") as connect:
			results = print_server.dispatch_many(jobs)
		connect.assert_not_called()
		self.assertEqual([r["status"] for r in results], ["Failed", "Failed"])
		error = frappe.db.get_value("Print Job", jobs[0], "error")
		self.assertIn(unit, error)
		self.assertIn(gs1.split_set_id(unit, "TPRN")[0], error)  # tiền tố demo chứa trong Set ID

	def test_dispatch_refuses_disabled_set_id(self):
		unit = self.units(1)[0]
		job = self.jobs(self.queue([unit]))[0]
		code_registry.disable(unit, "Thanh lý")
		self.tx.commit()
		with patch.object(print_server.socket, "create_connection") as connect:
			self.assertEqual(print_server.dispatch_job(job)["status"], "Failed")
		connect.assert_not_called()
		self.assertIn(unit, frappe.db.get_value("Print Job", job, "error"))


class TestReprint(SetTagPrintingCase):
	@bru("BRU-ID-001")
	def test_first_print_and_fill_in_without_reason(self):
		unit = self.units(1)[0]
		self.assertFalse(set_tags.needs_reason(unit, "tag"))
		first = self.queue([unit])["jobs"][0]["print_job"]
		row = frappe.get_doc("Print Job", first)
		self.assertIsNone(row.reprint_reason)
		self.assertFalse(frappe.parse_json(row.data)["reprint"])
		self.mark(first, "Failed")
		self.assertFalse(set_tags.needs_reason(unit, "tag"))  # chỉ có job Failed → in bù
		fill = self.queue([unit])["jobs"][0]["print_job"]
		self.assertFalse(frappe.parse_json(frappe.db.get_value("Print Job", fill, "data"))["reprint"])
		self.mark(fill, "Printed")
		self.assertTrue(set_tags.needs_reason(unit, "tag"))
		self.assertFalse(set_tags.needs_reason(unit, "tray"))  # loại bản in khác chưa in lần nào

	@bru("BRU-ID-001")
	def test_reprint_requires_reason_and_counts(self):
		unit = self.units(1)[0]
		printer = self.printer()
		original = self.queue([unit], printer=printer)["jobs"][0]["print_job"]
		self.mark(original, "Failed")
		fill = self.queue([unit], printer=printer)["jobs"][0]["print_job"]
		self.mark(fill, "Printed")

		jobs_before = frappe.db.count("Print Job", {"ref_doctype": "Set Unit", "ref_name": unit})
		for reason in (None, "", "   ", "x" * 501, 42):
			block = self.block_code(set_tags.queue_prints, [unit], ["tag"], {"tag": printer}, reason)
			self.assertEqual(block.code, "REASON_REQUIRED", msg=repr(reason))
			self.assertEqual(block.items, [{"set_unit": unit, "kind": "tag"}])
		self.assertEqual(
			frappe.db.count("Print Job", {"ref_doctype": "Set Unit", "ref_name": unit}), jobs_before
		)

		warnings = []
		for reason in ("  Thẻ rơi khi hấp ", "x" * 500, "Thẻ lỗi - không đọc được"):
			result = self.queue([unit], printer=printer, reason=reason)
			job = result["jobs"][0]["print_job"]
			warnings.append([w["code"] for w in result["warnings"]])
			row = frappe.get_doc("Print Job", job)
			self.assertEqual(row.reprint_reason, reason.strip())
			self.assertTrue(frappe.parse_json(row.data)["reprint"])
			audit = frappe.get_all(
				"Audit Log",
				filters={"ref_doctype": "Print Job", "ref_name": str(job), "action": "Create"},
				fields=["new_value", "reason"],
			)
			self.assertEqual(audit[0].reason, reason.strip())
			self.assertTrue(frappe.parse_json(audit[0].new_value)["reprint"])
			self.mark(job, "Printed")
		self.assertEqual(warnings, [[], [], ["TAG_REPRINTED"]])
		self.assertIn("3", result["warnings"][0]["reason"])

		with self.assertQueryCount(1):
			counts = set_tags.print_counts(unit)
		self.assertEqual(set(counts), {"tag", "tray"})
		tag = counts["tag"]
		self.assertTrue(tag.pop("last_printed_at"))
		self.assertEqual(tag, {"requested": 5, "printed": 4, "failed": 1, "reprints": 3, "pending": 0})
		self.assertEqual(
			counts["tray"],
			{
				"requested": 0,
				"printed": 0,
				"failed": 0,
				"reprints": 0,
				"pending": 0,
				"last_printed_at": None,
			},
		)

	def test_mixed_batch_reason_items_only_printed_units(self):
		first, second = self.units(2)
		printer = self.printer()
		job = self.queue([first], ("tag", "tray"), printer)["jobs"]
		self.mark(job[0]["print_job"], "Printed")
		self.mark(job[1]["print_job"], "Printed")
		block = self.block_code(
			set_tags.queue_prints, [first, second], ["tag", "tray"], {"tag": printer, "tray": printer}
		)
		self.assertEqual(
			block.items, [{"set_unit": first, "kind": "tag"}, {"set_unit": first, "kind": "tray"}]
		)
		result = self.queue([first, second], ("tag", "tray"), printer, reason="Thẻ mờ")
		reprints = [
			frappe.db.get_value("Print Job", row["print_job"], "reprint_reason") for row in result["jobs"]
		]
		self.assertEqual(reprints, ["Thẻ mờ", "Thẻ mờ", None, None])

	def test_pending_job_blocks_second_print(self):
		unit = self.units(1)[0]
		printer = self.printer()
		self.queue([unit], printer=printer)
		self.assertEqual(set_tags.pending_block(unit, "tag").code, "TAG_PRINT_PENDING")
		self.assertIsNone(set_tags.pending_block(unit, "tray"))
		block = self.block_code(set_tags.queue_prints, [unit], ["tag"], {"tag": printer}, reason="Thẻ rơi")
		self.assertEqual(block.code, "TAG_PRINT_PENDING")
		self.assertEqual(block.items, [{"set_unit": unit, "kind": "tag"}])
		# Waiting (job cũ của máy in agent, trước ruling PRINTER_NOT_NETWORK) cũng là đang chờ
		core_print.create_job(
			STATION,
			None,
			{"label_object": "Set Tray Label", "set_unit": unit, "kind": "tray", "reprint": False},
			core_print.active_template("Set Tray Label", None).name,
			printer=printer,
			status="Waiting",
			ref_doctype="Set Unit",
			ref_name=unit,
		)
		self.assertEqual(set_tags.pending_block(unit, "tray").code, "TAG_PRINT_PENDING")

	@bru("BRU-ID-001")
	def test_disposed_or_disabled_not_printable(self):
		disposed, end_of_life, disabled = self.units(3)
		frappe.db.set_value("Set Unit", disposed, "status", "Disposed")
		frappe.db.set_value("Set Unit", end_of_life, "status", "End of Life")
		code_registry.disable(disabled, "Thanh lý")
		self.assertEqual(set_tags.check_printable(disposed).code, "SET_DISPOSED")
		self.assertEqual(set_tags.check_printable(disabled).code, "CODE_DISABLED")
		self.assertIsNone(set_tags.check_printable(end_of_life))
		for missing in ("9520000TPRN999999", None, 12, ["x"]):
			self.assertEqual(set_tags.check_printable(missing).code, "SET_NOT_FOUND", msg=repr(missing))
		printer = self.printer()
		jobs_before = frappe.db.count("Print Job")
		for unit, code in ((disposed, "SET_DISPOSED"), (disabled, "CODE_DISABLED")):
			block = self.block_code(set_tags.queue_prints, [end_of_life, unit], ["tag"], {"tag": printer})
			self.assertEqual(block.code, code)
		self.assertEqual(frappe.db.count("Print Job"), jobs_before)  # kiểm cả lô trước mọi ghi
		self.assertEqual(self.queue([end_of_life], printer=printer)["jobs"][0]["status"], "Queued")

	def test_demo_prefix_set_id_not_printable_outside_dev_test(self):
		unit = self.units(1)[0]
		printer = self.printer()
		jobs_before = frappe.db.count("Print Job")
		conf, flags = production_site(tc_gs1_company_prefix=REAL_PREFIX)
		with conf, flags:
			self.assertEqual(set_tags.check_printable(unit).code, "GS1_PREFIX_NOT_CONFIGURED")
			block = self.block_code(set_tags.queue_prints, [unit], ["tag"], {"tag": printer})
		self.assertEqual(block.code, "GS1_PREFIX_NOT_CONFIGURED")
		self.assertEqual(frappe.db.count("Print Job"), jobs_before)

	def test_queue_prints_bad_parameters(self):
		unit = self.units(1)[0]
		printer = self.printer()
		inactive = self.printer()
		frappe.db.set_value("Printer", inactive, "is_active", 0)
		bad_calls = (
			("not-a-list", ["tag"], {"tag": printer}),
			([], ["tag"], {"tag": printer}),
			([f"9520000TPRN{i:06d}" for i in range(101)], ["tag"], {"tag": printer}),
			([unit], ["label"], {"label": printer}),
			([unit], [], {}),
			([unit], ["tag"], {}),
			([unit], ["tag"], {"tag": inactive}),
			([unit], ["tag"], {"tag": "PRN-NONE"}),
			([unit], ["tag"], "PRN"),
		)
		for args in bad_calls:
			with self.assertRaises(frappe.ValidationError, msg=repr(args)) as raised:
				set_tags.queue_prints(*args)
			self.assertNotIsInstance(raised.exception, BlockedError, msg=repr(args))

	def test_broken_template_reports_render_failed_before_writes(self):
		unit = self.units(1)[0]
		printer = self.printer()
		jobs_before = frappe.db.count("Print Job")
		with patch.object(set_tags.core_print, "render_label", side_effect=frappe.ValidationError("bad")):
			block = self.block_code(set_tags.queue_prints, [unit], ["tag"], {"tag": printer})
		self.assertEqual(block.code, "LABEL_RENDER_FAILED")
		self.assertEqual(frappe.db.count("Print Job"), jobs_before)


class TestVerifyTag(SetTagPrintingCase):
	@bru("BRU-ID-006")
	def test_verify_tag_match_mismatch_unknown(self):
		unit, other = self.units(2)

		result = set_tags.verify(unit, f"]d2\x1d{gs1.giai_payload(unit)[1:]}\r\n")

		doc = frappe.get_doc("Set Unit", unit)
		self.assertEqual(result, {"set_unit": unit, "verified_on": doc.tag_verified_on})
		self.assertTrue(doc.tag_verified_on)
		self.assertEqual(doc.tag_verified_by, frappe.session.user)
		audit = frappe.get_all(
			"Audit Log",
			filters={"ref_doctype": "Set Unit", "ref_name": unit, "action": "Update"},
			fields=["new_value", "reason"],
			order_by="creation desc",
			limit=1,
		)
		self.assertEqual(frappe.parse_json(audit[0].new_value)["tag_verified_by"], frappe.session.user)
		self.assertEqual(audit[0].reason, "verify_tag")

		block = self.block_code(set_tags.verify, unit, gs1.giai_hri(other))
		self.assertEqual(block.code, "TAG_MISMATCH")
		self.assertEqual(block.items, [{"expected": unit, "scanned": other}])
		self.assertIn(unit, block.reason)
		self.assertIn(other, block.reason)

		for raw in ("XYZ", "", None, 42, f"{code_registry.company_prefix()}I-00000001", "TB-0001"):
			self.assertEqual(self.block_code(set_tags.verify, unit, raw).code, "SCAN_INVALID", msg=repr(raw))
		self.assertEqual(self.block_code(set_tags.verify, "9520000TPRN999999", unit).code, "SET_NOT_FOUND")
		self.assertEqual(self.block_code(set_tags.verify, None, unit).code, "SET_NOT_FOUND")


class TestPrintJobIndex(IsolatedTestCase):
	def test_print_job_ref_index_exists(self):
		rows = frappe.db.sql("show index from `tabPrint Job`", as_dict=True)
		indexes = {}
		for row in rows:
			indexes.setdefault(row.Key_name, []).append((row.Seq_in_index, row.Column_name))
		columns = [[column for _seq, column in sorted(cols)] for cols in indexes.values()]
		self.assertIn(["ref_doctype", "ref_name"], columns)
