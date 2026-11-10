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
# FEAT-060 (ADR-015, A-131): mẫu phiếu & lịch giám sát, báo cáo tuân thủ & phản hồi khoa
SCREENS += [
	{
		"slug": "mau-phieu",
		"scr": "SCR-50",
		"uc": "UC-43",
		"label": "Audit Templates and Schedules",
		"group": "compliance",
		"roles": ("TC R01", "TC R10", "TC R11", "TC R13", "System Manager"),
		"script": "/assets/tracecore/js/ksnk/scr_50_mau_phieu.js",
	},
	{
		"slug": "tuan-thu",
		"scr": "SCR-53",
		"uc": "UC-45",
		"label": "Compliance Report",
		"group": "compliance",
		"roles": ("TC R01", "TC R11", "TC R13", "System Manager"),
		"script": "/assets/tracecore/js/ksnk/scr_53_tuan_thu.js",
	},
]
# FEAT-067 (A-136): vi sinh & đa kháng — import WHONET/CSV, nhập tay có xác nhận, chủng mới, kháng sinh đồ quý (UC-51);
# R13 chỉ thấy phần tổng hợp (không đọc chủng có mã người bệnh)
SCREENS += [
	{
		"slug": "vi-sinh",
		"scr": "SCR-59",
		"uc": "UC-51",
		"label": "Microbiology and MDRO",
		"group": "micro",
		"roles": ("TC R01", "TC R11", "TC R13", "System Manager"),
		"script": "/assets/tracecore/js/ksnk/scr_59_vi_sinh.js",
	},
]
# FEAT-059: đào tạo KSNK (HRMS Training), sinh viên thực tập (UC-42; R02 làm trên Desk — A-135 e)
SCREENS += [
	{
		"slug": "dao-tao",
		"scr": "SCR-49",
		"uc": "UC-42",
		"label": "IC Training and Improvement",
		"group": "program",
		"roles": ("TC R01", "TC R10", "TC R11", "TC R13", "System Manager"),
		"script": "/assets/tracecore/js/ksnk/scr_49_dao_tao.js",
	},
]


# FEAT-071 (A-137 j): phơi nhiễm nghề nghiệp & tiêm chủng (UC-55); R13 chỉ thấy số liệu tổng hợp, R02 ghi tiêm chủng
# trên Desk list Staff Immunization
SCREENS += [
	{
		"slug": "phoi-nhiem",
		"scr": "SCR-64",
		"uc": "UC-55",
		"label": "Exposure and Immunization",
		"group": "environment",
		"roles": ("TC R01", "TC R11", "TC R13", "System Manager"),
		"script": "/assets/tracecore/js/ksnk/scr_64_phoi_nhiem.js",
	},
]

# FEAT-066 (A-142 Q4): hóa chất KSNK theo khoa-tháng & đơn vị thuê ngoài (UC-46). R09 (kế toán vật tư) và R02 vào Page
# chỉ thấy màn này; R02, R10, R13 chỉ xem (quyền thật ở RPC và DocPerm)
PAGE_ROLES += ("TC R02", "TC R09")
OFFICE_ROLES += ("TC R02", "TC R09")
READ_ONLY_ROLES += ("TC R02",)
SCREENS += [
	{
		"slug": "hoa-chat",
		"scr": "SCR-54",
		"uc": "UC-46",
		"label": "Chemicals and Outsourcing",
		"group": "compliance",
		"roles": ("TC R01", "TC R02", "TC R09", "TC R10", "TC R11", "TC R13", "System Manager"),
		"script": "/assets/tracecore/js/ksnk/scr_54_hoa_chat.js",
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
