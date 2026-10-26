"""Phát lại offline: phiên tại `client_ts`, Sync Conflict + NC cho R02 (FEAT-009 Task 3; FR-M9-06.1, FR-M9-06.3; A-40)."""

import json
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import frappe
from frappe.utils import add_to_date, get_datetime, now_datetime

from tracecore.core import sync
from tracecore.tests.factories import make_user
from tracecore.tests.utils import IsolatedTestCase, request_headers
from tracecore.v1 import code_range as code_range_api
from tracecore.v1 import pack as pack_api
from tracecore.v1 import sync as sync_api
from tracecore.v1.tests.station_fixtures import make_station_session

STATION = "TR-004"
TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def ts(moment):
	"""Giờ hệ thống không múi giờ → ISO 8601 có offset như kiosk gửi."""
	return moment.replace(tzinfo=TZ).isoformat(timespec="seconds")


def replay(fn, key=None, replay_header=True, **kwargs):
	frappe.local.response.pop("http_status_code", None)
	headers = {"X-Idempotency-Key": key or str(uuid.uuid4()), "X-TC-Station": STATION}
	if replay_header:
		headers[sync.REPLAY_HEADER] = "1"
	with request_headers(headers):
		return fn(**kwargs)


class ReplayCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		frappe.get_doc("User", "Administrator").add_roles("TC R10", "TC R04", "TC R02")
		login = make_station_session("Administrator")
		self.token = login["token"]
		self.session = frappe.get_doc(
			"Station Session", {"station": STATION, "is_open": 1, "user": "Administrator"}
		)
		self.addCleanup(frappe.local.response.pop, "http_status_code", None)

	def end_session(self, started_hours_ago, ended_hours_ago, reason):
		now = now_datetime()
		frappe.db.set_value(
			"Station Session",
			self.session.name,
			{
				"started_at": add_to_date(now, hours=-started_hours_ago),
				"last_activity_at": add_to_date(now, hours=-ended_hours_ago),
				"absolute_expires_at": add_to_date(now, hours=8 - started_hours_ago),
				"is_open": 0,
				"ended_at": add_to_date(now, hours=-ended_hours_ago),
				"end_reason": reason,
			},
		)

	def allocate_at(self, moment, **kw):
		return replay(code_range_api.allocate, station=STATION, client_ts=ts(moment), token=self.token, **kw)

	def reprint_missing(self, key=None, replay_header=True):
		return replay(
			pack_api.reprint_label,
			key=key,
			replay_header=replay_header,
			cycle_id="CY-200101-0001",
			reason="test",
			station=STATION,
			client_ts=ts(now_datetime()),
			token=self.token,
		)


class TestReplaySession(ReplayCase):
	def test_replay_accepts_session_valid_at_client_ts(self):
		# phiên 9 giờ trước, hết hạn 1 giờ trước (Expired); giao dịch offline lúc 5 giờ trước
		self.end_session(9, 1, "Expired")
		result = self.allocate_at(add_to_date(now_datetime(), hours=-5))
		self.assertIs(result["ok"], True)

	def test_without_replay_header_expired_session_rejected(self):
		self.end_session(9, 1, "Expired")
		result = replay(
			code_range_api.allocate,
			replay_header=False,
			station=STATION,
			client_ts=ts(now_datetime()),
			token=self.token,
		)
		self.assertEqual(result["error"]["code"], "SESSION_INVALID")

	def test_replay_rejects_client_ts_before_session_start(self):
		result = self.allocate_at(add_to_date(now_datetime(), hours=-2))
		self.assertIs(result["ok"], False)
		self.assertEqual(result["error"]["code"], "SESSION_INVALID")

	def test_replay_rejects_client_ts_after_session_end(self):
		self.end_session(6, 3, "Logout")
		result = self.allocate_at(add_to_date(now_datetime(), hours=-1))
		self.assertEqual(result["error"]["code"], "SESSION_INVALID")

	def test_replay_after_disable(self):
		self.end_session(6, 1, "Employee Disabled")
		result = self.allocate_at(add_to_date(now_datetime(), hours=-3))
		self.assertEqual(result["error"]["code"], "SESSION_INVALID")

	def test_replay_extends_last_activity(self):
		old = add_to_date(now_datetime(), minutes=-30)
		frappe.db.set_value(
			"Station Session",
			self.session.name,
			{"started_at": add_to_date(old, hours=-1), "last_activity_at": old},
		)
		moment = add_to_date(now_datetime(), minutes=-5).replace(microsecond=0)
		self.assertIs(self.allocate_at(moment)["ok"], True)
		last = get_datetime(frappe.db.get_value("Station Session", self.session.name, "last_activity_at"))
		self.assertEqual(last, moment)
		self.assertEqual(frappe.db.get_value("Station Session", self.session.name, "is_open"), 1)


class TestSyncConflict(ReplayCase):
	def test_replay_rejection_creates_conflict_and_nc(self):
		key = str(uuid.uuid4())
		result = self.reprint_missing(key=key)
		self.assertIs(result["ok"], False)
		conflict = frappe.get_doc("Sync Conflict", {"idempotency_key": key})
		self.assertEqual(conflict.status, "Open")
		self.assertEqual(conflict.http_status, result["error"]["http_status"])
		self.assertEqual(conflict.error_code, result["error"]["code"])
		self.assertEqual(conflict.station, STATION)
		self.assertEqual(conflict.endpoint, "tracecore.v1.pack.reprint_label")
		self.assertEqual((conflict.ref_doctype, conflict.ref_name), ("Pack", "CY-200101-0001"))
		incident = frappe.get_doc("Incident CAPA", conflict.incident)
		self.assertEqual((incident.incident_type, incident.is_auto), ("Sync Conflict", 1))
		self.assertEqual((incident.source_doctype, incident.source_name), ("Sync Conflict", conflict.name))

	def test_conflict_once_per_key(self):
		key = str(uuid.uuid4())
		self.reprint_missing(key=key)
		self.reprint_missing(key=key)
		self.assertEqual(frappe.db.count("Sync Conflict", {"idempotency_key": key}), 1)
		name = frappe.db.get_value("Sync Conflict", {"idempotency_key": key})
		self.assertEqual(frappe.db.count("Incident CAPA", {"source_name": name}), 1)

	def test_non_replay_rejection_creates_no_conflict(self):
		key = str(uuid.uuid4())
		self.reprint_missing(key=key, replay_header=False)
		self.assertFalse(frappe.db.exists("Sync Conflict", {"idempotency_key": key}))

	def test_client_state_redacts_patient_code_and_token(self):
		name = sync.record_conflict(
			endpoint="tracecore.v1.usage.confirm",
			key=str(uuid.uuid4()),
			client_ts=datetime(2026, 10, 26, 2, 0),
			args={
				"cycle_id": "CY-261026-0001",
				"patient_code": "BN123456",
				"patient_code_enc": "QUJD",
				"token": "secret-token",
				"station": STATION,
			},
			error={"code": "PACK_USED", "http_status": 409},
			http_status=409,
		)
		state = frappe.db.get_value("Sync Conflict", name, "client_state")
		for secret in ("BN123456", "QUJD", "secret-token"):
			self.assertNotIn(secret, state)
		self.assertEqual(json.loads(state)["cycle_id"], "CY-261026-0001")

	def test_replay_permission_error_becomes_conflict(self):
		user = make_user("sync-r03@test.local", roles=("TC R03",))
		token = make_station_session(user)["token"]
		frappe.set_user(user)
		self.addCleanup(frappe.set_user, "Administrator")
		key = str(uuid.uuid4())
		result = replay(
			code_range_api.allocate, key=key, station=STATION, client_ts=ts(now_datetime()), token=token
		)
		self.assertIs(result["ok"], False, result)
		self.assertEqual(result["error"]["code"], "PERMISSION_DENIED", result)
		frappe.set_user("Administrator")
		self.assertTrue(frappe.db.exists("Sync Conflict", {"idempotency_key": key, "http_status": 403}))


class TestResolve(ReplayCase):
	def test_resolve_requires_r02_and_note(self):
		key = str(uuid.uuid4())
		self.reprint_missing(key=key)
		name = frappe.db.get_value("Sync Conflict", {"idempotency_key": key})
		with self.assertRaises(frappe.ValidationError):
			sync_api.resolve(name=name, note="")
		user = make_user("sync-r04@test.local", roles=("TC R04",))
		frappe.set_user(user)
		self.addCleanup(frappe.set_user, "Administrator")
		with self.assertRaises(frappe.PermissionError):
			sync_api.resolve(name=name, note="đã kiểm tra")
		frappe.set_user("Administrator")
		sync_api.resolve(name=name, note="Giữ bản server, gói đã thu hồi")
		doc = frappe.get_doc("Sync Conflict", name)
		self.assertEqual((doc.status, doc.resolved_by), ("Resolved", "Administrator"))
		self.assertTrue(doc.resolved_at)
