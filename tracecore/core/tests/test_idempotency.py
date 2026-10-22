import threading
import time
import uuid
from datetime import datetime

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, now_datetime

from tracecore.core import idempotency
from tracecore.core.client_time import ClientTimestampError, parse_client_ts
from tracecore.tests.factories import make_department, make_pack_type, make_user
from tracecore.tests.utils import request_headers

TS = "2026-10-19T09:00:00+07:00"
CALLS = []


@idempotency.idempotent
def sample_write(value, client_ts=None):
	CALLS.append(value)
	return {"echo": value, "n": len(CALLS)}


@idempotency.idempotent
def failing_write(value, client_ts=None):
	frappe.get_doc(
		{
			"doctype": "Instrument Set Type",
			"type_code": "IDF",
			"set_type_name": "x",
			"method": "Steam",
			"department": make_department(),
			"default_pack_type": make_pack_type(),
		}
	).insert()
	raise frappe.ValidationError("boom")


@idempotency.idempotent
def rejecting_write(value, client_ts=None):
	CALLS.append(value)
	return {"ok": False, "error": {"code": "SAMPLE_BLOCK", "http_status": value}}


@idempotency.idempotent
def status_less_rejection(value, client_ts=None):
	# như _common.rejection của FEAT-001: không có error.http_status
	CALLS.append(value)
	return {"ok": False, "error": {"code": "OLD_STYLE"}}


@idempotency.idempotent
def slow_write(value, client_ts=None):
	CALLS.append(value)
	time.sleep(1.5)
	return {"echo": value}


def call(func, key, **kwargs):
	with request_headers({"X-Idempotency-Key": key}):
		return func(**kwargs)


class TestIdempotencyConcurrency(FrappeTestCase):
	"""Hai request cùng key chạy song song trên hai kết nối DB (REPEATABLE READ của MariaDB)."""

	def test_concurrent_same_key_returns_stored_response(self):
		CALLS.clear()
		key = str(uuid.uuid4())
		site, sites_path = frappe.local.site, frappe.local.sites_path
		# mở snapshot của transaction chính trước khi request kia commit
		frappe.db.sql("select count(*) from `tabIdempotency Key`")
		frappe.local.message_log = []

		def other_request():
			frappe.init(site=site, sites_path=sites_path)
			frappe.connect()
			frappe.set_user("Administrator")
			try:
				call(slow_write, key, value="a", client_ts=TS)
				frappe.db.commit()
			finally:
				frappe.destroy()

		thread = threading.Thread(target=other_request)
		thread.start()
		time.sleep(0.5)  # request kia đã giữ khóa dòng Idempotency Key
		try:
			result = call(slow_write, key, value="a", client_ts=TS)
		finally:
			thread.join()
			frappe.db.rollback()
			frappe.db.delete("Idempotency Key", {"name": key})
			frappe.db.commit()

		self.assertEqual(result, {"echo": "a"})
		self.assertEqual(CALLS, ["a"])
		self.assertFalse([m for m in frappe.local.message_log if "already exists" in str(m)])


class TestClientTime(FrappeTestCase):
	def test_parse_client_ts(self):
		self.assertEqual(parse_client_ts(TS), datetime(2026, 10, 19, 2, 0, 0))
		self.assertEqual(parse_client_ts("2026-10-19T02:00:00Z"), datetime(2026, 10, 19, 2, 0, 0))
		for bad in ("2026-10-19T09:00:00", "yesterday", "", None):
			with self.assertRaises(ClientTimestampError, msg=repr(bad)):
				parse_client_ts(bad)


class TestIdempotency(FrappeTestCase):
	def setUp(self):
		CALLS.clear()

	def test_missing_or_invalid_key_rejected(self):
		with request_headers({}):
			with self.assertRaises(idempotency.IdempotencyKeyError):
				sample_write(value=1, client_ts=TS)
		with self.assertRaises(idempotency.IdempotencyKeyError):
			call(sample_write, "not-a-uuid", value=1, client_ts=TS)
		self.assertEqual(CALLS, [])

	def test_missing_client_ts_rejected(self):
		with self.assertRaises(ClientTimestampError):
			call(sample_write, str(uuid.uuid4()), value=1)
		self.assertEqual(CALLS, [])

	def test_replay_returns_stored_response_without_rerun(self):
		key = str(uuid.uuid4())
		first = call(sample_write, key, value="a", client_ts=TS, cmd="tracecore.x")
		second = call(sample_write, key, value="a", client_ts=TS)
		self.assertEqual(first, {"echo": "a", "n": 1})
		self.assertEqual(second, first)
		self.assertEqual(CALLS, ["a"])
		row = frappe.get_doc("Idempotency Key", key)
		self.assertTrue(row.endpoint.endswith("sample_write"))
		self.assertEqual(row.user, "Administrator")
		self.assertEqual(row.client_ts, datetime(2026, 10, 19, 2, 0, 0))

	def test_same_key_different_payload_conflict(self):
		key = str(uuid.uuid4())
		call(sample_write, key, value="a", client_ts=TS)
		with self.assertRaises(idempotency.IdempotencyConflictError):
			call(sample_write, key, value="b", client_ts=TS)
		self.assertEqual(CALLS, ["a"])

	def test_same_key_other_user_conflict(self):
		key = str(uuid.uuid4())
		call(sample_write, key, value="a", client_ts=TS)
		frappe.set_user(make_user("idem-other@example.com"))
		try:
			with self.assertRaises(idempotency.IdempotencyConflictError):
				call(sample_write, key, value="a", client_ts=TS)
		finally:
			frappe.set_user("Administrator")

	def test_failed_call_does_not_store_key(self):
		key = str(uuid.uuid4())
		with self.assertRaises(frappe.ValidationError):
			call(failing_write, key, value="x", client_ts=TS)
		self.assertFalse(frappe.db.exists("Idempotency Key", key))
		self.assertFalse(frappe.db.exists("Instrument Set Type", "IDF"))

	def test_purge_expired(self):
		old_key, new_key = str(uuid.uuid4()), str(uuid.uuid4())
		call(sample_write, old_key, value="old", client_ts=TS)
		call(sample_write, new_key, value="new", client_ts=TS)
		frappe.db.set_value("Idempotency Key", old_key, "created_at", add_days(now_datetime(), -31))
		self.assertGreaterEqual(idempotency.purge_expired(30), 1)
		self.assertFalse(frappe.db.exists("Idempotency Key", old_key))
		self.assertTrue(frappe.db.exists("Idempotency Key", new_key))


class TestReplayHttpStatus(FrappeTestCase):
	"""Trả lời lặp lại của một từ chối nghiệp vụ mang lại mã HTTP của lần đầu (FEAT-018 D3)."""

	def setUp(self):
		CALLS.clear()
		frappe.local.response.pop("http_status_code", None)
		self.addCleanup(frappe.local.response.pop, "http_status_code", None)

	def status(self):
		return frappe.local.response.get("http_status_code")

	def replay(self, fn, value):
		"""Gọi `fn` hai lần cùng khóa; trả (lần đầu, lần replay) và để lại mã HTTP của lần replay."""
		key = str(uuid.uuid4())
		first = call(fn, key, value=value, client_ts=TS)
		frappe.local.response.pop("http_status_code", None)  # request mới chưa có mã HTTP
		return first, call(fn, key, value=value, client_ts=TS)

	def test_replay_of_rejection_restores_http_status(self):
		first, second = self.replay(rejecting_write, 409)
		self.assertEqual(second, first)
		self.assertEqual(CALLS, [409])  # replay không chạy lại hàm
		self.assertEqual(self.status(), 409)

	def test_replay_of_success_or_old_style_rejection_leaves_status_alone(self):
		for fn, value in ((sample_write, "a"), (status_less_rejection, "b")):
			with self.subTest(fn=fn.__name__):
				first, second = self.replay(fn, value)
				self.assertEqual(second, first)
				self.assertIsNone(self.status())

	def test_no_request_context_sets_nothing(self):
		idempotency._apply_stored_status({"ok": False, "error": {"http_status": 409}})
		self.assertIsNone(self.status())

	def test_malformed_stored_status_is_ignored(self):
		with request_headers({}):
			for stored in (
				{"ok": False, "error": {"http_status": None}},
				{"ok": False, "error": {"http_status": "409"}},
				{"ok": False, "error": {"http_status": True}},
				{"ok": False, "error": {"http_status": 200}},
				{"ok": False, "error": "text"},
				{"ok": True, "error": {"http_status": 409}},
				["not", "a", "dict"],
				None,
			):
				with self.subTest(stored=stored):
					idempotency._apply_stored_status(stored)
					self.assertIsNone(self.status())
