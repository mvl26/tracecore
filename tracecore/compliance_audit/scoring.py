"""Chấm điểm phiếu giám sát theo `scoring_method` của mẫu (FEAT-060; ADR-015, FR-M12-06, BRU-AUD-003/005, A-132).

Sổ phương pháp ``SCORERS``: mỗi hàm nhận (phiếu, mẫu) và trả ``(score_pct | None, result | None, critical_failed)``.
FEAT-060 đăng ký "Weighted Score" và "All or None"; "By Opportunity" (vệ sinh tay, BRU-AUD-002) do FEAT-061 đăng ký.
Chỉ mục kiểu Pass/Fail được chấm; mục Không áp dụng (N/A) hoặc chưa trả lời loại khỏi mẫu số.
"""

from frappe.utils import cint, flt

PASS, FAIL, NA = "Pass", "Fail", "N/A"
PASS_FAIL = "Pass/Fail"
SCORERS = {}


def register(method):
	def decorator(fn):
		SCORERS[method] = fn
		return fn

	return decorator


def applicable(doc):
	"""Dòng trả lời được chấm: kiểu Pass/Fail và đã trả lời Đạt hoặc Không đạt."""
	return [row for row in doc.answers or () if row.answer_type == PASS_FAIL and row.answer in (PASS, FAIL)]


def critical_failed(rows):
	return any(cint(row.is_critical) and row.answer == FAIL for row in rows)


@register("Weighted Score")
def weighted(doc, template):
	rows = applicable(doc)
	critical = critical_failed(rows)
	total = sum(flt(row.weight) for row in rows)
	if not rows or total <= 0:
		return None, (FAIL if critical else None), critical
	score = round(sum(flt(row.weight) for row in rows if row.answer == PASS) * 100 / total, 1)
	if critical:
		return score, FAIL, True
	threshold = template.get("pass_threshold")
	if threshold not in (None, "") and score < flt(threshold):
		return score, FAIL, False
	return score, PASS, False


@register("All or None")
def all_or_none(doc, template):
	rows = applicable(doc)
	if not rows:
		return None, None, False
	return None, (PASS if all(row.answer == PASS for row in rows) else FAIL), critical_failed(rows)


def score(doc, template):
	scorer = SCORERS.get(doc.scoring_method)
	if not scorer:
		return None, None, False
	return scorer(doc, template)
