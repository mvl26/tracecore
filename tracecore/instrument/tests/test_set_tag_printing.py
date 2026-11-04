"""In thẻ kim loại / nhãn khay Set ID (FEAT-016 Task 4; FR-M1-05, .3, .4; EI-HW-008; A-09 G9-G12; A-114).

A-114: thẻ xếp ``Queued`` rồi in một PDF qua hộp thoại In (`set_tags.tags_pdf`). Các test `print_server` còn lại giữ
cho job cũ: máy in giả là socket TCP cục bộ trên 127.0.0.1, worker `print_server.dispatch_many` gọi đồng bộ;
`frappe.db.commit/rollback` giả bằng savepoint như `test_print_server.py`.
"""

import base64
import io
import socket
import threading
import time
from datetime import timedelta
from unittest.mock import patch

import frappe
from frappe.utils import now_datetime
from pypdf import PdfReader

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


class TestBatchPdf(SetTagPrintingCase):
	"""A-114: thẻ/nhãn khay xếp ``Queued`` rồi in một PDF nhiều trang qua hộp thoại In, không gửi ZPL qua mạng."""

	@bru("BRU-ID-001")
	def test_batch_queues_in_order_then_one_pdf_prints_every_label(self):
		units = self.units(3)
		frappe.db.set_single_value("TraceCore Settings", "label_printer", None)
		result = set_tags.queue_prints(units, ["tray", "tag"])
		expected = [(unit, kind) for unit in units for kind in ("tag", "tray")]
		self.assertEqual([(row["set_unit"], row["kind"]) for row in result["jobs"]], expected)
		self.assertEqual({row["status"] for row in result["jobs"]}, {"Queued"})
		self.enqueue.assert_not_called()  # không còn worker gửi ZPL
		jobs = self.jobs(result)
		for job, (unit, kind) in zip(jobs, expected, strict=True):
			row = frappe.get_doc("Print Job", job)
			self.assertEqual((row.ref_doctype, row.ref_name, row.printer), ("Set Unit", unit, None))
			self.assertEqual(
				frappe.parse_json(row.data),
				{"label_object": set_tags.KINDS[kind], "set_unit": unit, "kind": kind, "reprint": False},
			)
			audit = frappe.get_all(
				"Audit Log",
				filters={"ref_doctype": "Print Job", "ref_name": str(job), "action": "Create"},
				fields=["new_value"],
			)
			self.assertEqual(len(audit), 1)

		pdf = set_tags.tags_pdf(jobs)
		pages = PdfReader(io.BytesIO(base64.b64decode(pdf["pdf_b64"]))).pages
		self.assertEqual(len(pages), 6)
		decoded = [gs1.decode_datamatrix_png(page.images[0].data) for page in pages]
		self.assertEqual(decoded, [gs1.giai_payload(unit) for unit, _kind in expected])
		self.assertEqual((pdf["print_jobs"], pdf["skipped"]), ([str(job) for job in jobs], []))
		self.assertEqual(pdf["filename"], f"{units[0]}-6.pdf")
		self.assertEqual({self.state(job) for job in jobs}, {("Printed", 1)})
		self.assertEqual(frappe.db.get_value("Print Job", jobs[0], "output_mode"), "Browser")
		# đã in thì lấy lại không cần lý do không được: in lại phải qua queue_prints có lý do (FR-M1-05.3)
		self.assertEqual(self.block_code(set_tags.tags_pdf, jobs).code, "LABEL_NOT_QUEUED")

	@bru("BRU-ID-001")
	def test_pdf_failure_keeps_set_ids_and_jobs_queued(self):
		# FR-M1-05.4: không dựng được PDF thì Set ID còn nguyên, job giữ Queued để in lại
		units = self.units(2)
		registry_before = frappe.db.count("Code Registry")
		jobs = self.jobs(self.queue(units, ("tag",), self.printer()))
		with patch("frappe.utils.pdf.get_pdf", side_effect=OSError("No wkhtmltopdf executable found")):
			self.assertEqual(self.block_code(set_tags.tags_pdf, jobs).code, "LABEL_PDF_FAILED")
		self.assertEqual({self.state(job) for job in jobs}, {("Queued", 0)})
		self.assertEqual(frappe.db.count("Code Registry"), registry_before)
		self.assertEqual(len(set_tags.tags_pdf(jobs)["print_jobs"]), 2)

	def test_tags_pdf_skips_disabled_set_ids_and_other_jobs(self):
		units = self.units(2)
		jobs = self.jobs(self.queue(units))
		code_registry.disable(units[0], "Thanh lý")
		other = core_print.create_job(STATION, None, ref_doctype="Zone Station", ref_name=STATION)
		result = set_tags.tags_pdf([*jobs, other])
		self.assertEqual((result["print_jobs"], result["skipped"]), ([str(jobs[1])], [str(jobs[0]), str(other)]))
		self.assertEqual(self.state(jobs[0]), ("Queued", 0))

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

	def test_printer_without_network_address_is_fine(self):
		"""A-114: thẻ in ra PDF nên máy in không cần địa chỉ mạng (trước đây ``PRINTER_NOT_NETWORK``)."""
		units = self.units(1)
		result = set_tags.queue_prints(units, ["tag"], {"tag": self.printer(host="")})
		self.assertEqual(result["jobs"][0]["status"], "Queued")

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
			([unit], ["tag"], {"tag": inactive}),
			([unit], ["tag"], {"tag": "PRN-NONE"}),
			([unit], ["tag"], "PRN"),
		)
		for args in bad_calls:
			with self.assertRaises(frappe.ValidationError, msg=repr(args)) as raised:
				set_tags.queue_prints(*args)
			self.assertNotIsInstance(raised.exception, BlockedError, msg=repr(args))

	def test_broken_zpl_template_does_not_block_the_pdf_tag(self):
		# A-114: thẻ in ra PDF, mẫu ZPL chỉ còn là vết
		unit = self.units(1)[0]
		with patch.object(set_tags.core_print, "render_label", side_effect=frappe.ValidationError("bad")):
			job = self.jobs(set_tags.queue_prints([unit], ["tag"], {"tag": self.printer()}))[0]
		self.assertEqual(frappe.db.get_value("Print Job", job, ["status", "payload"]), ("Queued", None))
		self.assertEqual(set_tags.tags_pdf([job])["print_jobs"], [str(job)])


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
