"""Khoa gửi yêu cầu lấy đồ bẩn về KSNK (FEAT-100, A-160, FR-M2-26; cổng khoa của Page tc-flow).

Yêu cầu chỉ là thông báo cho KSNK: KHÔNG đổi trạng thái Set Unit hay Pack và không gọi ``core.step_gate``; bộ chỉ đổi
trạng thái khi KTV quét tiếp nhận tại T1 (BRU-FLOW-003), bộ chưa dùng về T1 vẫn tính Trả không sử dụng (FR-M2-01.3).
Trạng thái của yêu cầu suy ra lúc đọc: một bộ là "đã tiếp nhận" khi có dòng `Dirty Receipt Item` tạo sau thời điểm gửi
(phiếu không bị bỏ); code tiếp nhận T1 không biết tới yêu cầu.
"""

import frappe
from frappe import _
from frappe.utils import add_days, get_fullname, getdate, now_datetime

from tracecore.reprocessing import usage as usage_service

CONDITIONS = ("Complete", "Missing instruments", "Damaged", "Sharps inside")
WAITING, PARTLY, RECEIVED = "Waiting", "Partly received", "Received"

# bộ của dòng yêu cầu đã được T1 tiếp nhận sau thời điểm gửi
_RECEIVED_SQL = """exists (
	select 1 from `tabDirty Receipt Item` item
	join `tabDirty Receipt` receipt on receipt.name = item.parent and item.parenttype = 'Dirty Receipt'
	where item.set_unit = line.set_unit and ifnull(receipt.abandoned, 0) = 0
		and item.creation >= request.requested_at)"""


class ReturnRejected(Exception):
	"""Từ chối nghiệp vụ: kết quả (title) → lý do (reason) → hành động (action)."""

	def __init__(self, code, reason, action):
		super().__init__(code)
		self.code = code
		self.title = _("The pickup request was not sent")
		self.reason = reason
		self.action = action

	def as_dict(self):
		return {"code": self.code, "title": self.title, "reason": self.reason, "action": self.action}


def pending_sets(department):
	"""Set ID của khoa đang nằm trong yêu cầu đã gửi mà T1 chưa tiếp nhận."""
	rows = frappe.db.sql(
		f"""select distinct line.set_unit from `tabDirty Return Request Item` line
		join `tabDirty Return Request` request
			on request.name = line.parent and line.parenttype = 'Dirty Return Request'
		where request.docstatus = 1 and request.department = %s and not {_RECEIVED_SQL}""",  # nosec B608
		(department,),
	)
	return {row[0] for row in rows}


def _sets_at(department):
	"""Bộ của khoa có thể trả: gói đang tại khoa (chưa dùng) rồi gói đã dùng mà bộ chưa về T1; mỗi bộ một dòng."""
	overview = usage_service.department_overview(department)
	sources = [(row, False) for row in overview["at_department"]]
	sources += [(row, True) for row in overview["waiting_return"]]
	if not sources:
		return []
	packs = {
		row.name: row
		for row in frappe.get_all(
			"Pack",
			filters={"name": ["in", [row["cycle_id"] for row, _used in sources]]},
			fields=["name", "set_unit", "set_type"],
		)
	}
	rows, seen = [], set()
	for source, used in sources:
		pack = packs.get(source["cycle_id"])
		if not pack or not pack.set_unit or pack.set_unit in seen:
			continue
		seen.add(pack.set_unit)
		rows.append(
			{
				"set_id": pack.set_unit,
				"set_type": pack.set_type,
				"set_name": source.get("set_name") or pack.set_type,
				"cycle_id": pack.name,
				"used": used,
			}
		)
	return rows


def candidates(department):
	"""Bộ có thể trả của khoa, trừ bộ đã nằm trong yêu cầu đang chờ KSNK lấy (FR-M2-26.2)."""
	waiting = pending_sets(department)
	return [row for row in _sets_at(department) if row["set_id"] not in waiting]


def _lines(items):
	if isinstance(items, str):
		try:
			items = frappe.parse_json(items)
		except Exception:
			items = None
	lines = [line for line in items if isinstance(line, dict)] if isinstance(items, list) else []
	if not lines:
		raise ReturnRejected(
			"NO_SETS",
			_("No set was chosen."),
			_("Tick at least one set, then send the request again."),
		)
	return lines


def create(department, items, client_ts=None):
	"""Ghi sổ một yêu cầu lấy đồ bẩn cho các bộ ``[{"set_id", "condition"}]``; trả ``{"request", "set_count"}``."""
	lines = _lines(items)
	available = {row["set_id"]: row for row in candidates(department)}
	chosen = []
	for line in lines:
		set_id = str(line.get("set_id") or "")
		condition = line.get("condition") or CONDITIONS[0]
		if condition not in CONDITIONS:
			raise ReturnRejected(
				"CONDITION_INVALID",
				_("The condition on return of set {0} is not valid.").format(set_id),
				_("Choose the condition again, then send the request again."),
			)
		if set_id in {row["set_unit"] for row in chosen}:
			raise ReturnRejected(
				"SET_REPEATED",
				_("Set {0} is in the request twice.").format(set_id),
				_("Refresh the list, then send the request again."),
			)
		row = available.get(set_id)
		if not row:
			raise ReturnRejected(
				"SET_NOT_RETURNABLE",
				_("Set {0} is not at this department or is already in a request waiting for pickup.").format(
					set_id
				),
				_("Refresh the list and choose again."),
			)
		chosen.append(
			{
				"set_unit": set_id,
				"set_type": row["set_type"],
				"set_name": row["set_name"],
				"pack": row["cycle_id"],
				"used": 1 if row["used"] else 0,
				"return_condition": condition,
			}
		)
	user = frappe.session.user
	doc = frappe.get_doc(
		{
			"doctype": "Dirty Return Request",
			"department": department,
			"department_name": frappe.db.get_value("Department", department, "department_name"),
			"requested_by": user,
			"requested_by_name": get_fullname(user),
			"requested_at": now_datetime(),
			"client_ts": client_ts,
			"set_count": len(chosen),
			"items": chosen,
		}
	)
	doc.flags.tc_dirty_return = True
	doc.insert(ignore_permissions=True)
	doc.submit()
	return {"request": doc.name, "set_count": len(chosen)}


def requests_on(department, day):
	"""Yêu cầu khoa đã gửi trong ngày ``day``, mới nhất trước, kèm số bộ T1 đã tiếp nhận và trạng thái."""
	start = getdate(day)
	rows = frappe.db.sql(
		f"""select request.name as request, request.requested_at, request.requested_by_name,
			count(*) as set_count, sum(case when {_RECEIVED_SQL} then 1 else 0 end) as received_count
		from `tabDirty Return Request` request
		join `tabDirty Return Request Item` line
			on line.parent = request.name and line.parenttype = 'Dirty Return Request'
		where request.docstatus = 1 and request.department = %s
			and request.requested_at >= %s and request.requested_at < %s
		group by request.name, request.requested_at, request.requested_by_name
		order by request.requested_at desc, request.name desc""",  # nosec B608
		(department, start, add_days(start, 1)),
		as_dict=True,
	)
	for row in rows:
		row["set_count"] = int(row["set_count"] or 0)
		row["received_count"] = int(row["received_count"] or 0)
		if row["received_count"] >= row["set_count"]:
			row["status"] = RECEIVED
		else:
			row["status"] = PARTLY if row["received_count"] else WAITING
	return rows


def sets_on(department, day):
	"""Từng bộ khoa đã gửi trong ngày ``day`` (mỗi bộ một dòng, mới gửi trước) kèm tình trạng và đã về T1 chưa."""
	start = getdate(day)
	rows = frappe.db.sql(
		f"""select line.set_unit as set_id, line.set_type, line.set_name, line.return_condition as `condition`,
			request.name as request, request.requested_at, request.requested_by_name,
			case when {_RECEIVED_SQL} then 1 else 0 end as received
		from `tabDirty Return Request` request
		join `tabDirty Return Request Item` line
			on line.parent = request.name and line.parenttype = 'Dirty Return Request'
		where request.docstatus = 1 and request.department = %s
			and request.requested_at >= %s and request.requested_at < %s
		order by request.requested_at desc, request.name desc, line.idx asc""",  # nosec B608
		(department, start, add_days(start, 1)),
		as_dict=True,
	)
	for row in rows:
		row["received"] = bool(row["received"])
	return rows
