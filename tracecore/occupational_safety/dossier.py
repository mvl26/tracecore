"""Phần "phơi nhiễm nghề nghiệp" của gói hồ sơ KSNK (FEAT-074; FR-M9-30, FR-M9-30.1; FR-M16-06; BRU-RPT-002; A-152 Q3).

Đăng ký qua hook ``tracecore_ic_dossier_sections``. **Chỉ số liệu tổng hợp** theo tháng x khoa x loại phơi nhiễm: số
ca, báo muộn, có điều trị dự phòng, đã hoàn thành theo dõi. Không tên/mã nhân viên, không mã BN nguồn, không kết quả xét
nghiệm (hồ sơ phơi nhiễm chỉ R01, R11 và chính nhân viên xem).
"""

import frappe

from tracecore.core.dossier import DossierSection, ExportField

CANCELLED = "Cancelled"


def rows(ctx):
	return frappe.db.sql(
		"""
		select date_format(occurred_at, '%%Y-%%m') as month, department_name, exposure_type,
			count(*) as exposures,
			sum(case when report_late = 1 then 1 else 0 end) as reported_late,
			sum(case when prophylaxis = 'Given' then 1 else 0 end) as prophylaxis_given,
			sum(case when status = 'Completed' then 1 else 0 end) as follow_up_completed
		from `tabOccupational Exposure`
		where status != %(cancelled)s and date(occurred_at) between %(start)s and %(end)s
		group by month, department_name, exposure_type
		order by month asc, department_name asc, exposure_type asc
		""",
		{"cancelled": CANCELLED, "start": ctx.from_date, "end": ctx.to_date},
		as_dict=True,
	)


def register():
	return [
		DossierSection(
			key="exposures",
			label="Occupational exposures (aggregated)",
			order=130,
			fields=[
				ExportField("month", "Period"),
				ExportField("department_name", "Department"),
				ExportField("exposure_type", "Exposure Type", "select"),
				ExportField("exposures", "Exposures", "int"),
				ExportField("reported_late", "Reported Late", "int"),
				ExportField("prophylaxis_given", "Prophylaxis Given", "int"),
				ExportField("follow_up_completed", "Follow-up Completed", "int"),
			],
			rows=rows,
		)
	]
