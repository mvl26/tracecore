"""T4 sinh Cycle ID offline từ dải cấp trước rồi phát lại (FEAT-009 Task 5; FR-M2-07.11, FR-M9-06.2, NFR-L10N-01; A-40)."""

import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import frappe
from frappe.utils import add_to_date, get_datetime, now_datetime

from tracecore.core import code_range, sync
from tracecore.tests.factories import deactivate_printers, make_t4_ready_set
from tracecore.tests.utils import IsolatedTestCase, request_headers
from tracecore.v1 import pack as pack_api
from tracecore.v1.tests.station_fixtures import make_station_session

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]
STATION = "TR-004"
TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def iso(moment):
	return moment.replace(tzinfo=TZ).isoformat(timespec="seconds")


def last_2330(now):
	"""Mốc 23:30 gần nhất đã qua: luôn trong 24 giờ (giới hạn phiên offline), dù test chạy lúc 23:45 hay 10:00."""
	moment = datetime.combine(now.date(), datetime.min.time()).replace(hour=23, minute=30)
	return moment if moment <= now else moment - timedelta(days=1)


class OfflinePackCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		frappe.get_doc("User", "Administrator").add_roles("TC R10", "TC R04")
		self.token = make_station_session("Administrator")["token"]
		self.session = frappe.db.get_value(
			"Station Session", {"station": STATION, "is_open": 1, "user": "Administrator"}
		)
		deactivate_printers(STATION)
		self.addCleanup(frappe.local.response.pop, "http_status_code", None)

	def backdate_session(self, start):
		frappe.db.set_value(
			"Station Session",
			self.session,
			{
				"started_at": start,
				"last_activity_at": start,
				"absolute_expires_at": add_to_date(start, hours=8),
			},
		)

	def code_for(self, day, index=0):
		row = code_range.allocate(STATION, day)
		return f"{row['prefix']}{row['from_no'] + index:04d}"

	def generate(self, ready, code, moment, key=None):
		frappe.local.response.pop("http_status_code", None)
		headers = {
			"X-Idempotency-Key": key or str(uuid.uuid4()),
			"X-TC-Station": STATION,
			sync.REPLAY_HEADER: "1",
		}
		with request_headers(headers):
			return pack_api.generate_cycle_id(
				set_id=ready.set_id,
				station=STATION,
				confirmed_lines=list(ready.instruments),
				ci_batch=ready.ci_batch,
				pack_type=ready.pack_type,
				maint_actions=[],
				offline_cycle_id=code,
				client_ts=iso(moment),
				token=self.token,
			)


class TestOfflineGenerate(OfflinePackCase):
	def test_offline_generate_uses_range_code(self):
		moment = add_to_date(now_datetime(), hours=-3).replace(microsecond=0)
		self.backdate_session(add_to_date(moment, hours=-1))
		ready = make_t4_ready_set()
		code = self.code_for(moment.date())
		result = self.generate(ready, code, moment)
		self.assertIs(result["ok"], True, result)
		self.assertEqual(result["pack"]["cycle_id"], code)
		pack = frappe.get_doc("Pack", code)
		self.assertEqual(get_datetime(pack.packed_at), moment)
		self.assertEqual(frappe.db.get_value("Code Registry", code, "ref_doctype"), "Pack")
		self.assertEqual(frappe.db.get_value("Set Unit", ready.set_id, "active_cycle_id"), code)
		gate = frappe.db.get_value(
			"Step Gate Result", {"set_unit": ready.set_id, "step": "T4"}, "recorded_at"
		)
		self.assertEqual(get_datetime(gate), moment)  # FR-M1-06.4: cổng theo thời điểm ở trạm

	def test_offline_generate_future_client_ts_rejected(self):
		moment = add_to_date(now_datetime(), hours=1).replace(microsecond=0)
		self.backdate_session(add_to_date(now_datetime(), hours=-1))
		frappe.db.set_value(
			"Station Session", self.session, "absolute_expires_at", add_to_date(moment, hours=2)
		)
		ready = make_t4_ready_set()
		key = str(uuid.uuid4())
		result = self.generate(ready, self.code_for(moment.date()), moment, key=key)
		self.assertIs(result["ok"], False)
		self.assertEqual(result["error"]["http_status"], 400)
		self.assertTrue(frappe.db.exists("Sync Conflict", {"idempotency_key": key}))
		self.assertFalse(frappe.db.exists("Pack", {"set_unit": ready.set_id}))

	def test_offline_generate_code_other_day_conflict(self):
		moment = now_datetime().replace(microsecond=0)
		ready = make_t4_ready_set()
		code = self.code_for(moment.date() - timedelta(days=1))
		key = str(uuid.uuid4())
		result = self.generate(ready, code, moment, key=key)
		self.assertEqual(result["error"]["code"], "CODE_RANGE_INVALID")
		self.assertFalse(frappe.db.exists("Pack", code))
		conflict = frappe.get_doc("Sync Conflict", {"idempotency_key": key})
		self.assertEqual((conflict.error_code, conflict.ref_doctype), ("CODE_RANGE_INVALID", "Set Unit"))

	def test_last_2330_stays_within_the_offline_cap(self):
		# CI chạy 23:45 giờ VN: lấy 23:30 hôm nay (hôm qua 23:30 đã quá 24 giờ, phiên offline bị từ chối)
		self.assertEqual(last_2330(datetime(2026, 10, 28, 23, 45)), datetime(2026, 10, 28, 23, 30))
		self.assertEqual(last_2330(datetime(2026, 10, 28, 10, 0)), datetime(2026, 10, 27, 23, 30))

	def test_offline_2330_synced_0010_keeps_day(self):
		moment = last_2330(now_datetime())
		self.backdate_session(moment.replace(hour=23, minute=0))
		ready = make_t4_ready_set()
		code = self.code_for(moment.date())
		result = self.generate(ready, code, moment)
		self.assertIs(result["ok"], True, result)
		self.assertIn(f"CY-{moment:%y%m%d}-T004-", code)
		self.assertEqual(get_datetime(frappe.db.get_value("Pack", code, "packed_at")).date(), moment.date())

	def test_replay_twice_same_key(self):
		moment = now_datetime().replace(microsecond=0)
		ready = make_t4_ready_set()
		code = self.code_for(moment.date())
		key = str(uuid.uuid4())
		first = self.generate(ready, code, moment, key=key)
		second = self.generate(ready, code, moment, key=key)
		self.assertIs(first["ok"], True, first)
		self.assertEqual(first["pack"]["cycle_id"], second["pack"]["cycle_id"])
		self.assertEqual(frappe.db.count("Pack", {"set_unit": ready.set_id}), 1)
		self.assertFalse(frappe.db.exists("Sync Conflict", {"idempotency_key": key}))
