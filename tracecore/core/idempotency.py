"""Idempotency cho RPC của trạm/PDA/agent (ADR-003, F-9, EI-SW-004).

Mỗi request mang header ``X-Idempotency-Key`` (UUID) và tham số ``client_ts``.
Gửi lại cùng key + cùng dữ liệu → trả lại response đã lưu, không chạy lại.
"""

import functools
import hashlib
import json
import re

import frappe
from frappe import _
from frappe.utils import add_days, now_datetime

from tracecore.core.client_time import parse_client_ts

KEY_HEADER = "X-Idempotency-Key"
TTL_DAYS = 30
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


class IdempotencyKeyError(frappe.ValidationError):
	http_status_code = 400


class IdempotencyConflictError(frappe.ValidationError):
	http_status_code = 409


def _header(name):
	try:
		return frappe.get_request_header(name)
	except Exception:
		return None


def _request_hash(endpoint, kwargs):
	body = json.dumps({"endpoint": endpoint, "args": kwargs}, sort_keys=True, default=str)
	return hashlib.sha256(body.encode()).hexdigest()


def _station():
	station = _header("X-TC-Station")
	return station if station and frappe.db.exists("Zone Station", station) else None


def _stored_response(key, endpoint, request_hash, for_update=False):
	row = frappe.db.get_value(
		"Idempotency Key",
		key,
		["user", "endpoint", "request_hash", "response"],
		as_dict=True,
		for_update=for_update,
	)
	if not row:
		return False, None
	if row.user != frappe.session.user or row.endpoint != endpoint or row.request_hash != request_hash:
		raise IdempotencyConflictError(
			_("X-Idempotency-Key {0} was already used for a different request.").format(key)
		)
	return True, frappe.parse_json(row.response) if row.response else None


def idempotent(fn):
	"""Decorator cho whitelisted method: ``@frappe.whitelist()`` đặt bên ngoài."""
	endpoint = f"{fn.__module__}.{fn.__qualname__}"

	@functools.wraps(fn)
	def wrapper(*args, **kwargs):
		key = (_header(KEY_HEADER) or "").strip()
		if not _UUID.fullmatch(key):
			raise IdempotencyKeyError(_("Missing or invalid X-Idempotency-Key header."))
		client_ts = parse_client_ts(kwargs.get("client_ts"))
		kwargs.pop("cmd", None)
		request_hash = _request_hash(endpoint, kwargs)

		found, response = _stored_response(key, endpoint, request_hash)
		if found:
			return response

		savepoint = "tc_idem_" + key.replace("-", "")[:16]
		frappe.db.savepoint(savepoint)
		try:
			frappe.get_doc(
				{
					"doctype": "Idempotency Key",
					"key": key,
					"endpoint": endpoint,
					"user": frappe.session.user,
					"station": _station(),
					"request_hash": request_hash,
					"created_at": now_datetime(),
					"client_ts": client_ts,
				}
			).insert(ignore_permissions=True)
		except frappe.DuplicateEntryError:
			# Request song song cùng key đã commit trước (insert chờ khóa unique tới khi bên kia commit)
			frappe.db.rollback(save_point=savepoint)
			if frappe.local.message_log and key in str(frappe.local.message_log[-1]):
				frappe.clear_last_message()  # msgprint "... already exists" do db_insert thêm
			# REPEATABLE READ: đọc có khóa để thấy dòng vừa commit, không đọc snapshot cũ
			return _stored_response(key, endpoint, request_hash, for_update=True)[1]

		try:
			result = frappe.call(fn, *args, **kwargs)
			frappe.db.set_value(
				"Idempotency Key", key, "response", frappe.as_json(result), update_modified=False
			)
		except Exception:
			frappe.db.rollback(save_point=savepoint)
			raise
		return result

	return wrapper


def purge_expired(days=TTL_DAYS):
	"""Xóa khóa quá hạn (scheduler hằng ngày); trả số dòng đã xóa."""
	cutoff = add_days(now_datetime(), -int(days))
	names = frappe.get_all("Idempotency Key", filters={"created_at": ("<", cutoff)}, pluck="name")
	if names:
		frappe.db.delete("Idempotency Key", {"name": ("in", names)})
	return len(names)
