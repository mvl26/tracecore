"""Đường in từ server (A-05 R1, ADR-006 dự phòng): Print Job `Queued` → TCP tới `Printer.host:Printer.port`.

Máy in giả là một socket server cục bộ trên 127.0.0.1 (không cần máy in thật); cổng đóng = máy in từ chối kết nối.
"""

import json
import socket
import threading
import time
from datetime import timedelta
from unittest.mock import patch

import frappe
from frappe.utils import now_datetime

from tracecore import hooks
from tracecore.core import print as core_print
from tracecore.core import print_server
from tracecore.tests.factories import deactivate_printers, make_label_items, make_printer
from tracecore.tests.utils import IsolatedTestCase

STATION = "TR-004"
ZPL = "^XA^FO30,40^BQN,2,6^FDMA,TB-0001^FS^XZ"


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


def closed_port():
	"""Một cổng TCP cục bộ không có ai nghe (kết nối bị từ chối ngay)."""
	with socket.create_server(("127.0.0.1", 0)) as probe:
		return probe.getsockname()[1]


class TestServerDispatch(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		deactivate_printers(STATION)
		self.label_item = make_label_items()[0]

	def printer(self, host="127.0.0.1", port=9100, is_active=1):
		name = make_printer(STATION, self.label_item, host=host)
		frappe.db.set_value("Printer", name, {"port": port, "is_active": is_active})
		return name

	def job(self, printer, data=None, zpl=ZPL):
		return core_print.create_job(STATION, zpl, data, "object-label", printer=printer)

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
		connect.assert_called_once_with(("printer.local", 9100), timeout=print_server.SEND_TIMEOUT_S)
		self.assertEqual(print_server.SEND_TIMEOUT_S, 5)
		self.assertEqual(result, {"status": "Queued", "attempts": 1})
		self.assertIn("timed out", frappe.db.get_value("Print Job", job, "error"))

	def test_dispatch_ignores_agent_only_printer(self):
		for host in ("", "   "):
			job = self.job(self.printer(host=host))
			with patch.object(print_server.socket, "create_connection") as connect:
				result = print_server.dispatch_job(job)
			connect.assert_not_called()
			self.assertEqual(result, {"status": "Queued", "attempts": 0})
			doc = frappe.get_doc("Print Job", job)
			self.assertEqual((doc.status, doc.attempts, doc.error), ("Queued", 0, None))

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
		self.assertEqual(frappe.db.get_value("Print Job", first, "attempts"), 0)

	def test_scheduler_runs_dispatch_pending_every_minute(self):
		self.assertIn(
			"tracecore.core.print_server.dispatch_pending", hooks.scheduler_events["cron"]["* * * * *"]
		)
