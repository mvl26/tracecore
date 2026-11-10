"""Bộ khởi tạo M15 (FEAT-070; BRU-ENV-001, BRU-ENV-002; NFR-MAINT-04; D10; OQ-V12-08, OQ-V12-09; A-148).

- 4 mức nguy cơ theo QĐ 3916 (Thấp, Trung bình, Cao, Rất cao) kèm số phiếu tối thiểu/tháng khởi đầu.
- Ngưỡng môi trường **Nháp** (ví dụ cấu hình, chờ chuyên gia KSNK xác nhận rồi R01 duyệt): không phải tiêu chí đã duyệt.
- Mẫu phiếu Nháp loại Cơ sở hạ tầng (thông khí, cấp nước) và An toàn thực phẩm (dòng FEAT-061: ATTP ở FEAT-070); chèn
  thẳng `Audit Template` qua ``frappe.get_doc`` (M15 không import M12), bộ 8 mẫu của FEAT-061 giữ nguyên.

Chạy ở ``after_install``/``after_migrate``: chỉ chèn bản còn thiếu theo khóa (tên mức, ``limit_code``, ``template_code``),
không ghi đè bản bệnh viện đã sửa hay đã duyệt. Nguồn tiếng Anh ở đây; văn bản lưu vào DB lấy bản tiếng Việt từ
``translations/vi.csv``.
"""

import frappe
from frappe.utils import today

from tracecore.environmental_hygiene import limits, zones

LANG = "vi"
QD3916 = "QD 3916/QD-BYT"
DRAFT_REF = "Draft example - to be confirmed by the infection control expert"

# tên mức, thứ tự, số phiếu tối thiểu/tháng, tính là nguy cơ cao
RISK_LEVELS = [
	{"risk_name": "Low risk", "sort_order": 10, "min_audits_per_month": 1, "is_high_risk": 0},
	{"risk_name": "Medium risk", "sort_order": 20, "min_audits_per_month": 2, "is_high_risk": 0},
	{"risk_name": "High risk", "sort_order": 30, "min_audits_per_month": 4, "is_high_risk": 1},
	{"risk_name": "Very high risk", "sort_order": 40, "min_audits_per_month": 8, "is_high_risk": 1},
]

# Giá trị chỉ là ví dụ cấu hình (OQ-V12-09); R01 sửa theo chuyên gia rồi ghi sổ (duyệt)
LIMITS = [
	{
		"limit_code": "OR-AIR",
		"title": "Operating room air - total aerobic count",
		"sample_type": "Air",
		"method": "Culture",
		"parameter": "Total aerobic count",
		"limit_value": 10,
		"unit": "CFU/m3",
	},
	{
		"limit_code": "OR-SURFACE",
		"title": "Operating room surface - total aerobic count",
		"sample_type": "Surface",
		"method": "Culture",
		"parameter": "Total aerobic count",
		"limit_value": 5,
		"unit": "CFU/25 cm2",
	},
	{
		"limit_code": "RO-WATER",
		"title": "Dialysis RO water - total aerobic count",
		"sample_type": "Clinical Water",
		"method": "Culture",
		"parameter": "Total aerobic count",
		"limit_value": 100,
		"unit": "CFU/ml",
	},
	{
		"limit_code": "DOMESTIC-WATER",
		"title": "Domestic water - coliforms",
		"sample_type": "Domestic Water",
		"method": "Culture",
		"parameter": "Coliforms",
		"limit_value": 3,
		"unit": "CFU/100 ml",
	},
	{
		"limit_code": "SURFACE-ATP",
		"title": "High-touch surface - ATP",
		"sample_type": "Surface",
		"method": "ATP",
		"parameter": "ATP",
		"limit_value": 250,
		"unit": "RLU",
	},
]

VENTILATION = (
	("VENT-01", "Air handling unit runs per schedule", 2, 1),
	("VENT-02", "Filters are within their change date", 2, 1),
	("VENT-03", "Room pressure difference is in range", 2, 1),
	("VENT-04", "Air changes per hour meet the design", 1, 0),
	("VENT-05", "Maintenance log is signed", 1, 0),
)
WATER = (
	("WATER-01", "Water source and tanks are covered and clean", 2, 1),
	("WATER-02", "Tanks are cleaned on schedule", 1, 0),
	("WATER-03", "Residual chlorine is checked and logged", 2, 1),
	("WATER-04", "Water test results are on file", 1, 0),
)
FOOD = (
	("FS-01", "Food service license is valid", 2, 1),
	("FS-02", "Food handlers wear clean protective clothing", 1, 0),
	("FS-03", "Raw and cooked food are kept apart", 2, 1),
	("FS-04", "Food samples are kept for 24 hours", 2, 1),
	("FS-05", "Kitchen and utensils are clean", 1, 0),
)
# mã → (tiêu đề, loại phiếu, căn cứ, phần, mục, loại hạ tầng, chu kỳ ngày)
TEMPLATES = {
	"INFRA-VENT": (
		"Infrastructure - ventilation",
		"Infrastructure",
		"TT 16/2018/TT-BYT Article 11",
		"Ventilation",
		VENTILATION,
		"Ventilation",
		180,
	),
	"INFRA-WATER": (
		"Infrastructure - water supply",
		"Infrastructure",
		"TT 16/2018/TT-BYT Article 11",
		"Water supply",
		WATER,
		"Water Supply",
		90,
	),
	"ATTP": ("Food safety", "Food Safety", "Law 55/2010/QH12", "Food service", FOOD, None, 0),
}


def _t(text):
	return frappe._(text, LANG)


def source_texts():
	"""Mọi chuỗi tiếng Anh của bộ khởi tạo — phải có bản dịch trong ``vi.csv``."""
	texts = [row["risk_name"] for row in RISK_LEVELS] + [QD3916, DRAFT_REF]
	texts += [text for row in LIMITS for text in (row["title"], row["parameter"])]
	for title, _type, legal_ref, section, items, _category, _days in TEMPLATES.values():
		texts += [title, legal_ref, section, *(item[1] for item in items)]
	return list(dict.fromkeys(texts))


def _risk_levels():
	created = []
	for row in RISK_LEVELS:
		name = _t(row["risk_name"])
		if frappe.db.exists(zones.RISK_DOCTYPE, name):
			continue
		doc = frappe.get_doc(
			{**row, "doctype": zones.RISK_DOCTYPE, "risk_name": name, "legal_ref": _t(QD3916)}
		)
		created.append(doc.insert(ignore_permissions=True).name)
	return created


def limit_rows():
	return [
		{
			**row,
			"title": _t(row["title"]),
			"parameter": _t(row["parameter"]),
			"legal_ref": _t(DRAFT_REF),
			"effective_from": today(),
		}
		for row in LIMITS
	]


def _templates():
	created = []
	for code, (title, audit_type, legal_ref, section, items, category, days) in TEMPLATES.items():
		if frappe.db.exists("Audit Template", {"template_code": code}):
			continue
		doc = frappe.get_doc(
			{
				"doctype": "Audit Template",
				"template_code": code,
				"title": _t(title),
				"audit_type": audit_type,
				"scoring_method": "Weighted Score",
				"min_sample": 0,
				"legal_ref": _t(legal_ref),
				"effective_from": today(),
				"infra_category": category,
				"inspection_interval_days": days,
				"items": [
					{
						"item_code": item_code,
						"section": _t(section),
						"question": _t(question),
						"answer_type": "Pass/Fail",
						"weight": weight,
						"is_critical": critical,
					}
					for item_code, question, weight, critical in items
				],
			}
		)
		created.append(doc.insert(ignore_permissions=True).name)
	return created


def ensure_seed():
	"""Hook ``after_install`` / ``after_migrate``; trả tên bản ghi vừa tạo."""
	return _risk_levels() + limits.install(limit_rows()) + _templates()
