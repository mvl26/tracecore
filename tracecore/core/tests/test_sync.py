"""Phát lại offline: phiên tại `client_ts`, Sync Conflict + NC cho R02 (FEAT-009 Task 3; FR-M9-06.1, FR-M9-06.3; A-40)."""

import json
import uuid
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import frappe
from frappe.utils import add_to_date, get_datetime, now_datetime

from tracecore.core import sync
from tracecore.reprocessing import packing
from tracecore.tests.factories import make_user
from tracecore.tests.utils import IsolatedTestCase, request_headers
from tracecore.v1 import pack as pack_api
from tracecore.v1 import sync as sync_api
from tracecore.v1.tests.station_fixtures import make_station_session

STATION = "TR-004"
TZ = ZoneInfo("Asia/Ho_Chi_Minh")
MISSING_SET = "9520000ZZ999999"


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

	def generate_at(self, moment, key=None, replay_header=True, token=None):
		"""Đóng gói offline một bộ không tồn tại: phiên hợp lệ → SET_NOT_FOUND (404), phiên sai → SESSION_INVALID."""
		return replay(
			pack_api.generate_cycle_id,
			key=key,
			replay_header=replay_header,
			set_id=MISSING_SET,
			station=STATION,
			confirmed_lines=[],
			ci_batch="CI-NONE",
			pack_type="PT-NONE",
			maint_actions=[],
			offline_cycle_id="CY-000000-T004-0001",
			client_ts=ts(moment),
			token=token or self.token,
		)


class TestReplaySession(ReplayCase):
	def test_replay_accepts_session_valid_at_client_ts(self):
		# phiên 9 giờ trước, hết hạn 1 giờ trước (Expired); giao dịch offline lúc 5 giờ trước
		self.end_session(9, 1, "Expired")
		result = self.generate_at(add_to_date(now_datetime(), hours=-5))
		self.assertEqual(result["error"]["code"], "SET_NOT_FOUND", result)

	def test_without_replay_header_expired_session_rejected(self):
		self.end_session(9, 1, "Expired")
		result = self.generate_at(now_datetime(), replay_header=False)
		self.assertEqual(result["error"]["code"], "SESSION_INVALID")

	def test_replay_rejects_client_ts_before_session_start(self):
		result = self.generate_at(add_to_date(now_datetime(), hours=-2))
		self.assertEqual(result["error"]["code"], "SESSION_INVALID")

	def test_replay_rejects_client_ts_after_session_end(self):
		self.end_session(6, 3, "Logout")
		result = self.generate_at(add_to_date(now_datetime(), hours=-1))
		self.assertEqual(result["error"]["code"], "SESSION_INVALID")

	def test_replay_after_disable(self):
		self.end_session(6, 1, "Employee Disabled")
		result = self.generate_at(add_to_date(now_datetime(), hours=-3))
		self.assertEqual(result["error"]["code"], "SESSION_INVALID")

	def test_replay_older_than_24_hours_rejected(self):
		"""Token phiên cũ không là chứng thực dài hạn: phát lại chỉ nhận giao dịch trong 24 giờ (review I4)."""
		self.end_session(30, 22, "Expired")
		result = self.generate_at(add_to_date(now_datetime(), hours=-25))
		self.assertEqual(result["error"]["code"], "SESSION_INVALID")

	def test_replay_header_ignored_on_endpoint_without_offline(self):
		"""Chỉ RPC xếp hàng offline (T1/T4/T8) nhận phát lại; RPC khác vẫn cần phiên đang sống (review I4)."""
		self.end_session(9, 1, "Expired")
		key = str(uuid.uuid4())
		result = replay(
			pack_api.reprint_label,
			key=key,
			cycle_id="CY-200101-0001",
			reason="test",
			station=STATION,
			client_ts=ts(add_to_date(now_datetime(), hours=-5)),
			token=self.token,
		)
		self.assertEqual(result["error"]["code"], "SESSION_INVALID")
		self.assertFalse(frappe.db.exists("Sync Conflict", {"idempotency_key": key}))

	def test_replay_extends_last_activity(self):
		old = add_to_date(now_datetime(), minutes=-30)
		frappe.db.set_value(
			"Station Session",
			self.session.name,
			{"started_at": add_to_date(old, hours=-1), "last_activity_at": old},
		)
		moment = add_to_date(now_datetime(), minutes=-5).replace(microsecond=0)
		self.assertEqual(self.generate_at(moment)["error"]["code"], "SET_NOT_FOUND")
		last = get_datetime(frappe.db.get_value("Station Session", self.session.name, "last_activity_at"))
		self.assertEqual(last, moment)
		self.assertEqual(frappe.db.get_value("Station Session", self.session.name, "is_open"), 1)


class TestSyncConflict(ReplayCase):
	def test_replay_rejection_creates_conflict_and_nc(self):
		key = str(uuid.uuid4())
		result = self.generate_at(now_datetime(), key=key)
		self.assertIs(result["ok"], False)
		conflict = frappe.get_doc("Sync Conflict", {"idempotency_key": key})
		self.assertEqual(conflict.status, "Open")
		self.assertEqual(conflict.http_status, result["error"]["http_status"])
		self.assertEqual(conflict.error_code, result["error"]["code"])
		self.assertEqual(conflict.station, STATION)
		self.assertEqual(conflict.endpoint, "tracecore.v1.pack.generate_cycle_id")
		incident = frappe.get_doc("Incident CAPA", conflict.incident)
		self.assertEqual((incident.incident_type, incident.is_auto), ("Sync Conflict", 1))
		self.assertEqual((incident.source_doctype, incident.source_name), ("Sync Conflict", conflict.name))

	def test_replay_rejection_body_names_conflict(self):
		"""Kiosk chỉ xóa mục khỏi hàng đợi khi server báo đã ghi xung đột (review C1)."""
		key = str(uuid.uuid4())
		result = self.generate_at(now_datetime(), key=key)
		name = frappe.db.get_value("Sync Conflict", {"idempotency_key": key})
		self.assertEqual(result["error"]["sync_conflict"], name)
		again = self.generate_at(now_datetime(), key=key)  # phát lại lần hai: response đã lưu, cùng xung đột
		self.assertEqual(again["error"]["sync_conflict"], name)

	def test_conflict_once_per_key(self):
		key = str(uuid.uuid4())
		moment = now_datetime()
		self.generate_at(moment, key=key)
		self.generate_at(moment, key=key)
		self.assertEqual(frappe.db.count("Sync Conflict", {"idempotency_key": key}), 1)
		name = frappe.db.get_value("Sync Conflict", {"idempotency_key": key})
		self.assertEqual(frappe.db.count("Incident CAPA", {"source_name": name}), 1)

	def test_non_replay_rejection_creates_no_conflict(self):
		key = str(uuid.uuid4())
		self.generate_at(now_datetime(), key=key, replay_header=False)
		self.assertFalse(frappe.db.exists("Sync Conflict", {"idempotency_key": key}))

	def test_replay_unknown_token_records_nothing(self):
		"""Token không thuộc phiên nào (khách, rác) không tạo được Sync Conflict (review I3)."""
		key = str(uuid.uuid4())
		before = frappe.db.count("Sync Conflict")
		result = self.generate_at(now_datetime(), key=key, token="garbage-" + uuid.uuid4().hex)
		self.assertEqual(result["error"]["code"], "SESSION_INVALID")
		self.assertNotIn("sync_conflict", result["error"])
		self.assertEqual(frappe.db.count("Sync Conflict"), before)

	def test_replay_invalid_key_records_nothing(self):
		before = frappe.db.count("Sync Conflict")
		with self.assertRaises(frappe.ValidationError):
			self.generate_at(now_datetime(), key="not-a-uuid")
		self.assertEqual(frappe.db.count("Sync Conflict"), before)

	def test_server_side_validation_error_is_retried_not_conflict(self):
		"""Lỗi 417 chung (frappe.throw, sửa đồng thời) là lỗi server, kiosk thử lại; không thành NC (review I6)."""
		key = str(uuid.uuid4())
		with patch.object(packing, "generate", side_effect=frappe.ValidationError("boom")):
			with self.assertRaises(frappe.ValidationError):
				self.generate_at(now_datetime(), key=key)
		self.assertFalse(frappe.db.exists("Sync Conflict", {"idempotency_key": key}))

	def test_client_state_keeps_encrypted_patient_code_only(self):
		"""Mã BN mã hóa là bản duy nhất khi gói bị từ chối: giữ lại cho R02; mã rõ và token thì bỏ (review C2)."""
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
		state = json.loads(frappe.db.get_value("Sync Conflict", name, "client_state"))
		self.assertEqual(state["patient_code_enc"], "QUJD")
		for secret in ("BN123456", "secret-token"):
			self.assertNotIn(secret, json.dumps(state))
		self.assertEqual(state["cycle_id"], "CY-261026-0001")

	def test_replay_permission_error_becomes_conflict(self):
		user = make_user("sync-r03@test.local", roles=("TC R03",))
		token = make_station_session(user)["token"]
		frappe.set_user(user)
		self.addCleanup(frappe.set_user, "Administrator")
		key = str(uuid.uuid4())
		result = self.generate_at(now_datetime(), key=key, token=token)
		self.assertIs(result["ok"], False, result)
		self.assertEqual(result["error"]["code"], "PERMISSION_DENIED", result)
		frappe.set_user("Administrator")
		self.assertTrue(frappe.db.exists("Sync Conflict", {"idempotency_key": key, "http_status": 403}))


class TestResolve(ReplayCase):
	def test_resolve_requires_r02_and_note(self):
		key = str(uuid.uuid4())
		self.generate_at(now_datetime(), key=key)
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


TECHNICAL_FIELDS = (
	"section_request",
	"endpoint",
	"idempotency_key",
	"ref_doctype",
	"ref_name",
	"column_break_error",
	"http_status",
	"error_code",
	"section_state",
	"client_state",
	"server_state",
)


class TestReadableConflict(IsolatedTestCase):
	"""Trang Xung đột đồng bộ cho người dùng khoa: câu dễ hiểu, không JSON, không lộ dữ liệu kỹ thuật."""

	def _conflict(self, args=None, error=None, endpoint="tracecore.v1.pack.generate_cycle_id"):
		name = sync.record_conflict(
			endpoint=endpoint,
			key=frappe.generate_hash(length=20),
			client_ts=datetime(2026, 10, 27, 10, 47),
			args=args
			if args is not None
			else {
				"set_id": "S-READ-1",
				"pack_type": "GOI",
				"ci_batch": "CI-1",
				"confirmed_lines": ["KC-1", "KC-2"],
				"client_ts": "2026-10-27T17:47:13+07:00",
				"station": "TR-004",
				"maint_actions": [],
			},
			error=error
			or {
				"code": "SESSION_INVALID",
				"title": "Station session is invalid",
				"reason": "r",
				"action": "a",
			},
			http_status=401,
			session={"station": None, "employee": None, "user": "Administrator"},
		)
		return frappe.get_doc("Sync Conflict", name)

	def test_client_time_is_stored_in_system_time(self):
		doc = self._conflict()
		self.assertEqual(get_datetime(doc.client_ts), datetime(2026, 10, 27, 17, 47))

	def test_readable_has_sentences_and_no_raw_keys(self):
		data = sync.readable(self._conflict())
		for key in ("operation", "outcome", "reason", "todo"):
			self.assertTrue(data[key], key)
		text = frappe.as_json(data)
		for raw in (
			"ci_batch",
			"pack_type",
			"confirmed_lines",
			"SESSION_INVALID",
			"tracecore.v1",
			"maint_actions",
		):
			self.assertNotIn(raw, text)

	def test_details_list_known_values_only(self):
		values = {row["value"] for row in sync.readable(self._conflict())["details"]}
		self.assertIn("GOI", values)
		self.assertIn("CI-1", values)
		self.assertIn("KC-1, KC-2", values)
		self.assertNotIn("2026-10-27T17:47:13+07:00", values)

	def test_unknown_endpoint_and_broken_state_still_readable(self):
		doc = self._conflict(args={}, endpoint="tracecore.v1.other.thing")
		doc.server_state = "not json"
		doc.client_state = "not json"
		data = sync.readable(doc)
		self.assertTrue(data["operation"])
		self.assertTrue(data["reason"])
		self.assertEqual(data["details"], [])

	def test_form_sends_readable_on_load(self):
		doc = self._conflict()
		doc.run_method("onload")
		self.assertIn("readable", doc.get_onload())

	def test_technical_fields_are_hidden(self):
		meta = frappe.get_meta("Sync Conflict")
		for field in TECHNICAL_FIELDS:
			self.assertTrue(meta.get_field(field).hidden, field)
		self.assertFalse(meta.get_field("incident").hidden)
