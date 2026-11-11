"""Phần "giám sát NKBV, NKVM" của gói hồ sơ KSNK (FEAT-074; FR-M9-30, FR-M9-30.1; BRU-RPT-002; NFR-PRIV-01; A-152 Q3).

Đăng ký qua hook ``tracecore_ic_dossier_sections``; danh sách chỉ ở Excel (``in_pdf`` = False), mã BN dạng che, không họ
tên (BRU-HAI-005):
- ``hai_cases``: ca NKBV đã xác định có ngày khởi phát trong dải.
- ``ssi``: người bệnh được giám sát NKVM có ngày mổ trong dải (kết quả, NNIS, kháng sinh dự phòng).
"""

import frappe

from tracecore.core.dossier import DossierSection, ExportField

CASE_FIELDS = [
	"name",
	"onset_date",
	"department_name",
	"def_code",
	"infection_site",
	"device_type",
	"outcome",
	"mdro_flags",
	"patient_code_masked",
]
SSI_FIELDS = [
	"name",
	"surgery_date",
	"department_name",
	"group_name",
	"wound_class",
	"asa_score",
	"nnis_index",
	"outcome",
	"hai_case",
	"prophylaxis_timing",
	"patient_code_masked",
]


def case_rows(ctx):
	return frappe.get_all(
		"HAI Case",
		filters={
			"docstatus": 1,
			"status": "Confirmed",
			"onset_date": ["between", [ctx.from_date, ctx.to_date]],
		},
		fields=CASE_FIELDS,
		order_by="onset_date asc, name asc",
	)


def ssi_rows(ctx):
	return frappe.get_all(
		"Surgical Surveillance",
		filters={"surgery_date": ["between", [ctx.from_date, ctx.to_date]]},
		fields=SSI_FIELDS,
		order_by="surgery_date asc, name asc",
	)


def register():
	return [
		DossierSection(
			key="hai_cases",
			label="Healthcare-associated infection cases",
			order=80,
			in_pdf=False,
			fields=[
				ExportField("name", "HAI Case"),
				ExportField("onset_date", "Onset Date", "date"),
				ExportField("department_name", "Department"),
				ExportField("def_code", "Case Definition"),
				ExportField("infection_site", "Infection Site"),
				ExportField("device_type", "Device Type", "select"),
				ExportField("outcome", "Outcome", "select"),
				ExportField("mdro_flags", "Multidrug Resistance"),
				ExportField("patient_code_masked", "Patient Code"),
			],
			rows=case_rows,
		),
		DossierSection(
			key="ssi",
			label="Surgical site infection surveillance",
			order=90,
			in_pdf=False,
			fields=[
				ExportField("name", "Surgical Surveillance"),
				ExportField("surgery_date", "Surgery Date", "date"),
				ExportField("department_name", "Department"),
				ExportField("group_name", "Procedure Group"),
				ExportField("wound_class", "Wound Class", "select"),
				ExportField("asa_score", "ASA Score", "int"),
				ExportField("nnis_index", "NNIS Index"),
				ExportField("outcome", "Outcome", "select"),
				ExportField("hai_case", "HAI Case"),
				ExportField("prophylaxis_timing", "Prophylaxis Timing", "select"),
				ExportField("patient_code_masked", "Patient Code"),
			],
			rows=ssi_rows,
		),
	]
