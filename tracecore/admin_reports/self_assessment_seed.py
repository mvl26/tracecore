"""Chỉ tiêu QĐ 38/QĐ-BYT khởi tạo cho tự đánh giá năm (FEAT-065; FR-M9-29; NFR-MAINT-04; A-145 Q1, D8).

Chạy ở ``after_migrate`` và patch ``a145_qd38_criteria``. Chỉ **chèn mã còn thiếu**: chỉ tiêu bệnh viện đã sửa, đã ngưng
(`is_active` = 0) không bị ghi lại. Nội dung là bản khởi đầu theo các nhóm chỉ tiêu QĐ 38 (SRS §2.4: kế hoạch, đào tạo,
hóa chất quý, NKVM/NK hồi sức, kháng thuốc, phòng cách ly, cải tiến chất lượng, ứng dụng công nghệ); R01 rà soát tại
bệnh viện. Nguồn tiếng Anh, lưu bản tiếng Việt từ ``translations/vi.csv``.
"""

import frappe
from frappe import _

DOCTYPE = "IC QD38 Criterion"
# (mã, nội dung, nguồn dữ liệu, check_method)
CRITERIA = (
	(
		"QD38-PLAN",
		"Annual infection control plan approved",
		"M11 Infection control program",
		"ic_plan_approved",
	),
	("QD38-TRAIN", "Staff trained in infection control as planned", "M11 Training", ""),
	(
		"QD38-CHEM",
		"Quarterly report of hand hygiene product consumption",
		"M12 IC Chemical Consumption",
		"ic_chemical_quarterly",
	),
	(
		"QD38-HAI",
		"Surveillance and reports of surgical site infection and ICU infection",
		"M13 HAI surveillance",
		"hai_surveillance_active",
	),
	(
		"QD38-AMR",
		"Participation in national antimicrobial resistance surveillance",
		"M14 WHONET export",
		"amr_surveillance",
	),
	("QD38-ISO", "Isolation rooms meet requirements", "M14 Isolation", "isolation_rooms"),
	("QD38-QI", "Infection control quality improvement projects completed", "M11 Improvement projects", ""),
	("QD38-IT", "Information technology applied in infection control", "Manual entry with evidence", ""),
)


def ensure_seed():
	if not frappe.db.table_exists(DOCTYPE):
		return
	for order, (code, criterion, source_hint, check_method) in enumerate(CRITERIA, start=1):
		if frappe.db.exists(DOCTYPE, code):
			continue
		frappe.get_doc(
			{
				"doctype": DOCTYPE,
				"criterion_code": code,
				"criterion": _(criterion, "vi"),
				"source_hint": _(source_hint, "vi"),
				"check_method": check_method,
				"sort_order": order * 10,
				"is_active": 1,
			}
		).insert(ignore_permissions=True)
