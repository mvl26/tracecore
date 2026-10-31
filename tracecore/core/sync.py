"""Đồng bộ hàng đợi offline của trạm/PDA (ADR-003, FR-M9-06.1, FR-M9-06.3; A-40 Q2, D5).

Phát lại = kiosk gọi lại đúng RPC gốc với cùng ``X-Idempotency-Key`` và header ``X-TC-Replay: 1``. Khi một lần phát lại
bị từ chối nghiệp vụ (4xx) hoặc thiếu quyền (403), `record_conflict` ghi `Sync Conflict` (một dòng mỗi khóa) và hook
``tracecore_after_sync_conflict`` tạo NC cho R02; bản server giữ nguyên. Tham số lưu lại đã bỏ token và mã bệnh nhân.
"""

import json

import frappe
from frappe import _
from frappe.utils import now_datetime

from tracecore.core import extension, gs1
from tracecore.core.client_time import to_system_time

REPLAY_HEADER = "X-TC-Replay"
RESOLVE_ROLES = ("TC R02", "TC R01", "System Manager")
_SECRET_ARGS = ("token", "pin", "reviewer_proof", "approver_proof")


def is_replay() -> bool:
	try:
		return (frappe.get_request_header(REPLAY_HEADER) or "").strip() == "1"
	except Exception:
		return False


def _redacted(args):
	"""Bỏ token, PIN và mã BN rõ; GIỮ `patient_code_enc` (chỉ private key của server giải được): khi gói bị từ chối,
	đó là bản duy nhất của mã BN để R02 truy vết bệnh nhân (review C2)."""
	return {
		key: value
		for key, value in (args or {}).items()
		if key not in _SECRET_ARGS and key != "patient_code" and key != "cmd"
	}


def _ref(args):
	"""Đối tượng của giao dịch: gói theo Cycle ID, bộ theo Set ID; không rõ → (None, None)."""
	if args.get("cycle_id"):
		return "Pack", args["cycle_id"]
	if args.get("set_id"):
		scanned = gs1.parse_scan(args["set_id"])
		if scanned["type"] == "set":
			return "Set Unit", scanned["id"]
	return None, None


def record_conflict(
	endpoint, key, client_ts, args, error, http_status, ref_doctype=None, ref_name=None, session=None
):
	"""Ghi Sync Conflict cho lần phát lại bị từ chối (idempotent theo `key`); trả tên Sync Conflict."""
	existing = frappe.db.get_value("Sync Conflict", {"idempotency_key": key}, "name")
	if existing:
		return existing
	if not ref_doctype:
		ref_doctype, ref_name = _ref(args or {})
	session = session or {}
	user = session.get("user") or frappe.session.user
	doc = frappe.get_doc(
		{
			"doctype": "Sync Conflict",
			"station": session.get("station") or (args or {}).get("station"),
			"employee": session.get("employee") or frappe.db.get_value("Employee", {"user_id": user}, "name"),
			"user": user,
			"endpoint": endpoint,
			"idempotency_key": key,
			# giờ hệ thống (A-74): form Desk hiển thị thẳng, lưu UTC thì lệch 7 giờ
			"client_ts": to_system_time(client_ts) if client_ts else None,
			"synced_at": now_datetime(),
			"http_status": http_status,
			"error_code": (error or {}).get("code"),
			"ref_doctype": ref_doctype,
			"ref_name": ref_name,
			"client_state": json.dumps(_redacted(args), ensure_ascii=False, default=str, sort_keys=True),
			"server_state": json.dumps(error or {}, ensure_ascii=False, default=str, sort_keys=True),
			"status": "Open",
		}
	)
	doc.flags.ignore_links = True
	doc.insert(ignore_permissions=True)
	incidents = extension.run("tracecore_after_sync_conflict", doc)
	if incidents:
		doc.db_set("incident", incidents[0], update_modified=False)
	return doc.name


def resolve(name, note):
	"""R02 đóng xung đột: giữ bản server, ghi cách xử lý (FR-M9-06.3)."""
	if not set(RESOLVE_ROLES) & set(frappe.get_roles()):
		raise frappe.PermissionError(_("Only R02 or R01 can resolve a sync conflict."))
	note = (note or "").strip()
	if not note:
		frappe.throw(_("Enter how the conflict was handled."))
	doc = frappe.get_doc("Sync Conflict", name, for_update=True)
	if doc.status == "Resolved":
		frappe.throw(_("Sync conflict {0} is already resolved.").format(name))
	doc.update(
		{
			"status": "Resolved",
			"resolution_note": note,
			"resolved_by": frappe.session.user,
			"resolved_at": now_datetime(),
		}
	)
	doc.flags.tc_sync = True
	doc.flags.ignore_links = True  # ref của xung đột có thể là gói chưa từng được tạo
	doc.save(ignore_permissions=True)
	return doc.name


# --- Trang Xung đột đồng bộ cho người dùng khoa (A-74): câu dễ hiểu thay cho JSON ------------------------------

_OPERATIONS = {
	"tracecore.v1.pack.generate_cycle_id": "Packing: creating the pack code",
	"tracecore.v1.receive.submit_offline": "Receiving: recording the receipt",
	"tracecore.v1.usage.confirm": "Usage: recording that a pack was used",
}
_TODO = {
	"SESSION_INVALID": "The staff member was not signed in properly at that moment. Sign in again with the employee card, do this step again at the station, then press Resolve and write what was done.",
	"SESSION_EXPIRED": "The staff member was not signed in properly at that moment. Sign in again with the employee card, do this step again at the station, then press Resolve and write what was done.",
}
_DEFAULT_TODO = "Check the set or pack at the station. If the step was not done, do it again. Then press Resolve and write what was done."
_DETAILS = (
	("set_id", "Set"),
	("raw", "Scanned code"),
	("receipt", "Receipt"),
	("offline_cycle_id", "Pack code"),
	("pack_type", "Pack type"),
	("ci_batch", "Chemical indicator lot"),
	("confirmed_lines", "Instruments checked"),
)


def _loads(text) -> dict:
	try:
		value = json.loads(text or "{}")
	except ValueError:
		return {}
	return value if isinstance(value, dict) else {}


def readable(doc) -> dict:
	"""Nội dung dễ hiểu của một xung đột: thao tác, kết quả, lý do, việc cần làm và các thông tin đã nhập."""
	args, error = _loads(doc.client_state), _loads(doc.server_state)
	details = []
	for key, label in _DETAILS:
		value = args.get(key)
		if isinstance(value, list):
			value = ", ".join(str(item) for item in value)
		if value:
			details.append({"label": _(label), "value": str(value)})
	return {
		"operation": _(_OPERATIONS.get(doc.endpoint, "A step done while the station was offline")),
		"outcome": _("This step was NOT recorded in the system."),
		"reason": " ".join(
			text for text in (_(error.get("title") or ""), _(error.get("reason") or "")) if text
		)
		or _("The server refused this step."),
		"todo": _(_TODO.get(error.get("code"), _DEFAULT_TODO)),
		"details": details,
	}
