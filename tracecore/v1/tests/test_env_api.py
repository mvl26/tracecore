"""RPC tracecore.v1.env.log — cảm biến môi trường đẩy số liệu qua agent của trạm (FEAT-008, FR-M9-04, EI-HW-005, A-55 Q1/D4)."""

import uuid

import frappe
from frappe.utils import add_to_date, now_datetime

from tracecore.tests.factories import make_user
from tracecore.tests.utils import IsolatedTestCase, request_headers
from tracecore.v1 import env as env_api
from tracecore.v1._common import BadRequestError

# giờ đo 1 phút trước, giờ site (Asia/Ho_Chi_Minh, +07:00): không phụ thuộc giờ chạy test
TS = add_to_date(now_datetime(), minutes=-1).replace(microsecond=0).isoformat() + "+07:00"
STATION = "TR-004"
AGENT = "agent-tr-004@tracecore.local"


def call(key=None, **kwargs):
	with request_headers({"X-Idempotency-Key": key or str(uuid.uuid4()), "X-TC-Station": STATION}):
		return env_api.log(station=kwargs.pop("station", STATION), client_ts=TS, **kwargs)


class TestEnvApi(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user("Administrator")
		self.zone = frappe.db.get_value("Zone Station", STATION, "parent_zone")
		frappe.db.set_value("Zone Station", self.zone, {"env_monitored": 1, "temp_max": 24})
		frappe.set_user(make_user(AGENT, roles=["TC Agent"]))

	def test_sensor_reading_is_recorded_for_the_zone_of_the_station(self):
		result = call(measured_at=TS, temperature=22.5, humidity="48", sensor_id="S-01")
		self.assertTrue(result["ok"])
		doc = frappe.get_doc("Environment Log", result["name"])
		self.assertEqual(
			(doc.docstatus, doc.zone, doc.source, doc.sensor_id, doc.temperature, doc.humidity),
			(1, self.zone, "Sensor", "S-01", "22.5", "48"),  # số đo lưu ô Data đã chuẩn hóa (A-55)
		)
		self.assertEqual(result["out_of_range"], 0)

	def test_out_of_range_is_reported_back(self):
		self.assertEqual(call(measured_at=TS, temperature=30)["out_of_range"], 1)

	def test_same_key_records_once(self):
		key = str(uuid.uuid4())
		first = call(key=key, measured_at=TS, temperature=20)
		second = call(key=key, measured_at=TS, temperature=20)
		self.assertEqual(first["name"], second["name"])
		self.assertEqual(frappe.db.count("Environment Log", {"zone": self.zone}), 1)

	def test_unmonitored_zone_is_rejected_with_a_code(self):
		frappe.db.set_value("Zone Station", self.zone, "env_monitored", 0)
		result = call(measured_at=TS, temperature=20)
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "ENV_ZONE_NOT_MONITORED")
		self.assertEqual(frappe.db.count("Environment Log", {"zone": self.zone}), 0)

	def test_invalid_reading_is_rejected_with_a_code(self):
		result = call(measured_at=TS, humidity=150)
		self.assertEqual(result["error"]["code"], "ENV_READING_INVALID")
		result = call(measured_at=TS)
		self.assertEqual(result["error"]["code"], "ENV_READING_INVALID")

	def test_malformed_values_are_bad_requests(self):
		with self.assertRaises(BadRequestError):
			call(measured_at=TS, temperature="hot")
		with self.assertRaises(frappe.ValidationError):
			call(measured_at="30/10/2026 09:00", temperature=20)

	def test_agent_only_for_its_own_station(self):
		with self.assertRaises(frappe.PermissionError):
			call(station="TR-003", measured_at=TS, temperature=20)
		frappe.set_user("Administrator")
		frappe.set_user(make_user("env-no-agent@example.com", roles=["TC R04"]))
		with self.assertRaises(frappe.PermissionError):
			call(measured_at=TS, temperature=20)
