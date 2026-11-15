"""Khoa gửi đề nghị cấp bộ dụng cụ (FEAT-101, A-161, FR-M2-27; cổng khoa của Page tc-flow, UC-12 phía khoa).

Đề nghị chỉ là thông báo cho KSNK: KHÔNG giữ chỗ gói, không đổi trạng thái gói hay bộ; cấp phát vẫn làm tại T7. Trạng
thái đề nghị suy ra lúc đọc từ phiếu cấp phát (`Issue Note`) đã ghi sổ cho khoa sau thời điểm gửi: đủ số gói của loại bộ
thì "đã cấp". Code cấp phát T7 không biết tới đề nghị.
"""

import frappe
from frappe import _
from frappe.utils import add_days, add_to_date, cint, get_datetime, get_fullname, getdate, now_datetime

from tracecore.reprocessing import issuing

MAX_QTY = 99
SET_TYPE_LIMIT = 500
WAITING, PARTLY, ISSUED = "Waiting", "Partly issued", "Issued"

# số gói của loại bộ đã cấp phát cho khoa sau thời điểm gửi đề nghị
_ISSUED_SQL = """(select count(*) from `tabIssue Note Pack` line
	join `tabIssue Note` note on note.name = line.parent and line.parenttype = 'Issue Note'
	join `tabPack` pack on pack.name = line.pack
	where note.docstatus = 1 and note.department = request.department
		and pack.set_type = request.set_type and note.creation >= request.requested_at)"""


class RequestRejected(Exception):
	"""Từ chối nghiệp vụ: kết quả (title) → lý do (reason) → hành động (action)."""

	def __init__(self, code, reason, action):
		super().__init__(code)
		self.code = code
		self.title = _("The issue request was not sent")
		self.reason = reason
		self.action = action

	def as_dict(self):
		return {"code": self.code, "title": self.title, "reason": self.reason, "action": self.action}


def options(department):
	"""Loại bộ khoa có thể đề nghị kèm tồn khoa, cơ số và tồn kho vô khuẩn (cùng số liệu màn cấp phát T7)."""
	par = {row["set_type"]: row for row in issuing.context(department)["rows"]}
	rows = []
	for set_type in frappe.get_all(
		"Instrument Set Type",
		fields=["name", "set_type_name"],
		order_by="set_type_name asc, name asc",
		limit=SET_TYPE_LIMIT,
	):
		known = par.get(set_type.name) or {}
		rows.append(
			{
				"set_type": set_type.name,
				"set_name": set_type.set_type_name or set_type.name,
				"stock": cint(known.get("stock")),
				"min": known.get("min"),
				"max": known.get("max"),
				"available": cint(known.get("available")),
			}
		)
	return rows


def _quantity(value):
	text = str(value if value is not None else "").strip()
	if not text.isdigit() or not 1 <= int(text) <= MAX_QTY:
		raise RequestRejected(
			"QTY_INVALID",
			_("The quantity must be a whole number from 1 to {0}.").format(MAX_QTY),
			_("Enter the quantity again, then send the request again."),
		)
	return int(text)


def _needed_by(value):
	try:
		needed = get_datetime(value) if value else None
	except Exception:
		needed = None
	if not needed or not isinstance(value, str):
		raise RequestRejected(
			"NEEDED_BY_INVALID",
			_("The time the sets are needed is missing or not valid."),
			_("Choose the date and time again, then send the request again."),
		)
	if needed < add_to_date(now_datetime(), minutes=-1):
		raise RequestRejected(
			"NEEDED_BY_PAST",
			_("The time the sets are needed is already past."),
			_("Choose a later date and time, then send the request again."),
		)
	return needed


def create(department, set_type, qty, needed_by, client_ts=None):
	"""Ghi sổ một đề nghị cấp; trả ``{"request", "qty"}``. Không đổi trạng thái gói hay bộ (FR-M2-27.1)."""
	known = next((row for row in options(department) if row["set_type"] == set_type), None)
	if not known:
		raise RequestRejected(
			"SET_TYPE_INVALID",
			_("Set type {0} does not exist.").format(set_type or "-"),
			_("Choose a set type from the list, then send the request again."),
		)
	quantity = _quantity(qty)
	needed = _needed_by(needed_by)
	user = frappe.session.user
	doc = frappe.get_doc(
		{
			"doctype": "Set Issue Request",
			"department": department,
			"department_name": frappe.db.get_value("Department", department, "department_name"),
			"set_type": set_type,
			"set_name": known["set_name"],
			"qty": quantity,
			"needed_by": needed,
			"par_min": known["min"],
			"par_max": known["max"],
			"stock_at_request": known["stock"],
			"requested_by": user,
			"requested_by_name": get_fullname(user),
			"requested_at": now_datetime(),
			"client_ts": client_ts,
		}
	)
	doc.flags.tc_issue_request = True
	doc.insert(ignore_permissions=True)
	doc.submit()
	return {"request": doc.name, "qty": quantity}


def requests_on(department, day):
	"""Đề nghị khoa đã gửi trong ngày ``day``, mới nhất trước, kèm số gói đã cấp sau đó và trạng thái."""
	start = getdate(day)
	rows = frappe.db.sql(
		f"""select request.name as request, request.set_type, request.set_name, request.qty,
			request.needed_by, request.requested_at, request.requested_by_name,
			{_ISSUED_SQL} as issued_count
		from `tabSet Issue Request` request
		where request.docstatus = 1 and request.department = %s
			and request.requested_at >= %s and request.requested_at < %s
		order by request.requested_at desc, request.name desc""",  # nosec B608
		(department, start, add_days(start, 1)),
		as_dict=True,
	)
	for row in rows:
		row["qty"] = cint(row["qty"])
		row["issued_count"] = min(cint(row["issued_count"]), row["qty"])
		if row["issued_count"] >= row["qty"]:
			row["status"] = ISSUED
		else:
			row["status"] = PARTLY if row["issued_count"] else WAITING
	return rows
