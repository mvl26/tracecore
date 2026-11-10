"""Đơn vị thuê ngoài trên ERPNext Supplier và nhắc giấy phép (FEAT-066; FR-M12-13, FR-M12-13.1; BRU-AUD-006; UC-46).

Đơn vị thuê ngoài = Supplier có ``tc_ic_service_type`` (A-142 Q1). Job hằng ngày:

- giấy phép còn đúng 60, 30, 7 ngày → ``IC_VENDOR_LICENSE_EXPIRING`` (R01, R02), một lần mỗi mốc;
- giấy phép đã hết hạn → ``IC_VENDOR_LICENSE_EXPIRED`` + Audit Log, một lần cho mỗi ngày hết hạn; **chỉ cảnh báo**,
  không chặn phiếu giám sát hay giao dịch (BRU-AUD-006 — quyết định dừng hợp đồng thuộc bệnh viện);
- ngày 1 tháng cuối quý → ``IC_VENDOR_UNAUDITED`` liệt kê đơn vị còn hợp đồng chưa có phiếu "Đơn vị thuê ngoài"
  đã ghi sổ trong quý.

Đơn vị xử lý chất thải vẫn quản lý hợp đồng/giấy phép môi trường ở `Waste Treatment Vendor` (M10, BRU-WST-003): chỉ
đọc tham chiếu qua ``frappe.db`` (không import M10).
"""

import frappe
from frappe import _
from frappe.utils import date_diff, formatdate, get_last_day, getdate, today

from tracecore.core import audit, notification

EXPIRING_EVENT = "IC_VENDOR_LICENSE_EXPIRING"
EXPIRED_EVENT = "IC_VENDOR_LICENSE_EXPIRED"
UNAUDITED_EVENT = "IC_VENDOR_UNAUDITED"
NOTICE_DAYS = (60, 30, 7)
VALID, EXPIRING, EXPIRED, UNKNOWN = "Valid", "Expiring", "Expired", "Unknown"
VENDOR_AUDIT_TYPE = "Outsourced Service"
WASTE_VENDOR = "Waste Treatment Vendor"
FIELDS = (
	"name",
	"supplier_name",
	"tc_ic_service_type",
	"tc_license_no",
	"tc_license_expiry",
	"tc_contract_from",
	"tc_contract_to",
)


def vendors() -> list:
	return frappe.get_all(
		"Supplier",
		filters={"tc_ic_service_type": ["is", "set"], "disabled": 0},
		fields=list(FIELDS),
		order_by="supplier_name asc",
	)


def notice_days(expiry, day) -> int | None:
	"""Số ngày còn lại nếu ``day`` đúng là mốc nhắc 60/30/7 ngày của ``expiry``."""
	if not expiry:
		return None
	left = date_diff(expiry, day)
	return left if left in NOTICE_DAYS else None


def state_of(expiry, day) -> tuple[str, int | None]:
	"""(trạng thái, số ngày còn lại): Hết hạn khi đã qua ngày hết hạn; Sắp hết hạn trong 60 ngày."""
	if not expiry:
		return UNKNOWN, None
	left = date_diff(expiry, day)
	if left < 0:
		return EXPIRED, left
	return (EXPIRING if left <= max(NOTICE_DAYS) else VALID), left


def status(supplier, day=None) -> dict:
	expiry = frappe.db.get_value("Supplier", supplier, "tc_license_expiry")
	state, left = state_of(expiry, getdate(day or today()))
	return {"state": state, "days_left": left}


def expired_count(day=None) -> int:
	day = getdate(day or today())
	return sum(1 for row in vendors() if state_of(row.tc_license_expiry, day)[0] == EXPIRED)


def _quarter_range(year, quarter):
	start = getdate(f"{int(year)}-{int(quarter) * 3 - 2:02d}-01")
	return start, get_last_day(getdate(f"{int(year)}-{int(quarter) * 3:02d}-01"))


def _audited(start, end) -> set:
	return set(
		frappe.get_all(
			"Audit Session",
			filters={
				"docstatus": 1,
				"audit_type": VENDOR_AUDIT_TYPE,
				"supplier": ["is", "set"],
				"audit_date": ["between", [start, end]],
			},
			pluck="supplier",
		)
	)


def _under_contract(row, start, end) -> bool:
	if row.tc_contract_to and getdate(row.tc_contract_to) < start:
		return False
	return not (row.tc_contract_from and getdate(row.tc_contract_from) > end)


def unaudited(year, quarter) -> list[str]:
	"""Đơn vị còn hợp đồng trong quý chưa có phiếu "Đơn vị thuê ngoài" đã ghi sổ trong quý (FR-M12-13)."""
	start, end = _quarter_range(year, quarter)
	audited = _audited(start, end)
	return [row.name for row in vendors() if _under_contract(row, start, end) and row.name not in audited]


def last_session(supplier) -> dict | None:
	rows = frappe.get_all(
		"Audit Session",
		filters={"docstatus": 1, "supplier": supplier, "audit_type": VENDOR_AUDIT_TYPE},
		fields=["name", "audit_date", "score_pct", "result"],
		order_by="audit_date desc, creation desc",
		limit=1,
	)
	return rows[0] if rows else None


def waste_vendor_of(supplier) -> str | None:
	"""Hồ sơ M10 (`Waste Treatment Vendor`) gắn Supplier này — chỉ tham chiếu (UC-46 A2)."""
	if not frappe.db.exists("DocType", WASTE_VENDOR):
		return None
	return frappe.db.get_value(WASTE_VENDOR, {"supplier": supplier}, "name")


def overview(day=None) -> list[dict]:
	"""Bảng đơn vị thuê ngoài của SCR-54."""
	day = getdate(day or today())
	out = []
	for row in vendors():
		state, left = state_of(row.tc_license_expiry, day)
		out.append(
			{
				**row,
				"state": state,
				"days_left": left,
				"last_session": last_session(row.name),
				"waste_vendor": waste_vendor_of(row.name)
				if row.tc_ic_service_type == "Waste Treatment"
				else None,
			}
		)
	return out


# --- Nhắc (scheduler) -------------------------------------------------------------------------------------------------


def _sent(event, supplier, marker) -> bool:
	return bool(
		frappe.db.exists(
			"Notification Delivery", {"event_code": event, "ref_name": supplier, "message": marker}
		)
	)


def _remind_expiring(row, day):
	left = notice_days(row.tc_license_expiry, day)
	if left is None:
		return
	marker = _("The license of {0} ends in {1} days ({2}).").format(
		row.supplier_name, left, formatdate(row.tc_license_expiry)
	)
	if _sent(EXPIRING_EVENT, row.name, marker):
		return
	notification.emit(
		EXPIRING_EVENT,
		frappe._dict(doctype="Supplier", name=row.name),
		subject=_("Outsourced vendor license of {0} is close to expiry").format(row.supplier_name),
		message=marker,
	)


def _expired_logged(row) -> bool:
	return bool(
		frappe.db.exists(
			"Audit Log",
			{
				"ref_doctype": "Supplier",
				"ref_name": row.name,
				"action": "Update",
				"reason": ["like", f"%{row.tc_license_expiry}%"],
			},
		)
	)


def _warn_expired(row, day):
	if state_of(row.tc_license_expiry, day)[0] != EXPIRED or _expired_logged(row):
		return
	audit.log(
		"Update",
		"Supplier",
		row.name,
		new={"tc_license_state": EXPIRED, "tc_license_expiry": str(row.tc_license_expiry)},
		reason=f"license expired {row.tc_license_expiry}: warning only (BRU-AUD-006)",
	)
	notification.emit(
		EXPIRED_EVENT,
		frappe._dict(doctype="Supplier", name=row.name),
		subject=_("Outsourced vendor license of {0} has expired").format(row.supplier_name),
		message=_(
			"The license of {0} expired on {1}. The system only warns; stopping the contract is a hospital decision."
		).format(row.supplier_name, formatdate(row.tc_license_expiry)),
	)


def _remind_unaudited(day):
	quarter = (day.month - 1) // 3 + 1
	if day.day != 1 or day.month != quarter * 3:
		return
	names = unaudited(day.year, quarter)
	if not names:
		return
	labels = dict(
		frappe.get_all(
			"Supplier", filters={"name": ["in", names]}, fields=["name", "supplier_name"], as_list=True
		)
	)
	marker = _("Quarter {0}/{1}: no outsourced vendor audit yet for {2}.").format(
		quarter, day.year, ", ".join(labels.get(name, name) for name in names)
	)
	if frappe.db.exists("Notification Delivery", {"event_code": UNAUDITED_EVENT, "message": marker}):
		return
	notification.emit(
		UNAUDITED_EVENT,
		frappe._dict(doctype="Supplier", name=names[0]),
		subject=_("{0} outsourced vendor(s) not audited this quarter").format(len(names)),
		message=marker,
	)


def run_daily(day=None):
	"""Job hằng ngày (scheduler ``daily``)."""
	day = getdate(day or today())
	for row in vendors():
		_remind_expiring(row, day)
		_warn_expired(row, day)
	_remind_unaudited(day)


def warn_expired_license(doc, method=None):
	"""``Audit Session.validate``: đơn vị gắn phiếu đã hết hạn giấy phép → chỉ báo, không chặn (BRU-AUD-006)."""
	if not doc.get("supplier") or doc.docstatus != 0:
		return
	state = status(doc.supplier, doc.audit_date)
	if state["state"] == EXPIRED:
		frappe.msgprint(
			_(
				"The license of vendor {0} has expired. The audit can still be saved; this is only a warning."
			).format(doc.supplier),
			indicator="orange",
			alert=True,
		)
