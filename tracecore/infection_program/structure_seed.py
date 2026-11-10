"""Bộ tiêu chí cơ cấu KSNK khởi tạo theo TT 16/2018/TT-BYT Điều 16-22 (FEAT-094; FR-M11-01.8; NFR-MAINT-04; A-138 a, b).

Chạy ở ``after_install`` và ``after_migrate``. Chỉ chèn một bản Nháp khi site **chưa có bản IC Structure Profile nào**:
bản bệnh viện đã sửa, đã duyệt hay đã thay thế đều không bị nạp lại đè lên (AC-094-02). Không dùng ``fixtures`` của
Frappe vì ``bench migrate`` nạp lại fixtures. Nội dung chỉ là bản nháp khởi đầu, R01 rà soát và duyệt tại bệnh viện;
đến khi duyệt, ``structure.compute`` chỉ kiểm phần đếm (OQ-V12-16).
"""

import frappe
from frappe import _

from tracecore.infection_program import structure_profile

# nguồn tiếng Anh, lưu bản tiếng Việt từ translations/vi.csv (căn cứ hiển thị cho R01)
LEGAL_BASIS = "TT 16/2018/TT-BYT Articles 16-22"
EFFECTIVE_FROM = "2018-08-15"  # ngày TT 16/2018/TT-BYT có hiệu lực
# Điều 17.1d: lãnh đạo phòng chức năng, vi sinh - xét nghiệm, dược, khoa lâm sàng nguy cơ cao
COMMITTEE_GROUPS = ("Functional Unit", "Microbiology and Laboratory", "Pharmacy", "High-risk Clinical")
LEAD = {
	"min_education": "Bachelor",
	"health_field_required": 1,
	"full_time_required": 1,
	"evidence_required": 1,
}
SURVEILLANCE = {
	"min_education": "College",
	"health_field_required": 1,
	"full_time_required": 1,
	"evidence_required": 1,
}
# Điều 16.3 không nêu bậc học của người phụ trách; Điều 16.4 (không nội trú) không nêu điều kiện
PERSON_IN_CHARGE = {
	"min_education": "None",
	"health_field_required": 1,
	"full_time_required": 1,
	"evidence_required": 1,
}
NO_CONDITION = {
	"min_education": "None",
	"health_field_required": 0,
	"full_time_required": 0,
	"evidence_required": 0,
}
ROLES = (
	("Head", "Large", LEAD),  # Điều 18.1b
	("Head Nurse", "Large", LEAD),  # Điều 18.1b
	("Person in Charge", "Small", PERSON_IN_CHARGE),  # Điều 16.3
	("Surveillance Officer", "Large", SURVEILLANCE),  # Điều 22.1b, c
	("Surveillance Officer", "Small", SURVEILLANCE),  # Điều 22.1c
	("Person in Charge", "Outpatient", NO_CONDITION),  # Điều 16.4
)


def default_profile():
	return {
		"doctype": structure_profile.PROFILE,
		"profile_name": "TT 16/2018",
		"effective_from": EFFECTIVE_FROM,
		"legal_basis": _(LEGAL_BASIS, "vi"),
		"department_min_beds": 150,
		"committee_min_beds": 150,
		"committee_rule_severity": "Warn",
		"network_rule": "Doctor and Nurse",
		"allow_one_person_both_roles": 0,
		"committee_requirements": [
			{"requirement_type": "Representing", "representing": group, "min_count": 1}
			for group in COMMITTEE_GROUPS
		],
		"role_requirements": [
			{"ic_role": role, "applies_to": applies_to, **conditions}
			for role, applies_to, conditions in ROLES
		],
	}


def ensure_seed():
	"""Hook ``after_install`` / ``after_migrate``: chèn bản Nháp TT 16/2018 khi chưa có bản nào; trả tên hoặc None."""
	if frappe.db.count(structure_profile.PROFILE):
		return None
	return frappe.get_doc(default_profile()).insert(ignore_permissions=True).name
