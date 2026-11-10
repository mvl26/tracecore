"""Bộ định nghĩa ca NKBV khởi tạo ở trạng thái Nháp (FEAT-063; FR-M13-01; D10, NFR-MAINT-04, OQ-V12-08; A-144 a).

Chạy ở ``after_install`` và ``after_migrate``; chỉ chèn mã còn thiếu, không ghi đè bản bệnh viện đã sửa hay đã duyệt.
Nội dung chỉ là bản nháp khởi đầu theo QĐ 3916/QĐ-BYT, QĐ 3671/QĐ-BYT và QĐ 1526/QĐ-BYT: R01 cùng chuyên gia KSNK
rà soát, sửa và ghi sổ (duyệt) trước khi ca dùng được (BRU-HAI-001). Chuỗi nguồn tiếng Anh, dịch qua ``vi.csv``.
"""

import frappe

from tracecore.hai_surveillance import definitions

LANG = "vi"
EFFECTIVE_FROM = "2026-01-01"
REVIEW = "Draft for review by the infection control expert before approval."
DEVICE_REF = "Decision 3916/QD-BYT; Decision 3671/QD-BYT"
SSI_REF = "Decision 1526/QD-BYT; Decision 3671/QD-BYT"
# mã: (tiêu đề, vị trí, thiết bị, giờ sau nhập viện, ngày thiết bị trước khởi phát, căn cứ, tiêu chí)
DEFINITIONS = {
	"VAP": (
		"Ventilator-associated pneumonia",
		"Ventilator-associated Pneumonia",
		"Ventilator",
		48,
		2,
		DEVICE_REF,
		(
			"Patient on mechanical ventilation before the onset of pneumonia.",
			"New or progressive infiltrate on chest imaging.",
			"Clinical signs: fever or abnormal white cell count, new purulent sputum or worsening gas exchange.",
		),
	),
	"CLABSI": (
		"Central line-associated bloodstream infection",
		"Catheter-related Bloodstream Infection",
		"Central Line",
		48,
		2,
		DEVICE_REF,
		(
			"Central venous catheter in place before the positive blood culture.",
			"Recognised pathogen in blood culture not related to an infection at another site.",
		),
	),
	"CAUTI": (
		"Catheter-associated urinary tract infection",
		"Catheter-associated Urinary Tract Infection",
		"Urinary Catheter",
		48,
		2,
		DEVICE_REF,
		(
			"Indwelling urinary catheter in place before the onset.",
			"Positive urine culture with symptoms such as fever, suprapubic tenderness or flank pain.",
		),
	),
	"SSI-SUP": (
		"Superficial incisional surgical site infection",
		"Superficial Incisional SSI",
		None,
		0,
		0,
		SSI_REF,
		(
			"Infection within the surveillance window after surgery, involving only skin and subcutaneous tissue of the incision.",
		),
	),
	"SSI-DEEP": (
		"Deep incisional surgical site infection",
		"Deep Incisional SSI",
		None,
		0,
		0,
		SSI_REF,
		("Infection within the surveillance window involving deep soft tissues of the incision.",),
	),
	"SSI-ORGAN": (
		"Organ/space surgical site infection",
		"Organ/Space SSI",
		None,
		0,
		0,
		SSI_REF,
		(
			"Infection within the surveillance window involving any part of the body opened or manipulated during surgery.",
		),
	),
}
CODES = tuple(DEFINITIONS)


def source_texts():
	"""Mọi chuỗi tiếng Anh của bộ định nghĩa — phải có bản dịch trong ``vi.csv``."""
	texts = [REVIEW]
	for title, _site, _device, _hours, _days, legal_ref, criteria in DEFINITIONS.values():
		texts += [title, legal_ref, *criteria]
	return list(dict.fromkeys(texts))


def _t(text):
	return frappe._(text, LANG)


def rows():
	return [
		{
			"def_code": code,
			"title": _t(title),
			"infection_site": site,
			"device_type": device,
			"min_hours_after_admission": hours,
			"min_device_days_before_onset": days,
			"legal_ref": _t(legal_ref),
			"effective_from": EFFECTIVE_FROM,
			"notes": _t(REVIEW),
			"criteria": [{"criterion": _t(text)} for text in criteria],
		}
		for code, (title, site, device, hours, days, legal_ref, criteria) in DEFINITIONS.items()
	]


def ensure_seed():
	"""Hook ``after_install`` / ``after_migrate``; trả tên các định nghĩa vừa tạo."""
	created = []
	for row in rows():
		if frappe.db.exists(definitions.DOCTYPE, {"def_code": row["def_code"]}):
			continue
		doc = frappe.get_doc({**row, "doctype": definitions.DOCTYPE})
		created.append(doc.insert(ignore_permissions=True).name)
	return created
