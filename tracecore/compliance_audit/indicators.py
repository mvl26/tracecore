"""Hàm chỉ số KSNK của M12 cho bảng chỉ số M9 (FEAT-060; FR-M12-14, ADR-015; hook ``tracecore_ic_indicators``).

Mỗi hàm nhận ``(period "YYYY-MM", department | None)`` và trả ``(phiếu Đạt, phiếu có kết quả, cỡ mẫu)`` từ
``compliance.aggregate``. Tỷ lệ tuân thủ vệ sinh tay theo cơ hội (BRU-AUD-002) do FEAT-061 đăng ký.
"""

from frappe.utils import get_first_day, get_last_day, getdate

from tracecore.compliance_audit import compliance, hand_hygiene

RATE_ALL = "AUDIT_PASS_RATE"
# FEAT-061 (BRU-AUD-002): tuân thủ vệ sinh tay tính theo cơ hội; đúng kỹ thuật tách riêng, mẫu số là cơ hội có hành động
HAND_HYGIENE_RATE = "HAND_HYGIENE_RATE"
HAND_HYGIENE_TECHNIQUE = "HAND_HYGIENE_TECHNIQUE"
# khóa chỉ số → loại phiếu (audit_type) của Audit Template
BY_TYPE = {
	"AUDIT_PASS_PPE": "Standard Precautions - PPE",
	"AUDIT_PASS_BUNDLE": "Prevention Bundle",
	"AUDIT_PASS_ENV": "Environmental Hygiene",
	"AUDIT_PASS_VENDOR": "Outsourced Service",
	"AUDIT_PASS_FOOD": "Food Safety",
}


def _rate(period, department=None, audit_type=None):
	start = getdate(f"{period}-01")
	rows = compliance.aggregate(
		{
			"from_date": get_first_day(start),
			"to_date": get_last_day(start),
			"department": department,
			"audit_type": audit_type,
			"exclude_opportunity": 1,
		}
	)
	passed = sum(row.passed for row in rows)
	scored = sum(row.scored for row in rows)
	return passed, scored, scored


def pass_rate(period, department=None):
	return _rate(period, department)


def _by_type(audit_type):
	def compute(period, department=None):
		return _rate(period, department, audit_type)

	return compute


def _hygiene_totals(period, department=None):
	start = getdate(f"{period}-01")
	return hand_hygiene.totals(
		{"from_date": get_first_day(start), "to_date": get_last_day(start), "department": department}
	)


def hand_hygiene_rate(period, department=None):
	total, actioned, _technique = _hygiene_totals(period, department)
	return actioned, total, total


def hand_hygiene_technique(period, department=None):
	_total, actioned, technique = _hygiene_totals(period, department)
	return technique, actioned, actioned


def register():
	return {
		RATE_ALL: pass_rate,
		**{key: _by_type(audit_type) for key, audit_type in BY_TYPE.items()},
		HAND_HYGIENE_RATE: hand_hygiene_rate,
		HAND_HYGIENE_TECHNIQUE: hand_hygiene_technique,
	}
