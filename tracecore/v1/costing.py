"""RPC tracecore.v1.costing.*: tra bảng định giá có hiệu lực tại một ngày (FEAT-045, FR-M7-03.1, API-M7-01, A-48 D6).

Chỉ đọc. Bản Nháp/Đã hủy không bao giờ được trả (UC-28 E3). Quyền: R01, R02, R09, R10, System Manager.
"""

import re

import frappe
from frappe import _
from frappe.utils import getdate

from tracecore.costing import rates
from tracecore.v1._common import BadRequestError, require_any_role

READ_ROLES = ("TC R01", "TC R02", "TC R09", "TC R10", "System Manager")


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
