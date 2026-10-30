"""RPC tracecore.v1.costing.*: tra bảng định giá có hiệu lực tại một ngày (FEAT-045, FR-M7-03.1, API-M7-01, A-48 D6).

Chỉ đọc. Bản Nháp/Đã hủy không bao giờ được trả (UC-28 E3). Quyền: R01, R02, R09, R10, System Manager.
"""

import re

import frappe
from frappe import _
from frappe.utils import getdate

from tracecore.core import audit
from tracecore.core.errors import Block
from tracecore.costing import rates, sheet
from tracecore.v1._common import BadRequestError, reject_block, require_any_role

READ_ROLES = ("TC R01", "TC R02", "TC R09", "TC R10", "System Manager")
# UC-29 A1: R01 yêu cầu, R09 tính lại (FR-M7-03.2)
RECALC_ROLES = ("TC R01", "TC R09", "System Manager")


ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _date(value):
	"""Chỉ nhận ``YYYY-MM-DD``: `getdate` còn đọc dạng theo định dạng ngày của site (dd/mm hay mm/dd), dễ hiểu sai."""
	parsed = None
	if isinstance(value, str) and ISO_DATE.fullmatch(value):
		try:
			parsed = getdate(value)
		except Exception:
			parsed = None
	if not parsed:
		raise BadRequestError(_("date must be a date in YYYY-MM-DD form."))
	return parsed


@frappe.whitelist(methods=["GET"])
def rate_at(date=None):
	"""Bảng giá có hiệu lực tại `date`: ``{"ok", "version", "effective_from", "effective_to", "rates", "pack_norms"}``."""
	require_any_role(*READ_ROLES)
	version = rates.version_at(_date(date))
	if not version:
		return {
			"ok": True,
			"version": None,
			"effective_from": None,
			"effective_to": None,
			"rates": [],
			"pack_norms": [],
		}
	period = frappe.db.get_value(
		"Cost Rate Version", version, ["effective_from", "effective_to"], as_dict=True
	)
	return {"ok": True, "version": version, **period, **rates.snapshot(version)}


@frappe.whitelist(methods=["POST"])
def recalculate(source_doctype=None, source_name=None, rate_version=None, note=None):
	"""Tính lại giá thành mẻ/lô theo phiên bản giá đã duyệt khác, ghi chú bắt buộc (UC-29 A1, FR-M7-03.2, A-53 i).

	Tạo Cost Sheet mới (is_recalculation), giữ nguyên Cost Sheet chính và giá thành đã ghi vào gói:
	{"ok": true, "cost_sheet"} hoặc {"ok": false, "error"}.
	"""
	require_any_role(*RECALC_ROLES)
	if not sheet.finished(source_doctype, source_name):
		return reject_block(
			Block(
				"COST_SOURCE_NOT_FOUND",
				_("Load or wash batch not found"),
				_("{0} {1} does not exist.").format(source_doctype or "", source_name or ""),
				_("Choose an existing sterilization load or wash batch."),
			),
			"Cost Sheet",
		)
	if not rate_version or frappe.db.get_value(rates.DOCTYPE, rate_version, "docstatus") != 1:
		return reject_block(
			Block(
				"RATE_VERSION_NOT_APPROVED",
				_("Rate version not approved"),
				_("Cost rate version {0} is not approved.").format(rate_version or ""),
				_("Choose an approved cost rate version."),
			),
			"Cost Sheet",
		)
	note = (note or "").strip()
	if not note:
		return reject_block(
			Block(
				"NOTE_REQUIRED",
				_("Note required"),
				_("A recalculation needs a note on why another rate version is used."),
				_("Enter the note, then try again."),
			),
			"Cost Sheet",
		)
	name = sheet.build(source_doctype, source_name, rate_version=rate_version, note=note, recalculation=True)
	audit.log(
		"Create",
		"Cost Sheet",
		name,
		new={"source": f"{source_doctype} {source_name}", "rate_version": rate_version},
		reason=note,
	)
	return {"ok": True, "cost_sheet": name}
