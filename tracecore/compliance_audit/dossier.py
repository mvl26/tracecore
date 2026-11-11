"""Phần "kết quả giám sát tuân thủ" của gói hồ sơ KSNK (FEAT-074; FR-M9-30; BRU-RPT-002; A-152).

Đăng ký qua hook ``tracecore_ic_dossier_sections``: mỗi tháng trong dải, tổng hợp phiếu giám sát đã ghi sổ theo (mẫu,
khoa) từ ``compliance.aggregate`` — vệ sinh tay tính theo cơ hội (BRU-AUD-002). Chỉ số liệu tổng hợp, không có người
được quan sát hay người bệnh.
"""

from frappe.utils import get_last_day, getdate

from tracecore.compliance_audit import compliance
from tracecore.core.dossier import DossierSection, ExportField


def rows(ctx):
	out = []
	for month in ctx.months:
		start = getdate(f"{month}-01")
		for row in compliance.aggregate({"from_date": start, "to_date": get_last_day(start)}):
			if not row.sessions and not row.scored:
				continue
			out.append({"month": month, **row})
	return out


def register():
	return [
		DossierSection(
			key="compliance",
			label="Compliance audit results",
			order=70,
			fields=[
				ExportField("month", "Period"),
				ExportField("template_code", "Template Code"),
				ExportField("template_title", "Template"),
				ExportField("department", "Department"),
				ExportField("sessions", "Audit Sessions", "int"),
				ExportField("scored", "Observations", "int"),
				ExportField("passed", "Passed", "int"),
				ExportField("pass_rate", "Pass Rate (%)", "float"),
				ExportField("avg_score", "Average Score (%)", "float"),
				ExportField("sample_note", "Sample Note", "select"),
			],
			rows=rows,
		)
	]
