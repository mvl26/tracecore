"""Phần "vi sinh - đa kháng - cách ly" của gói hồ sơ KSNK (FEAT-074; FR-M9-30, FR-M9-30.1; BRU-RPT-002; NFR-PRIV-01;
A-152 Q3).

Đăng ký qua hook ``tracecore_ic_dossier_sections``; danh sách chỉ ở Excel, mã BN dạng che, không họ tên:
- ``mdro_isolates``: chủng đa kháng có ngày lấy mẫu trong dải.
- ``isolation_orders``: lệnh cách ly đã ghi sổ bắt đầu trong dải (loại phòng ngừa, lý do, phòng, kết thúc).
"""

import frappe
from frappe.utils import add_days

from tracecore.core.dossier import DossierSection, ExportField


def isolate_rows(ctx):
	return frappe.get_all(
		"Microbiology Isolate",
		filters={"is_mdro": 1, "collected_on": ["between", [ctx.from_date, ctx.to_date]]},
		fields=[
			"name",
			"collected_on",
			"department_name",
			"organism_name",
			"organism_group",
			"specimen_type",
			"mdro_flags",
			"is_first_isolate",
			"patient_code_masked",
		],
		order_by="collected_on asc, name asc",
	)


def isolation_rows(ctx):
	return frappe.get_all(
		"Isolation Order",
		filters=[
			["docstatus", "=", 1],
			["start_at", ">=", ctx.from_date],
			["start_at", "<", add_days(ctx.to_date, 1)],
		],
		fields=[
			"name",
			"start_at",
			"end_at",
			"department_name",
			"isolation_room",
			"bedside_isolation",
			"precaution_type",
			"reason",
			"is_mdro",
			"status",
			"patient_code_masked",
		],
		order_by="start_at asc, name asc",
	)


def register():
	return [
		DossierSection(
			key="mdro_isolates",
			label="Multidrug-resistant isolates",
			order=100,
			in_pdf=False,
			fields=[
				ExportField("name", "Isolate"),
				ExportField("collected_on", "Collected On", "date"),
				ExportField("department_name", "Department"),
				ExportField("organism_name", "Organism"),
				ExportField("organism_group", "Organism Group"),
				ExportField("specimen_type", "Specimen Type"),
				ExportField("mdro_flags", "Multidrug Resistance"),
				ExportField("is_first_isolate", "First Isolate", "check"),
				ExportField("patient_code_masked", "Patient Code"),
			],
			rows=isolate_rows,
		),
		DossierSection(
			key="isolation_orders",
			label="Isolation orders",
			order=110,
			in_pdf=False,
			fields=[
				ExportField("name", "Isolation Order"),
				ExportField("start_at", "Start", "date"),
				ExportField("end_at", "End", "date"),
				ExportField("department_name", "Department"),
				ExportField("isolation_room", "Isolation Room"),
				ExportField("bedside_isolation", "Bedside Isolation", "check"),
				ExportField("precaution_type", "Precaution Type", "select"),
				ExportField("reason", "Reason", "select"),
				ExportField("is_mdro", "Multidrug-Resistant", "check"),
				ExportField("status", "Status", "select"),
				ExportField("patient_code_masked", "Patient Code"),
			],
			rows=isolation_rows,
		),
	]
