"""Nhóm phẫu thuật giám sát NKVM khởi tạo (FEAT-064; FR-M13-07; D10, NFR-MAINT-04, OQ-V12-09; A-147 a).

Chạy ở ``after_install`` / ``after_migrate``; chỉ chèn mã còn thiếu, không ghi đè bản bệnh viện đã sửa. Mọi nhóm khởi
tạo ``is_monitored = 0`` (Nháp): R01 cùng chuyên gia KSNK rà soát T, cửa sổ và lịch theo dõi theo QĐ 1526/QĐ-BYT rồi bật
giám sát. Tên tiếng Anh, lưu bản tiếng Việt từ ``vi.csv``.
"""

import frappe

GROUP = "Surgical Procedure Group"
LANG = "vi"
SHORT = ((7, "Phone"), (30, "Phone"))
LONG = ((7, "Phone"), (30, "Phone"), (90, "Revisit"))
# mã: (tên, T phút, cấy ghép)
GROUPS = {
	"APPY": ("Appendectomy", 60, 0),
	"CHOL": ("Cholecystectomy", 120, 0),
	"COLO": ("Colon surgery", 180, 0),
	"CSEC": ("Caesarean section", 60, 0),
	"HPRO": ("Hip prosthesis", 120, 1),
	"KPRO": ("Knee prosthesis", 120, 1),
}
CODES = tuple(GROUPS)


def source_texts():
	return [title for title, _t, _implant in GROUPS.values()]


def rows():
	return [
		{
			"group_code": code,
			"group_name": frappe._(title, LANG),
			"t_time_minutes": t_time,
			"has_implant": implant,
			"followup_days": "90" if implant else "30",
			"is_monitored": 0,
			"followups": [
				{"day_offset": day, "method": method} for day, method in (LONG if implant else SHORT)
			],
		}
		for code, (title, t_time, implant) in GROUPS.items()
	]


def ensure_seed():
	"""Hook ``after_install`` / ``after_migrate``; trả mã các nhóm vừa tạo."""
	created = []
	for row in rows():
		if frappe.db.exists(GROUP, row["group_code"]):
			continue
		frappe.get_doc({**row, "doctype": GROUP}).insert(ignore_permissions=True)
		created.append(row["group_code"])
	return created
