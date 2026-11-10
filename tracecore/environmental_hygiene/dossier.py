"""Phần "giám sát môi trường" của gói hồ sơ KSNK (FEAT-074; FR-M9-30; A-152).

Đăng ký qua hook ``tracecore_ic_dossier_sections``: mẫu môi trường đã ghi sổ có ngày lấy mẫu trong dải (vùng, loại mẫu,
phương pháp, kết quả so ngưỡng, NC). Không có dữ liệu người bệnh.
"""

import frappe
from frappe.utils import add_days

from tracecore.core.dossier import DossierSection, ExportField


def sample_rows(ctx):
	return frappe.get_all(
		"Environmental Sample",
		filters=[
			["docstatus", "=", 1],
			["sampled_on", ">=", ctx.from_date],
			["sampled_on", "<", add_days(ctx.to_date, 1)],
		],
		fields=[
			"name",
			"sampled_on",
			"environment_zone_name",
			"department",
			"risk_level",
			"sample_type",
			"method",
			"lab",
			"result_value",
			"unit",
			"limit_code",
			"result",
			"nc_status",
		],
		order_by="sampled_on asc, name asc",
	)


def register():
	return [
		DossierSection(
			key="environment_samples",
			label="Environmental samples",
			order=120,
			fields=[
				ExportField("name", "Sample"),
				ExportField("sampled_on", "Sampled On", "date"),
				ExportField("environment_zone_name", "Zone"),
				ExportField("department", "Department"),
				ExportField("risk_level", "Risk Level"),
				ExportField("sample_type", "Sample Type", "select"),
				ExportField("method", "Method", "select"),
				ExportField("lab", "Laboratory"),
				ExportField("result_value", "Result Value", "float"),
				ExportField("unit", "Unit"),
				ExportField("limit_code", "Limit"),
				ExportField("result", "Result", "select"),
				ExportField("nc_status", "Non-conformance", "select"),
			],
			rows=sample_rows,
		)
	]
