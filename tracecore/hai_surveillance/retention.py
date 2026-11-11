"""Xóa định danh dữ liệu người bệnh M13 khi hết thời hạn lưu (FEAT-063; NFR-PRIV-02; OQ-V12-07; A-144 Q3).

Thời hạn ``IC Program Settings.patient_data_retention_months`` do bệnh viện đặt (trống = không xóa). Hằng ngày:
`HAI Case` đã ghi sổ (Xác định / Loại trừ) có ngày khởi phát và `Device Episode` đã đóng có ngày rút cũ hơn thời hạn →
xóa mã người bệnh (Password trong ``__Auth``), hash, bản che, năm sinh; giữ khoa, ngày, trạng thái để số liệu tổng hợp
và `IC Indicator Value` đã khóa không đổi. Mỗi bản ghi một dòng Audit Log (không chứa mã).
"""

import frappe
from frappe.utils import add_months, cint, getdate, today
from frappe.utils.password import delete_all_passwords_for

from tracecore.core import audit

SETTINGS = "IC Program Settings"
CASE, EPISODE = "HAI Case", "Device Episode"
# cột Int không nhận NULL: năm sinh xóa thành 0 (không xác định)
CLEARED = {"patient_code": None, "patient_code_hash": None, "patient_code_masked": None, "birth_year": 0}
REASON = "Retention period expired (NFR-PRIV-02)"


def cutoff(day=None):
	months = cint(frappe.db.get_single_value(SETTINGS, "patient_data_retention_months"))
	if months <= 0:
		return None
	return add_months(getdate(day or today()), -months)


def _clear(doctype, name, extra=None):
	delete_all_passwords_for(doctype, name)
	frappe.db.set_value(doctype, name, {**CLEARED, **(extra or {})}, update_modified=False)
	audit.log("Update", doctype, name, new={"deidentified": 1}, reason=REASON)


def run(day=None):
	"""Scheduler hằng ngày; trả số bản ghi đã xóa định danh theo DocType."""
	limit = cutoff(day)
	result = {CASE: 0, EPISODE: 0}
	if not limit:
		return result
	for name in frappe.get_all(
		CASE,
		filters={"docstatus": 1, "deidentified": 0, "onset_date": ["<", limit]},
		pluck="name",
	):
		_clear(CASE, name, {"deidentified": 1})
		result[CASE] += 1
	for name in frappe.get_all(
		EPISODE,
		filters={
			"status": "Closed",
			"removed_on": ["<", limit],
			"patient_code_hash": ["is", "set"],
		},
		pluck="name",
	):
		_clear(EPISODE, name)
		result[EPISODE] += 1
	return result
