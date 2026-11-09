"""Loại import "Kết quả vi sinh" cho khung `core.importer` (FEAT-067; FR-M14-01, EI-SW-011, F-21; UC-51; A-136 Q6, Q7).

File CSV/Excel xuất từ WHONET hoặc phòng xét nghiệm, đọc qua Import Mapping Profile:

- dạng **dài**: mỗi dòng một cặp chủng x kháng sinh (cột Antibiotic Code, Result, MIC), các dòng cùng
  (`lab_sample_id`, mã vi khuẩn) gom thành một chủng;
- dạng **rộng** WHONET: mỗi kháng sinh một cột, hồ sơ ánh xạ cột đó sang đích ``ab:<MÃ>`` (vd ``MEM_NM`` → ``ab:MEM``);
  ô ghi ``R``, ``S``, ``I``, có thể kèm MIC/đường kính (``R (>8)``, ``>=32 R``).

Khóa không trùng (`lab_sample_id`, vi khuẩn): đã có thì bỏ qua ("Existing"), nhập lại cùng file tạo 0 bản ghi. Cột họ
tên người bệnh bị bỏ kèm cảnh báo (UC-51 E3); file nguồn bị xóa sau khi ghi sổ (mã người bệnh rõ, ADR-010 mở rộng).
"""

import re

import frappe
from frappe import _
from frappe.utils import cint, cstr, getdate, now_datetime

from tracecore.core.importer import Column, ImportKind, Issue, department_ref
from tracecore.microbiology import isolates, rules

KEY = "microbiology"
EXTRA_PREFIX = "ab:"
SEPARATOR = "|"
HEAD_FIELDS = ("patient_code", "birth_year", "sex", "department", "specimen_type", "collected_on")
# tiêu đề cột họ tên người bệnh (so sau khi bỏ dấu, không phân biệt hoa thường) — không lưu (BRU-HAI-005)
NAME_COLUMNS = (
	"patient name",
	"patient_name",
	"full name",
	"first name",
	"first_name",
	"last name",
	"last_name",
	"ho ten",
	"ho va ten",
	"ten benh nhan",
	"ten nguoi benh",
)
RESULT_TOKEN = re.compile(r"(?<![A-Z])([SIR])(?![A-Z])")
MIN_BIRTH_YEAR = 1900


def _key(values) -> str:
	lab = isolates.sample_id(values.get("lab_sample_id"))
	organism = "".join(cstr(values.get("organism")).split()).lower()
	return f"{lab}{SEPARATOR}{organism}" if lab and organism else ""


def _exists(code) -> bool:
	lab, _sep, organism = code.partition(SEPARATOR)
	# loài đã tắt vẫn tính "đã có" (nhập lại file cũ không báo lỗi danh mục)
	name = frappe.db.get_value("Organism", {"organism_code": organism}, "name")
	return bool(name) and isolates.exists(lab, name)


def is_extra(header) -> bool:
	return cstr(header).strip().lower().startswith(EXTRA_PREFIX) and len(cstr(header).strip()) > len(
		EXTRA_PREFIX
	)


def parse_cell(text) -> tuple[str | None, str | None]:
	"""(S/I/R, MIC) của một ô kháng sinh dạng rộng; không có S/I/R → (None, chữ gốc)."""
	upper = cstr(text).strip().upper()
	found = RESULT_TOKEN.findall(upper)
	if len(found) != 1:
		return None, cstr(text).strip()
	mic = RESULT_TOKEN.sub("", upper).replace("(", " ").replace(")", " ")
	return found[0], " ".join(mic.split()) or None


def _susceptibility(unit) -> tuple[list[dict], list[Issue]]:
	"""Dòng kháng sinh đồ của một chủng (dạng dài + dạng rộng) và lỗi theo dòng."""
	rows, issues, seen = [], [], {}

	def add(row_no, field, code, result, mic, name=None):
		code = rules.antibiotic_code(code)
		if code in seen and seen[code] != result:
			issues.append(
				Issue(
					row_no,
					"ANTIBIOTIC_CONFLICT",
					field,
					_("Antibiotic {0} has two different results for this isolate.").format(code),
				)
			)
			return
		if code not in seen:
			seen[code] = result
			rows.append({"antibiotic": code, "antibiotic_name": name, "result": result, "mic": mic})

	for row in unit:
		values = row.values
		code, result = values.get("antibiotic"), cstr(values.get("result")).strip().upper()
		if code and result in isolates.RESULTS:
			add(row.row, "antibiotic", code, result, values.get("mic"), values.get("antibiotic_name"))
		elif code or result:
			issues.append(
				Issue(
					row.row,
					"VALUE_INVALID",
					"result" if code else "antibiotic",
					_("Antibiotic code and a result S, I or R are needed together."),
				)
			)
		for header, text in (values.get("_extra") or {}).items():
			result, mic = parse_cell(text)
			code = header.strip()[len(EXTRA_PREFIX) :]
			if not result:
				issues.append(
					Issue(
						row.row,
						"VALUE_INVALID",
						header,
						_('Antibiotic {0}: "{1}" has no result S, I or R.').format(
							code.upper(), cstr(text)[:40]
						),
					)
				)
				continue
			add(row.row, header, code, result, mic)
	return rows, issues


def _validate(unit):
	head = unit[0]
	values = head.values
	issues = []
	if values.get("organism") and not isolates.organism_ref(values["organism"]):
		issues.append(
			Issue(
				head.row,
				"ORGANISM_NOT_FOUND",
				"organism",
				_("Organism code {0} is not in the Organism catalog.").format(values["organism"]),
			)
		)
	if values.get("department") and not department_ref(values["department"]):
		issues.append(
			Issue(
				head.row,
				"DEPARTMENT_NOT_FOUND",
				"department",
				_("Department {0} does not exist.").format(values["department"]),
			)
		)
	if values.get("collected_on") and getdate(values["collected_on"]) > getdate(now_datetime()):
		issues.append(
			Issue(head.row, "VALUE_INVALID", "collected_on", _("Collection date cannot be in the future."))
		)
	year = values.get("birth_year")
	if year is not None and not MIN_BIRTH_YEAR <= cint(year) <= now_datetime().year:
		issues.append(
			Issue(head.row, "VALUE_INVALID", "birth_year", _("Birth year {0} is not valid.").format(year))
		)
	rows, problems = _susceptibility(unit)
	issues += problems
	if not rows and not problems:
		# chủng không có kháng sinh đồ (vd hồ sơ quên ánh xạ cột kháng sinh) sẽ không bao giờ được gắn nhãn đa kháng,
		# và import lại sau đó chỉ ra "đã có": chặn như nhập tay
		issues.append(
			Issue(head.row, "VALUE_INVALID", "antibiotic", _("Enter at least one antibiotic result."))
		)
	return issues


def _write(unit):
	values = dict(unit[0].values)
	values["organism"] = isolates.organism_ref(values.get("organism"))
	values["department"] = department_ref(values.get("department"))
	susceptibility, _issues = _susceptibility(unit)
	doc = isolates.create(
		values, susceptibility, source=isolates.SOURCE_IMPORT, import_batch=frappe.flags.tc_import_batch
	)
	return doc.name


def import_kinds():
	"""Hook ``tracecore_import_kinds``."""
	return [
		ImportKind(
			key=KEY,
			label="Microbiology results",
			doctype=isolates.DOCTYPE,
			columns=[
				Column("lab_sample_id", "Lab Sample ID", required=True),
				Column(
					"organism", "Organism Code", required=True, help="WHONET organism code, for example eco."
				),
				Column("patient_code", "Patient Code", required=True),
				Column("birth_year", "Birth Year", kind="int"),
				Column("sex", "Sex", kind="select", options=("Male", "Female", "Other")),
				Column("department", "Department", required=True),
				Column("specimen_type", "Specimen Type"),
				Column("collected_on", "Collection Date", required=True, kind="date"),
				Column("antibiotic", "Antibiotic Code"),
				Column("antibiotic_name", "Antibiotic Name"),
				Column("result", "Result (S/I/R)"),
				Column("mic", "MIC or Zone"),
			],
			code_field="lab_sample_id",
			code_of=_key,
			group_of=_key,
			group_fields=HEAD_FIELDS,
			exists=_exists,
			validate=_validate,
			write=_write,
			extra_columns=is_extra,
			ignored_columns=NAME_COLUMNS,
			purge_file=True,
			roles=("TC R11", "System Manager"),
			guide=(
				_(
					"One row per isolate and antibiotic; rows with the same lab sample ID and organism form one isolate."
				),
				_(
					"WHONET files with one column per antibiotic: map each antibiotic column to ab:<code> in the mapping profile."
				),
				_("Patient names are not stored: name columns are ignored."),
			),
		)
	]
