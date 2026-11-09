"""Registry màn của màn quản lý KSNK toàn viện — Page `tc-ksnk` (FEAT-056; A-131 a, b, e).

Mỗi FEAT 057..074 thêm màn WEB của mình vào ``SCREENS`` (slug, mã SCR/UC, nhãn, nhóm, vai trò, file JS). Menu chỉ là
hiển thị: quyền thật vẫn ở RPC và DocPerm. Số việc chờ trên menu do module đăng ký qua hook ``tracecore_ksnk_badges``
(mỗi hàm nhận ``user`` và trả ``{slug: số}``), gọi một lần cho cả menu.
"""

import frappe
from frappe import _

from tracecore.core import extension

BADGE_HOOK = "tracecore_ksnk_badges"
PAGE_ROLES = ("TC R01", "TC R10", "TC R11", "TC R12", "TC R13", "System Manager")
OFFICE_ROLES = ("TC R01", "TC R10", "TC R11", "TC R13", "System Manager")
READ_ONLY_ROLES = ("TC R13",)
DEPT_ROLES = ("TC R12",)

# nhóm rail theo bản giao diện v1.12 (SCR-66): (khóa, nhãn tiếng Anh — dịch qua vi.csv)
GROUPS = (
	("program", "Hospital IC"),
	("compliance", "Compliance Monitoring"),
	("hai", "HAI Surveillance"),
	("micro", "Microbiology and Isolation"),
	("environment", "Environment and Occupational Safety"),
)

SCREENS = [
	{
		"slug": "chi-so",
		"scr": "SCR-66",
		"uc": "UC-57",
		"label": "IC Indicator Board",
		"group": "program",
		"roles": ("TC R01", "TC R10", "TC R11", "TC R13", "System Manager"),
		"script": "/assets/tracecore/js/ksnk/scr_66_chi_so.js",
	},
	# FEAT-057: cơ cấu KSNK — cài đặt chương trình, Hội đồng, mạng lưới (UC-40; R02 sửa mạng lưới trên Desk form)
	{
		"slug": "co-cau",
		"scr": "SCR-47",
		"uc": "UC-40",
		"label": "IC Structure",
		"group": "program",
		"roles": ("TC R01", "TC R10", "TC R11", "TC R13", "System Manager"),
		"script": "/assets/tracecore/js/ksnk/scr_47_co_cau.js",
	},
]
# FEAT-058: kế hoạch năm, văn bản nội bộ, họp Hội đồng (UC-41; R13 ghi sổ kế hoạch ngay trên màn)
SCREENS += [
	{
		"slug": "ke-hoach",
		"scr": "SCR-48",
		"uc": "UC-41",
		"label": "Plans and Documents",
		"group": "program",
		"roles": ("TC R01", "TC R10", "TC R11", "TC R13", "System Manager"),
		"script": "/assets/tracecore/js/ksnk/scr_48_ke_hoach.js",
	},
]


def _badges(user):
	total: dict[str, int] = {}
	for result in extension.run(BADGE_HOOK, user):
		for slug, count in (result or {}).items():
			total[slug] = total.get(slug, 0) + int(count or 0)
	return total


def _departments():
	"""Khoa cho bộ lọc (Department có tc_is_ward). Chỉ gọi cho vai trò văn phòng KSNK (toàn viện), không có R12; danh
	sách tên khoa không nhạy cảm nên không đòi quyền đọc Department của ERPNext."""
	return frappe.get_all(
		"Department",
		filters={"tc_is_ward": 1, "disabled": 0, "is_group": 0},
		fields=["name", "department_name"],
		order_by="department_name asc",
		limit_page_length=0,
	)


def nav(user=None):
	"""Menu theo vai trò người dùng: ``{groups, home, read_only, dept_only, departments}``."""
	user = user or frappe.session.user
	roles = set(frappe.get_roles(user))
	if not roles & set(PAGE_ROLES):
		frappe.throw(_("You are not allowed to open infection control management."), frappe.PermissionError)
	if not roles & set(OFFICE_ROLES):
		# R12 làm việc trên Cổng khoa (A-131 e); màn này không có mục nào cho R12
		return {"groups": [], "home": "", "read_only": True, "dept_only": True, "departments": []}
	badges = _badges(user)
	groups = []
	for key, label in GROUPS:
		items = [
			{
				"slug": screen["slug"],
				"scr": screen["scr"],
				"uc": screen["uc"],
				"label": _(screen["label"]),
				"script": screen["script"],
				"badge": badges.get(screen["slug"], 0),
			}
			for screen in SCREENS
			if screen["group"] == key and roles & set(screen["roles"])
		]
		if items:
			groups.append({"key": key, "label": _(label), "items": items})
	home = groups[0]["items"][0]["slug"] if groups else ""
	if any(item["slug"] == "chi-so" for group in groups for item in group["items"]):
		home = "chi-so"  # R13: trang chủ là bảng chỉ số (A-131 e)
	return {
		"groups": groups,
		"home": home,
		"read_only": not (roles & (set(OFFICE_ROLES) - set(READ_ONLY_ROLES))),
		"dept_only": False,
		"departments": _departments(),
	}
