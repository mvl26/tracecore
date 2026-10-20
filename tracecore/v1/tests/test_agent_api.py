import base64
import uuid

import frappe

from tracecore import v1
from tracecore.core import print as core_print
from tracecore.tests.factories import make_user
from tracecore.tests.utils import IsolatedTestCase, request_headers
from tracecore.v1 import agent as agent_api
from tracecore.v1 import print as print_api

TS = "2026-10-19T09:00:00+07:00"


def call(fn, **kwargs):
	with request_headers({"X-Idempotency-Key": str(uuid.uuid4()), "X-TC-Station": "TR-004"}):
		return fn(client_ts=TS, **kwargs)


class TestAgentApi(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		# user agent của trạm TR-004 theo quy ước provision: agent-<trạm>@tracecore.local
		frappe.set_user(make_user("agent-tr-004@tracecore.local", roles=["TC Agent"]))

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.cache.hdel(v1.AGENT_HEARTBEAT_CACHE, "TR-004")

	def test_agent_heartbeat_rejected_for_inactive_station(self):
		frappe.db.set_value("Zone Station", "TR-004", "is_active", 0)
		for fn in (agent_api.heartbeat, print_api.test_label):
			with self.assertRaises(frappe.ValidationError, msg=fn.__name__) as raised:
				call(fn, station="TR-004")
			self.assertEqual(raised.exception.http_status_code, 409, msg=fn.__name__)
			self.assertIn("TR-004", str(raised.exception))
		self.assertIsNone(frappe.cache.hget(v1.AGENT_HEARTBEAT_CACHE, "TR-004"))

	def test_agent_bound_to_its_station(self):
		for fn in (agent_api.heartbeat, print_api.test_label):
			with self.assertRaises(frappe.PermissionError, msg=fn.__name__):
				call(fn, station="TR-003")

	def test_ack_rejects_job_of_other_station(self):
		frappe.set_user("Administrator")
		job = core_print.create_job("TR-003", "^XA^XZ")
		frappe.set_user("agent-tr-004@tracecore.local")
		with self.assertRaises(frappe.PermissionError):
			call(print_api.ack, print_job=job, status="Printed", output_mode="File")
		self.assertEqual(frappe.db.get_value("Print Job", job, "status"), "Queued")

	def test_test_label_creates_queued_job(self):
		result = call(print_api.test_label, station="TR-004")
		job = frappe.get_doc("Print Job", result["print_job"])
		self.assertEqual((job.status, job.station, job.template), ("Queued", "TR-004", "test-label"))
		self.assertEqual(job.payload, result["zpl"])
		self.assertTrue(base64.b64decode(result["preview_png_b64"]).startswith(b"\x89PNG"))

	def test_ack_marks_printed(self):
		job = call(print_api.test_label, station="TR-004")["print_job"]
		result = call(
			print_api.ack, print_job=job, status="Printed", output_mode="File", output_ref="/x/1.zpl"
		)
		self.assertEqual(result, {"ok": True, "status": "Printed"})
		self.assertEqual(frappe.db.get_value("Print Job", job, "status"), "Printed")

	def test_agent_endpoints_require_role(self):
		frappe.set_user(make_user("no-agent@example.com", roles=["TC R04"]))
		for fn in (agent_api.heartbeat, print_api.test_label):
			with self.assertRaises(frappe.PermissionError, msg=fn.__name__):
				call(fn, station="TR-004")

	def test_unknown_station_rejected(self):
		for fn in (agent_api.heartbeat, print_api.test_label):
			with self.assertRaises(frappe.ValidationError, msg=fn.__name__):
				call(fn, station="TR-999")

	def test_heartbeat_visible_in_ping(self):
		result = call(
			agent_api.heartbeat, station="TR-004", agent_version="0.1.0", queue_depth=2, printer="file"
		)
		self.assertTrue(result["ok"])
		frappe.set_user("Administrator")
		agent = v1.ping(station="TR-004")["agent"]
		self.assertEqual(
			(agent["agent_version"], agent["queue_depth"], agent["printer"]), ("0.1.0", 2, "file")
		)
		self.assertTrue(agent["last_seen"])
