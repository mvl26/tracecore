"""Đường in từ server (A-05 R1, ADR-006 dự phòng): Print Job `Queued` → TCP tới `Printer.host:Printer.port`.

Máy in giả là một socket server cục bộ trên 127.0.0.1 (không cần máy in thật); cổng đóng = máy in từ chối kết nối.
"""

import json
import socket
import threading
import time
from datetime import timedelta
from unittest.mock import call, patch

import frappe
from frappe.utils import now_datetime

from tracecore import hooks
from tracecore.core import print as core_print
from tracecore.core import print_server
from tracecore.tests.factories import deactivate_printers, make_label_items, make_printer
from tracecore.tests.utils import IsolatedTestCase, allow_local_printers

STATION = "TR-004"
ZPL = "^XA^FO30,40^BQN,2,6^FDMA,TB-0001^FS^XZ"
COMMITTED = "tc_print_committed"


class FakePrinter:
	"""Máy in nhãn giả: nhận một kết nối TCP trên 127.0.0.1, đọc tới khi bên gửi đóng, lưu toàn bộ byte."""

	def __init__(self):
		self.server = socket.create_server(("127.0.0.1", 0))
		self.server.settimeout(2)
		self.port = self.server.getsockname()[1]
		self.received = []
		self.stopping = False
		self.thread = threading.Thread(target=self._serve, daemon=True)
		self.thread.start()

	def _serve(self):
		try:
			conn, _addr = self.server.accept()
		except OSError:
			return
		with conn:
			if self.stopping:
				return
			conn.settimeout(2)
			chunks = []
			while chunk := conn.recv(4096):
				chunks.append(chunk)
			self.received.append(b"".join(chunks))

	def close(self):
		if self.thread.is_alive():  # chưa ai kết nối: tự kết nối để accept() trả về ngay thay vì chờ timeout
			self.stopping = True
			with socket.create_connection(("127.0.0.1", self.port), timeout=1):
				pass
		self.server.close()
		self.thread.join(timeout=3)


class FakeTransactions:
	"""Giả `frappe.db.commit/rollback` bằng savepoint để test không commit thật (giữ cách ly IsolatedTestCase).

	`commit()` dời savepoint `COMMITTED` tới hiện tại; `rollback()` không tham số quay về commit gần nhất;
	`crash()` mô phỏng worker chết/transaction bị hủy sau đó: mọi thứ chưa commit mất, cái đã commit còn.
	"""

	def __init__(self, case):
		self.real_rollback = frappe.db.rollback
		frappe.db.savepoint(COMMITTED)
		for name, fake in (("commit", self.commit), ("rollback", self.rollback)):
			patcher = patch.object(frappe.db, name, side_effect=fake)
			patcher.start()
			case.addCleanup(patcher.stop)

	def commit(self):
		frappe.db.savepoint(COMMITTED)

	def rollback(self, *, save_point=None):
		self.real_rollback(save_point=save_point or COMMITTED)

	def crash(self):
		self.real_rollback(save_point=COMMITTED)


def closed_port():
	"""Một cổng TCP cục bộ không có ai nghe (kết nối bị từ chối ngay)."""
	with socket.create_server(("127.0.0.1", 0)) as probe:
		return probe.getsockname()[1]


class TestServerDispatch(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		deactivate_printers(STATION)
		self.label_item = make_label_items()[0]
		self.tx = FakeTransactions(self)
		allow_local_printers(self)  # máy in giả nghe trên 127.0.0.1

	def printer(self, host="127.0.0.1", port=9100, is_active=1):
		name = make_printer(STATION, self.label_item, host=host)
		frappe.db.set_value("Printer", name, {"port": port, "is_active": is_active})
		return name

	def job(self, printer, data=None, zpl=ZPL):
		job = core_print.create_job(STATION, zpl, data, "object-label", printer=printer)
		self.tx.commit()  # dữ liệu chuẩn bị coi như đã commit trước khi worker chạy
		return job

	def fake_printer(self):
		fake = FakePrinter()
		self.addCleanup(fake.close)
		return fake

	def test_dispatch_sends_payload_to_printer_host(self):
		fake = self.fake_printer()
		job = self.job(self.printer(port=fake.port))

		result = print_server.dispatch_job(job)

		fake.thread.join(timeout=3)
		self.assertEqual(fake.received, [ZPL.encode("utf-8")])
		self.assertEqual(result, {"status": "Printed", "attempts": 1})
		doc = frappe.get_doc("Print Job", job)
		self.assertEqual(
			(doc.status, doc.output_mode, doc.output_ref, doc.attempts, bool(doc.printed_at), doc.error),
			("Printed", "Printer", f"127.0.0.1:{fake.port}", 1, True, None),
		)

	def test_dispatch_sends_unicode_payload_as_utf8(self):
		fake = self.fake_printer()
		zpl = "^XA^CI28^FO1,1^FDMáy hấp^FS^XZ"
		job = self.job(self.printer(port=fake.port), zpl=zpl)

		print_server.dispatch_job(job)

		fake.thread.join(timeout=3)
		self.assertEqual(fake.received, [zpl.encode("utf-8")])

	def test_dispatch_unreachable_printer_retries_then_fails(self):
		port = closed_port()
		job = self.job(self.printer(port=port))

		for attempt in (1, 2):
			started = time.monotonic()
			result = print_server.dispatch_job(job)
			self.assertLess(time.monotonic() - started, print_server.SEND_TIMEOUT_S)
			self.assertEqual(result, {"status": "Queued", "attempts": attempt})
			doc = frappe.get_doc("Print Job", job)
			self.assertEqual((doc.status, doc.attempts), ("Queued", attempt))
			self.assertIn(f"127.0.0.1:{port}", doc.error)

		result = print_server.dispatch_job(job)
		self.assertEqual(result, {"status": "Failed", "attempts": 3})
		doc = frappe.get_doc("Print Job", job)
		self.assertEqual((doc.status, doc.output_mode, doc.attempts), ("Failed", "Printer", 3))
		self.assertIn(f"127.0.0.1:{port}", doc.error)
		self.assertFalse(doc.printed_at)

		# job Failed không bị gửi lại
		self.assertEqual(print_server.dispatch_job(job), {"status": "Failed", "attempts": 3})

	def test_dispatch_connects_with_bounded_timeout(self):
		job = self.job(self.printer(host="printer.local", port=9100))
		with patch.object(
			print_server.socket, "create_connection", side_effect=TimeoutError("timed out")
		) as connect:
			result = print_server.dispatch_job(job)
		connect.assert_called_once()
		args, kwargs = connect.call_args
		self.assertEqual(args, (("printer.local", 9100),))
		# kết nối luôn có timeout hữu hạn: không có timeout (None) thì worker treo khi máy in im lặng
		self.assertIsInstance(kwargs.get("timeout"), int | float)
		self.assertTrue(0 < kwargs["timeout"] <= 10, kwargs["timeout"])
		self.assertEqual(result, {"status": "Queued", "attempts": 1})
		self.assertIn("timed out", frappe.db.get_value("Print Job", job, "error"))

	def test_dispatch_locks_job_row_while_sending(self):
		job = self.job(self.printer(port=closed_port()))
		with patch.object(print_server.frappe, "get_doc", wraps=frappe.get_doc) as get_doc:
			print_server.dispatch_job(job)
		self.assertEqual(get_doc.call_args_list[0], call("Print Job", job, for_update=True))

	def test_dispatch_commits_printed_result_right_after_sending(self):
		fake = self.fake_printer()
		job = self.job(self.printer(port=fake.port))

		print_server.dispatch_job(job)
		self.tx.crash()  # lỗi/rollback sau đó không được đưa job về Queued (nhãn đã ra giấy)

		doc = frappe.get_doc("Print Job", job)
		self.assertEqual((doc.status, doc.attempts), ("Printed", 1))

	def test_dispatch_commits_failed_attempt(self):
		job = self.job(self.printer(port=closed_port()))

		print_server.dispatch_job(job)
		self.tx.crash()

		self.assertEqual(frappe.db.get_value("Print Job", job, ["status", "attempts"]), ("Queued", 1))

	def test_dispatch_keeps_printed_when_ack_save_fails_after_sending(self):
		fake = self.fake_printer()
		job = self.job(self.printer(port=fake.port))

		with (
			patch.object(print_server.core_print, "ack", side_effect=RuntimeError("save failed")),
			patch.object(print_server.frappe, "log_error") as log_error,
		):
			result = print_server.dispatch_job(job)
		self.tx.crash()

		fake.thread.join(timeout=3)
		self.assertEqual(fake.received, [ZPL.encode("utf-8")])
		self.assertEqual(result, {"status": "Printed", "attempts": 1})
		log_error.assert_called_once()
		doc = frappe.get_doc("Print Job", job)
		self.assertEqual(
			(doc.status, doc.output_mode, doc.output_ref, doc.attempts, bool(doc.printed_at), doc.error),
			("Printed", "Printer", f"127.0.0.1:{fake.port}", 1, True, None),
		)
		# đã in rồi thì không bao giờ gửi lại
		with patch.object(print_server.socket, "create_connection") as connect:
			print_server.dispatch_job(job)
		connect.assert_not_called()

	def test_dispatch_ignores_agent_only_printer(self):
		for host in ("", "   "):
			job = self.job(self.printer(host=host))
			with patch.object(print_server.socket, "create_connection") as connect:
				result = print_server.dispatch_job(job)
			connect.assert_not_called()
			self.assertEqual(result, {"status": "Queued", "attempts": 0})
			doc = frappe.get_doc("Print Job", job)
			self.assertEqual((doc.status, doc.attempts, doc.error), ("Queued", 0, None))

	def test_local_ip_printer_needs_site_flag(self):
		# máy in có host IP loopback/link-local (máy in của agent, lưu được): không cờ site thì server không gửi tới
		printer = self.printer(host="10.0.0.5")
		hosts = ("127.0.0.1", "127.1", "::1", "169.254.169.254", "0.0.0.0", "127.0.0.1.", "169.254.169.254.")
		for host in hosts:
			frappe.db.set_value("Printer", printer, "host", host)
			frappe.conf.pop("tracecore_allow_local_printers", None)
			self.assertTrue(print_server.blocked_host(host), host)
			self.assertIsNone(print_server.printer_address(printer), host)
			frappe.conf["tracecore_allow_local_printers"] = 1
			self.assertEqual(print_server.printer_address(printer), (host, 9100), host)
		frappe.db.set_value("Printer", printer, "host", "printer.local")
		frappe.conf.pop("tracecore_allow_local_printers", None)
		self.assertEqual(print_server.printer_address(printer), ("printer.local", 9100))

	def test_ip_literal_ignores_trailing_dot(self):
		for host, expected in (
			("127.0.0.1.", "127.0.0.1"),
			("169.254.169.254.", "169.254.169.254"),
			(" 10.0.0.5. ", "10.0.0.5"),
		):
			self.assertEqual(str(print_server._ip_literal(host)), expected, host)
		self.assertIsNone(print_server._ip_literal("printer.local."))

	def test_dispatch_blocked_or_invalid_host_fails_job_with_reason(self):
		printer = self.printer(host="10.0.0.5")
		for host in ("127.0.0.1", "169.254.169.254.", "10.0.0.5 extra"):
			job = self.job(printer)
			frappe.db.set_value("Printer", printer, "host", host)  # máy in bị chặn sau khi job đã Queued
			frappe.conf.pop("tracecore_allow_local_printers", None)
			with patch.object(print_server.socket, "create_connection") as connect:
				result = print_server.dispatch_job(job)
			connect.assert_not_called()
			self.assertEqual(result, {"status": "Failed", "attempts": 1}, host)
			doc = frappe.get_doc("Print Job", job)
			self.assertEqual(
				(doc.status, doc.output_mode, bool(doc.printed_at)), ("Failed", "Printer", False)
			)
			self.assertIn("printer host not allowed for server printing", doc.error)
			self.assertIn(printer, doc.error)
			self.tx.crash()  # kết quả Failed đã commit ngay
			self.assertEqual(frappe.db.get_value("Print Job", job, "status"), "Failed", host)

	def test_dispatch_inactive_printer_does_nothing(self):
		fake = self.fake_printer()
		job = self.job(self.printer(port=fake.port, is_active=0))

		result = print_server.dispatch_job(job)

		self.assertEqual(result, {"status": "Queued", "attempts": 0})
		self.assertEqual(fake.received, [])
		self.assertEqual(frappe.db.get_value("Print Job", job, ["status", "attempts"]), ("Queued", 0))

	def test_dispatch_job_without_printer_or_invalid_port_does_nothing(self):
		jobs = [core_print.create_job(STATION, ZPL)]
		for port in (0, 65536, -1):
			jobs.append(self.job(self.printer(port=port)))
		with patch.object(print_server.socket, "create_connection") as connect:
			results = [print_server.dispatch_job(job) for job in jobs]
		connect.assert_not_called()
		self.assertEqual(results, [{"status": "Queued", "attempts": 0}] * len(jobs))

	def test_dispatch_only_uses_printer_host_not_job_data(self):
		fake = self.fake_printer()
		decoy = self.fake_printer()
		data = {"host": "127.0.0.1", "port": decoy.port, "printer_host": f"127.0.0.1:{decoy.port}"}
		job = self.job(self.printer(port=fake.port), data=data)

		print_server.dispatch_job(job)

		fake.thread.join(timeout=3)
		self.assertEqual(fake.received, [ZPL.encode("utf-8")])
		self.assertEqual(decoy.received, [])
		self.assertEqual(frappe.db.get_value("Print Job", job, "output_ref"), f"127.0.0.1:{fake.port}")

	def test_public_functions_take_no_host_or_port(self):
		import inspect

		for function in (
			print_server.dispatch_job,
			print_server.enqueue_server_dispatch,
			print_server.dispatch_pending,
		):
			params = set(inspect.signature(function).parameters)
			self.assertFalse(params & {"host", "port", "address"}, function.__name__)

	def test_dispatch_job_is_idempotent_for_printed_job(self):
		job = self.job(self.printer(port=closed_port()))
		core_print.ack(job, "Printed", "File", output_ref="agent.zpl")
		with patch.object(print_server.socket, "create_connection") as connect:
			result = print_server.dispatch_job(job)
		connect.assert_not_called()
		self.assertEqual(result, {"status": "Printed", "attempts": 1})
		self.assertEqual(frappe.db.get_value("Print Job", job, "output_ref"), "agent.zpl")

	def test_dispatch_waiting_job_does_nothing(self):
		data = {"method": "Steam", "label_object": "Pack", "label_context": {}}
		job = core_print.create_job(
			STATION, None, data, "pack-label", printer=self.printer(), status="Waiting"
		)
		with patch.object(print_server.socket, "create_connection") as connect:
			result = print_server.dispatch_job(job)
		connect.assert_not_called()
		self.assertEqual(result, {"status": "Waiting", "attempts": 0})


class TestServerDispatchQueue(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		deactivate_printers(STATION)
		self.label_item = make_label_items()[0]
		self.tx = FakeTransactions(self)
		allow_local_printers(self)  # máy in giả nghe trên 127.0.0.1

	def printer(self, host="127.0.0.1", port=9100):
		name = make_printer(STATION, self.label_item, host=host)
		frappe.db.set_value("Printer", name, "port", port)
		return name

	def server_job(self, printer, age_seconds=120):
		job = core_print.create_job(
			STATION, ZPL, {"label_object": "Equipment"}, "object-label", printer=printer
		)
		with patch.object(print_server.frappe, "enqueue"):
			print_server.enqueue_server_dispatch(job)
		self.age(job, age_seconds)
		return job

	def age(self, job, seconds):
		frappe.db.set_value(
			"Print Job", job, "modified", now_datetime() - timedelta(seconds=seconds), update_modified=False
		)
		self.tx.commit()  # dữ liệu chuẩn bị coi như đã commit trước khi worker chạy

	def test_enqueue_server_dispatch_marks_job_and_enqueues_after_commit(self):
		job = core_print.create_job(
			STATION, ZPL, {"label_object": "Equipment"}, "object-label", printer=self.printer()
		)
		with patch.object(print_server.frappe, "enqueue") as enqueue:
			self.assertIsNone(print_server.enqueue_server_dispatch(job))
		enqueue.assert_called_once()
		args, kwargs = enqueue.call_args
		self.assertEqual(args, ("tracecore.core.print_server.dispatch_job",))
		self.assertEqual(kwargs["job"], job)
		self.assertEqual(kwargs["queue"], "short")
		self.assertTrue(kwargs["enqueue_after_commit"])
		# một job id cố định + deduplicate: bấm in hai lần không xếp hai worker cho cùng lệnh in
		self.assertEqual(kwargs["job_id"], f"tc-print-job-{job}")
		self.assertTrue(kwargs["deduplicate"])
		data = json.loads(frappe.db.get_value("Print Job", job, "data"))
		self.assertEqual(data, {"label_object": "Equipment", "dispatch": "server"})

	def test_dispatch_pending_picks_old_queued_jobs(self):
		fake = FakePrinter()
		self.addCleanup(fake.close)
		printer = self.printer(port=fake.port)
		old = self.server_job(printer)
		fresh = self.server_job(printer, age_seconds=0)
		agent_only = self.server_job(self.printer(host=""))
		# job của đường kiosk → Station Agent (không đánh dấu server) không bao giờ bị server gửi
		kiosk = core_print.create_job(STATION, ZPL, {"label_object": "Pack"}, "pack-label", printer=printer)
		self.age(kiosk, 120)

		self.assertEqual(print_server.dispatch_pending(), 1)

		fake.thread.join(timeout=3)
		self.assertEqual(fake.received, [ZPL.encode("utf-8")])
		statuses = {
			job: frappe.db.get_value("Print Job", job, "status") for job in (old, fresh, agent_only, kiosk)
		}
		self.assertEqual(statuses, {old: "Printed", fresh: "Queued", agent_only: "Queued", kiosk: "Queued"})

	def test_dispatch_pending_fails_queued_job_of_later_blocked_printer(self):
		printer = self.printer(host="10.0.0.5")
		job = self.server_job(printer)
		frappe.db.set_value("Printer", printer, "host", "169.254.169.254")
		frappe.conf.pop("tracecore_allow_local_printers", None)
		self.tx.commit()

		with patch.object(print_server.socket, "create_connection") as connect:
			self.assertEqual(print_server.dispatch_pending(), 1)
		connect.assert_not_called()
		row = frappe.db.get_value("Print Job", job, ["status", "error"], as_dict=True)
		self.assertEqual(row.status, "Failed")
		self.assertIn("printer host not allowed for server printing", row.error)
		self.assertEqual(print_server.dispatch_pending(), 0)

	def test_dispatch_pending_retries_failed_attempts_and_respects_limit(self):
		printer = self.printer(port=closed_port())
		jobs = [self.server_job(printer) for _ in range(3)]

		self.assertEqual(print_server.dispatch_pending(limit=2), 2)
		attempts = sorted(frappe.db.get_value("Print Job", job, "attempts") for job in jobs)
		self.assertEqual(attempts, [0, 1, 1])

		# job vừa thử (modified mới) chờ đủ 1 phút mới thử lại
		self.assertEqual(print_server.dispatch_pending(), 1)
		for job in jobs:
			self.age(job, 120)
		self.assertEqual(print_server.dispatch_pending(), 3)
		self.assertEqual([frappe.db.get_value("Print Job", job, "attempts") for job in jobs], [2, 2, 2])

	def test_dispatch_pending_keeps_going_after_an_unexpected_error(self):
		printer = self.printer(port=closed_port())
		first, second = self.server_job(printer, 180), self.server_job(printer, 120)
		real = print_server.dispatch_job

		def flaky(job):
			if job == first:
				raise RuntimeError("boom")
			return real(job)

		with (
			patch.object(print_server, "dispatch_job", side_effect=flaky),
			patch.object(print_server.frappe, "log_error") as log_error,
		):
			self.assertEqual(print_server.dispatch_pending(), 1)
		log_error.assert_called_once()
		self.assertEqual(frappe.db.get_value("Print Job", second, "attempts"), 1)
		# lỗi bất ngờ vẫn tính một lần thử (không thử lại vô hạn) và ghi lý do
		first_row = frappe.db.get_value("Print Job", first, ["status", "attempts", "error"], as_dict=True)
		self.assertEqual((first_row.status, first_row.attempts), ("Queued", 1))
		self.assertIn("boom", first_row.error)

	def test_dispatch_pending_fails_job_after_three_unexpected_errors(self):
		job = self.server_job(self.printer(port=closed_port()))
		encode_error = UnicodeEncodeError("utf-8", "\ud800", 0, 1, "surrogates not allowed")

		with (
			patch.object(print_server, "_send", side_effect=encode_error),
			patch.object(print_server.frappe, "log_error"),
		):
			for attempt in (1, 2, 3):
				print_server.dispatch_pending()
				self.tx.crash()
				row = frappe.db.get_value("Print Job", job, ["status", "attempts", "error"], as_dict=True)
				self.assertEqual(row.attempts, attempt)
				self.assertIn("surrogates not allowed", row.error)
				self.age(job, 120)
			self.assertEqual(row.status, "Failed")
			self.assertEqual(frappe.db.get_value("Print Job", job, "output_mode"), "Printer")
			# job Failed không còn được quét
			self.assertEqual(print_server.dispatch_pending(), 0)

	def test_dispatch_pending_commits_each_job_before_the_next(self):
		fake = FakePrinter()
		self.addCleanup(fake.close)
		first = self.server_job(self.printer(port=fake.port), 180)
		second = self.server_job(self.printer(port=closed_port()), 120)
		real = print_server.dispatch_job
		crashing = []

		def crash_on_second(job):
			if job == second:
				crashing.append(job)
				self.tx.crash()  # transaction của lần quét bị hủy khi đang làm job sau
				raise RuntimeError("worker lost")
			return real(job)

		with (
			patch.object(print_server, "dispatch_job", side_effect=crash_on_second),
			patch.object(print_server.frappe, "log_error"),
		):
			print_server.dispatch_pending()

		fake.thread.join(timeout=3)
		self.assertEqual(crashing, [second])
		self.assertEqual(fake.received, [ZPL.encode("utf-8")])
		# nhãn job trước đã ra giấy: kết quả Printed phải còn, không bị in lại ở lần quét sau
		self.assertEqual(frappe.db.get_value("Print Job", first, ["status", "attempts"]), ("Printed", 1))

	def test_dispatch_pending_is_not_starved_by_non_server_jobs(self):
		fake = FakePrinter()
		self.addCleanup(fake.close)
		printer = self.printer(port=fake.port)
		window = print_server.PENDING_SCAN_FACTOR + 1  # nhiều hơn cửa sổ đọc của limit=1
		for _ in range(window):
			kiosk = core_print.create_job(
				STATION, ZPL, {"label_object": "Pack"}, "pack-label", printer=printer
			)
			self.age(kiosk, 600)
		agent_only = self.printer(host="")
		for _ in range(window):
			self.server_job(agent_only, 500)
		server = self.server_job(printer, 120)

		self.assertEqual(print_server.dispatch_pending(limit=1), 1)

		fake.thread.join(timeout=3)
		self.assertEqual(frappe.db.get_value("Print Job", server, "status"), "Printed")

	def test_scheduler_runs_dispatch_pending_every_minute(self):
		self.assertIn(
			"tracecore.core.print_server.dispatch_pending", hooks.scheduler_events["cron"]["* * * * *"]
		)


class TestServerDispatchMany(IsolatedTestCase):
	"""Gửi cả lô một worker (FEAT-016 G9): tuần tự, commit từng job, dừng máy in ở lỗi mạng đầu tiên."""

	def setUp(self):
		super().setUp()
		deactivate_printers(STATION)
		self.label_item = make_label_items()[0]
		self.tx = FakeTransactions(self)
		allow_local_printers(self)

	def printer(self, port=9100):
		name = make_printer(STATION, self.label_item, host="127.0.0.1")
		frappe.db.set_value("Printer", name, "port", port)
		return name

	def jobs(self, printer, count):
		jobs = [
			core_print.create_job(
				STATION, ZPL, {"label_object": "Equipment"}, "object-label", printer=printer
			)
			for _ in range(count)
		]
		self.tx.commit()
		return jobs

	def test_enqueue_server_dispatch_many_marks_jobs_and_enqueues_once(self):
		jobs = self.jobs(self.printer(), 3)
		with patch.object(print_server.frappe, "enqueue") as enqueue:
			self.assertIsNone(print_server.enqueue_server_dispatch_many(jobs))
			print_server.enqueue_server_dispatch_many([])
		enqueue.assert_called_once()
		args, kwargs = enqueue.call_args
		self.assertEqual(args, ("tracecore.core.print_server.dispatch_many",))
		self.assertEqual(kwargs["jobs"], jobs)
		self.assertEqual(kwargs["queue"], "short")
		self.assertTrue(kwargs["enqueue_after_commit"])
		self.assertEqual(kwargs["job_id"], f"tc-print-batch-{jobs[0]}-3")
		self.assertTrue(kwargs["deduplicate"])
		for job in jobs:
			data = json.loads(frappe.db.get_value("Print Job", job, "data"))
			self.assertEqual(data, {"label_object": "Equipment", "dispatch": "server"})

	def test_dispatch_many_commits_each_job(self):
		jobs = self.jobs(self.printer(closed_port()), 2)
		sent = []

		def send_then_crash(host, port, payload):
			sent.append(payload)
			if len(sent) == 2:
				self.tx.crash()  # worker chết giữa job thứ hai: job thứ nhất đã commit
				raise KeyboardInterrupt

		with patch.object(print_server, "_send", side_effect=send_then_crash):
			with self.assertRaises(KeyboardInterrupt):
				print_server.dispatch_many(jobs)
		self.assertEqual(frappe.db.get_value("Print Job", jobs[0], ["status", "attempts"]), ("Printed", 1))

	def test_dispatch_many_counts_unexpected_error_and_continues(self):
		jobs = self.jobs(self.printer(), 3)
		calls = []

		def flaky(host, port, payload):
			calls.append(payload)
			if len(calls) == 1:
				raise UnicodeEncodeError("utf-8", "x", 0, 1, "bad")

		with patch.object(print_server, "_send", side_effect=flaky):
			results = print_server.dispatch_many(jobs)
		self.assertEqual(len(calls), 3)  # lỗi không phải lỗi mạng: không dừng lô
		self.assertEqual(
			results,
			[
				{"status": "Queued", "attempts": 1},
				{"status": "Printed", "attempts": 1},
				{"status": "Printed", "attempts": 1},
			],
		)
		self.assertIn("UnicodeEncodeError", frappe.db.get_value("Print Job", jobs[0], "error"))

	def test_dispatch_many_skips_jobs_not_queued(self):
		jobs = self.jobs(self.printer(closed_port()), 2)
		core_print.ack(jobs[0], "Printed", "File", output_ref="agent.zpl")
		with patch.object(print_server.socket, "create_connection", side_effect=ConnectionRefusedError):
			results = print_server.dispatch_many([str(job) for job in jobs])
		self.assertEqual(results, [{"status": "Printed", "attempts": 1}, {"status": "Queued", "attempts": 1}])

	def test_new_public_functions_take_no_host_or_port(self):
		import inspect

		for function in (print_server.dispatch_many, print_server.enqueue_server_dispatch_many):
			params = set(inspect.signature(function).parameters)
			self.assertFalse(params & {"host", "port", "address"}, function.__name__)
