"""Bộ mẫu phiếu giám sát khởi tạo (FEAT-061; FR-M12-02, NFR-MAINT-04, D10, A-140).

8 mẫu: vệ sinh tay 5 thời điểm, phòng ngừa chuẩn - PPE, 4 gói dự phòng (VAP, CLABSI, CAUTI, SSI), vệ sinh môi trường bề
mặt, đơn vị thuê ngoài. Tất cả ở trạng thái **Nháp**: nội dung chỉ là bản khởi đầu để R01 xem, sửa và ghi sổ (duyệt) tại
bệnh viện (OQ-V12-08); không phải tiêu chí đã được chuyên gia duyệt. ATTP thuộc FEAT-070, Tự đánh giá thuộc FEAT-072.

Chạy ở ``after_install`` và ``after_migrate`` qua ``templates.install_templates``: chỉ chèn mã còn thiếu, không ghi đè
mẫu bệnh viện đã sửa hay đã duyệt. Không dùng ``fixtures`` của Frappe vì ``bench migrate`` nạp lại fixtures đè lên chỉnh sửa.
Nguồn tiếng Anh nằm ở đây; văn bản lưu vào DB là bản tiếng Việt lấy từ ``translations/vi.csv`` (thiếu thì giữ tiếng Anh).
"""

import frappe
from frappe.utils import today

from tracecore.compliance_audit import templates

BY_OPPORTUNITY, ALL_OR_NONE, WEIGHTED = templates.BY_OPPORTUNITY, templates.ALL_OR_NONE, templates.WEIGHTED
LANG = "vi"
HYGIENE_SECTION = "WHO 5 moments of hand hygiene"
BUNDLE_SECTION = "Bundle elements"
DECISION = "decision"

# (mã mục, câu hỏi, trọng số, trọng yếu)
MOMENTS = (
	("MOMENT-1", "Before touching a patient"),
	("MOMENT-2", "Before a clean or aseptic procedure"),
	("MOMENT-3", "After body fluid exposure risk"),
	("MOMENT-4", "After touching a patient"),
	("MOMENT-5", "After touching a patient's surroundings"),
)
PPE = (
	("PPE-01", "Hand hygiene before putting on gloves", 2, 1),
	("PPE-02", "PPE is chosen to match the exposure risk", 2, 1),
	("PPE-03", "PPE is put on in the right order", 1, 0),
	("PPE-04", "PPE is removed in the right order", 1, 0),
	("PPE-05", "Used PPE is discarded in the right waste bin", 1, 0),
	("PPE-06", "Sharps box is not more than three-quarters full", 1, 0),
	("PPE-07", "No two-handed needle recapping", 2, 1),
	("PPE-08", "Hand hygiene right after removing PPE", 1, 0),
)
VAP = (
	("VAP-01", "Head of bed is raised 30 to 45 degrees", 1, 1),
	("VAP-02", "Sedation is reviewed daily and readiness to wean is checked", 1, 0),
	("VAP-03", "Oral care is done per protocol", 1, 0),
	("VAP-04", "Ventilator circuit is closed and not changed without indication", 1, 0),
	("VAP-05", "Cuff pressure is checked per protocol", 1, 0),
	("VAP-06", "Hand hygiene before airway care", 1, 1),
)
CLABSI = (
	("CLB-01", "Need for the central line is reviewed daily", 1, 1),
	("CLB-02", "Insertion site dressing is clean, dry and intact", 1, 0),
	("CLB-03", "Hub is disinfected before each access", 1, 0),
	("CLB-04", "Dressing and tubing are changed on schedule and dated", 1, 0),
	("CLB-05", "Hand hygiene before catheter care", 1, 1),
	("CLB-06", "Skin antisepsis with chlorhexidine at insertion and dressing change", 1, 0),
)
CAUTI = (
	("CAU-01", "Need for the urinary catheter is reviewed daily", 1, 1),
	("CAU-02", "Closed drainage system is intact", 1, 0),
	("CAU-03", "Drainage bag is below bladder level and off the floor", 1, 0),
	("CAU-04", "Catheter is secured and perineal care is done", 1, 0),
	("CAU-05", "Hand hygiene before catheter care", 1, 1),
	("CAU-06", "Urine is sampled from the sampling port with aseptic technique", 1, 0),
)
SSI = (
	("SSI-01", "Prophylactic antibiotic is given within 60 minutes before incision", 1, 1),
	("SSI-02", "Hair is removed only if needed, using clippers", 1, 0),
	("SSI-03", "Skin antisepsis is done and allowed to dry", 1, 0),
	("SSI-04", "Surgical hand antisepsis is done by the team", 1, 0),
	("SSI-05", "Normal body temperature is kept during surgery", 1, 0),
	("SSI-06", "Dressing stays intact and is changed with aseptic technique", 1, 0),
)
ENVIRONMENT = (
	("ENV-01", "Cleaning schedule is posted and signed", 1, 0),
	("ENV-02", "Right disinfectant and dilution are used", 2, 1),
	("ENV-03", "High-touch surfaces are visibly clean", 2, 0),
	("ENV-04", "Cleaning goes from clean to dirty areas", 1, 0),
	("ENV-05", "Mops and cloths are changed and washed per protocol", 1, 0),
	("ENV-06", "Blood or body fluid spill is cleaned with the spill kit", 2, 1),
)
OUTSOURCED = (
	("VND-01", "A valid license is on file", 2, 1),
	("VND-02", "Staff wear the required PPE", 1, 0),
	("VND-03", "Staff are trained in infection control", 1, 0),
	("VND-04", "Waste or linen is handled and transported separately", 2, 1),
	("VND-05", "Service log is signed by the department", 1, 0),
	("VND-06", "Equipment and vehicles are clean", 1, 0),
)

# mã mẫu → (tiêu đề, loại, phương pháp chấm, loại gói, cỡ mẫu tối thiểu, căn cứ, phần, mục)
TEMPLATES = {
	"VST": (
		"Hand hygiene - 5 moments",
		"Hand Hygiene",
		BY_OPPORTUNITY,
		None,
		30,  # mục tiêu "≥ 30 cơ hội/khoa/tháng" của UC-44; R01 chỉnh tại bệnh viện (OQ-V12-09)
		"QD 3916/QD-BYT",
		HYGIENE_SECTION,
		[(code, question, 0, 0) for code, question in MOMENTS],
	),
	"PPE": (
		"Standard precautions - PPE",
		"Standard Precautions - PPE",
		WEIGHTED,
		None,
		0,
		"QD 3671/QD-BYT",
		"Standard precautions",
		PPE,
	),
	"VAP": (
		"VAP prevention bundle",
		"Prevention Bundle",
		ALL_OR_NONE,
		"VAP",
		0,
		"QD 3671/QD-BYT",
		BUNDLE_SECTION,
		VAP,
	),
	"CLABSI": (
		"CLABSI prevention bundle",
		"Prevention Bundle",
		ALL_OR_NONE,
		"CLABSI",
		0,
		"QD 3671/QD-BYT",
		BUNDLE_SECTION,
		CLABSI,
	),
	"CAUTI": (
		"CAUTI prevention bundle",
		"Prevention Bundle",
		ALL_OR_NONE,
		"CAUTI",
		0,
		"QD 3916/QD-BYT",
		BUNDLE_SECTION,
		CAUTI,
	),
	"SSI": (
		"SSI prevention bundle",
		"Prevention Bundle",
		ALL_OR_NONE,
		"SSI",
		0,
		"QD 3671/QD-BYT",
		BUNDLE_SECTION,
		SSI,
	),
	"VSMT": (
		"Environmental surface hygiene",
		"Environmental Hygiene",
		WEIGHTED,
		None,
		0,
		"TT 16/2018/TT-BYT",
		"Environmental cleaning",
		ENVIRONMENT,
	),
	"OUTSRC": (
		"Outsourced service provider",
		"Outsourced Service",
		WEIGHTED,
		None,
		0,
		"TT 16/2018/TT-BYT Article 25",
		"Service provider",
		OUTSOURCED,
	),
}


def source_texts():
	"""Mọi chuỗi tiếng Anh của bộ mẫu (tiêu đề, phần, câu hỏi) — phải có bản dịch trong ``vi.csv``."""
	texts = []
	for title, _type, _method, _bundle, _min, legal_ref, section, items in TEMPLATES.values():
		texts += [title, section, legal_ref, *(item[1] for item in items)]
	return list(dict.fromkeys(texts))


def _t(text):
	return frappe._(text, LANG)


def rows():
	"""Giá trị Audit Template (kèm ``items``) của bộ mẫu, văn bản đã dịch sang tiếng Việt."""
	result = []
	for code, (title, audit_type, method, bundle, min_sample, legal_ref, section, items) in TEMPLATES.items():
		result.append(
			{
				"template_code": code,
				"title": _t(title),
				"audit_type": audit_type,
				"scoring_method": method,
				"bundle_type": bundle,
				"min_sample": min_sample,
				"legal_ref": _t(legal_ref),
				"effective_from": today(),
				"items": [
					{
						"item_code": item_code,
						"section": _t(section),
						"question": _t(question),
						"answer_type": "Choice" if method == BY_OPPORTUNITY else "Pass/Fail",
						"weight": weight,
						"is_critical": critical,
					}
					for item_code, question, weight, critical in items
				],
			}
		)
	return result


def ensure_seed():
	"""Hook ``after_install`` / ``after_migrate``; trả tên các mẫu vừa tạo."""
	return templates.install_templates(rows())
