"""Cấp Set ID hàng loạt cho bộ dụng cụ vật lý (M1, FEAT-016; FR-M1-05, .1, .2; BRU-ID-001, BRU-ID-006; UC-03).

- ``precheck``: điều kiện cấp, chỉ đọc (G5, G6): loại bộ có BOM hiệu lực hôm nay không chứa dụng cụ Ngừng sử dụng/không
  tương thích, tiền tố GS1 dùng được (G3), khoa sở hữu là Department lá đang dùng, cơ số tối đa 1-99 999, nguồn bộ
  Mới (0 chu trình) / Đang lưu hành (số chu trình ước tính ``0 ≤ n < cơ số``).
- ``issue_batch``: 1-``MAX_BATCH`` bộ trong **một** transaction có savepoint (G1): lỗi ở bất kỳ bộ nào → hoàn tác cả
  lô, kể cả bộ đếm ``tabSeries`` (InnoDB) nên không thủng số; ``getseries`` giữ khóa dòng series tới commit nên hai lô
  cùng loại bộ chạy lần lượt và serial trong một lô liên tiếp. Set Unit chỉ tạo qua đây (cờ ``flags.tc_set_issue``);
  trường vòng đời khởi tạo ở ``step_gate.init_unit`` (ADR-005). Không ghim BOM khi cấp (G4).

- ``dispose``: thanh lý bộ Mới tạo / Hết vòng đời (G14) qua ``step_gate.dispose``, rồi vô hiệu mã Set ID trong Code
  Registry (vẫn tra được, không in được, không bao giờ cấp lại; FR-M1-05.2, BRU-ID-001).
- ``summary``, ``history``: tóm tắt form và lịch sử vòng đời (G13), hiện thực ở ``set_history``.

Từ chối nghiệp vụ là ``BlockedError`` (mã trong ``core.errors.HTTP_STATUS``); tầng RPC (``v1.set_unit``) đổi thành body
lỗi + Audit ``Reject``.
"""

import frappe
from frappe import _
from frappe.utils import cint

from tracecore.core import audit, code_registry, step_gate
from tracecore.core.errors import Block, BlockedError
from tracecore.instrument import bom_versions, catalog, set_tags
from tracecore.instrument import set_type as set_type_service
from tracecore.instrument.set_history import history, summary  # công bố lại: giao diện set_units của plan

MAX_BATCH = 100
MAX_CYCLES_LIMIT = 99999
ORIGINS = ("New", "Existing")
SAVEPOINT = "tc_issue_set_units"
CYCLES_SOURCE = {"New": "Actual", "Existing": "Estimated"}
ISSUE_REASON = step_gate.ISSUE_EVENT  # cột reason của Audit Create (lô và từng bộ)
REASON_MAX = set_tags.REASON_MAX
DISPOSE_SAVEPOINT = "tc_dispose_set_unit"


def _whole(value) -> int | None:
	"""Số nguyên từ int hoặc chuỗi chữ số (có thể có khoảng trắng hai đầu); bool, float, chuỗi khác → None."""
	if isinstance(value, bool):
		return None
	if isinstance(value, int):
		return value
	if isinstance(value, str) and value.strip().isascii() and value.strip().isdigit():
		return int(value.strip())
	return None


def parse_count(value) -> int | None:
	"""Số bộ cần cấp: số nguyên (hoặc chuỗi chữ số từ hộp thoại Desk) trong 1..MAX_BATCH, ngược lại None."""
	number = _whole(value)
	return number if number is not None and 1 <= number <= MAX_BATCH else None


# --- Từ chối nghiệp vụ -------------------------------------------------------------------------------------------


def count_block() -> Block:
	return Block(
		"COUNT_OUT_OF_RANGE",
		_("Quantity out of range"),
		_("The number of sets must be a whole number from 1 to {0}.").format(MAX_BATCH),
		_("Enter a quantity from 1 to {0}; split larger orders into several batches.").format(MAX_BATCH),
	)


def _bom_block(set_type: str, items: list[dict]) -> Block:
	return Block(
		"SET_TYPE_BOM_INVALID",
		_("Set type cannot be issued"),
		_("Set type {0} has no usable BOM effective today.").format(set_type),
		_(
			"Save a new BOM version effective today without retired or incompatible instruments, then issue again."
		),
		items=items,
	)


def _department_block(department) -> Block:
	return Block(
		"DEPARTMENT_INVALID",
		_("Owning department not valid"),
		_("Department {0} does not exist, is a group or is disabled.").format(
			department if isinstance(department, str) and department else "-"
		),
		_("Choose an enabled department that is not a group."),
	)


def _max_cycles_block(reason: str) -> Block:
	return Block(
		"MAX_CYCLES_INVALID",
		_("Cycle numbers not valid"),
		reason,
		_(
			"Enter the max cycles as a whole number from 1 to {0}, and cycles used below the max cycles."
		).format(MAX_CYCLES_LIMIT),
	)


def _exhausted_block(set_type: str) -> Block:
	return Block(
		"SET_SERIES_EXHAUSTED",
		_("Set ID numbers used up"),
		_("All 999999 Set ID numbers of set type {0} have been issued; nothing was issued.").format(set_type),
		_("Create a new set type code for further sets."),
	)


# --- Kiểm điều kiện ----------------------------------------------------------------------------------------------


def _bom_items(set_type: str, method: str | None, version: int) -> list[dict]:
	"""Lỗi từng dòng của BOM `version`: dụng cụ Ngừng sử dụng / không tương thích phương pháp (một truy vấn)."""
	rows = frappe.db.sql(
		"""
		select b.position, b.instrument, i.status, group_concat(m.method separator '\n') as methods
		from `tabSet BOM Item` b
		left join `tabInstrument` i on i.name = b.instrument
		left join `tabInstrument Compatible Method` m
			on m.parent = b.instrument and m.parenttype = 'Instrument' and m.parentfield = 'compatible_methods'
		where b.set_type = %s and b.bom_version = %s
		group by b.name, b.position, b.instrument, i.status
		order by b.position asc, b.name asc
		""",
		(set_type, version),
	)
	items = []
	for position, instrument, status, methods in rows:
		methods = set(filter(None, (methods or "").split("\n")))
		if status == "Retired" or status is None:
			items.append(
				{
					"row": cint(position),
					"instrument": instrument,
					"code": "RETIRED",
					"message": _("Instrument {0} is retired and cannot be in an issued set.").format(
						instrument
					),
				}
			)
		if method and method not in catalog.families(methods):
			items.append(
				{
					"row": cint(position),
					"instrument": instrument,
					"code": "INCOMPATIBLE",
					"message": _(
						"Instrument {0} ({1}) is not compatible with the set type method {2}."
					).format(instrument, ", ".join(catalog.ordered_methods(methods)) or "—", _(method)),
				}
			)
	return items


def _check_department(department) -> str:
	row = (
		frappe.db.get_value("Department", department, ["is_group", "disabled"], as_dict=True)
		if isinstance(department, str) and department
		else None
	)
	if not row or cint(row.is_group) or cint(row.disabled):
		raise BlockedError(_department_block(department))
	return department


def _check_max_cycles(value, derived) -> int:
	number = derived if value in (None, "") else _whole(value)
	if number is None or not 1 <= number <= MAX_CYCLES_LIMIT:
		raise BlockedError(
			_max_cycles_block(
				_("Max cycles must be a whole number from 1 to {0}.").format(MAX_CYCLES_LIMIT)
				if value not in (None, "")
				else _("Max cycles is required: it cannot be derived from the instruments of this set type.")
			)
		)
	return number


def _check_cycles_used(origin, value, max_cycles) -> int:
	if origin == "New":
		if value not in (None, "") and _whole(value) != 0:
			raise BlockedError(_max_cycles_block(_("A new set has used 0 cycles.")))
		return 0
	number = _whole(value)
	if number is None or not 0 <= number < max_cycles:
		raise BlockedError(
			_max_cycles_block(
				_("Estimated cycles used must be a whole number from 0 to {0}.").format(max_cycles - 1)
			)
		)
	return number


def precheck(
	set_type: str, department: str | None = None, max_cycles=None, origin: str = "New", cycles_used=0
) -> dict:
	"""Điều kiện cấp Set ID cho loại bộ (G3, G5, G6); không ghi gì.

	Trả ``{set_type, type_code, department, max_cycles, origin, cycles_used, bom_version, derived_max_cycles,
	warnings}``. Lỗi → ``BlockedError`` theo thứ tự ``SET_TYPE_NOT_FOUND`` → ``GS1_PREFIX_NOT_CONFIGURED`` →
	``SET_TYPE_BOM_INVALID`` (``items = [{row, instrument, code: NO_EFFECTIVE_BOM | RETIRED | INCOMPATIBLE, message}]``)
	→ ``DEPARTMENT_INVALID`` → ``MAX_CYCLES_INVALID``. ``department`` trống → khoa của loại bộ; ``max_cycles`` trống →
	cơ số suy ra (``set_type.derived_max_cycles``), không suy ra được → bắt buộc nhập; lớn hơn cơ số suy ra → cảnh báo
	``MAX_CYCLES_ABOVE_DERIVED`` (không chặn). ``origin`` ngoài ``ORIGINS`` → ``ValidationError`` (lỗi tham số).
	"""
	if origin not in ORIGINS:
		frappe.throw(_("Set origin must be one of: {0}.").format(", ".join(ORIGINS)))
	header = (
		frappe.db.get_value(
			"Instrument Set Type", set_type, ["name", "type_code", "method", "department"], as_dict=True
		)
		if isinstance(set_type, str) and set_type
		else None
	)
	if not header:
		raise BlockedError(bom_versions.not_found_block(set_type))
	block = code_registry.gs1_prefix_block(code_registry.company_prefix(), "set")
	if block:
		raise BlockedError(block)

	version = bom_versions.effective_version(header.name)
	if not version:
		items = [
			{
				"row": None,
				"instrument": None,
				"code": "NO_EFFECTIVE_BOM",
				"message": _("Set type {0} has no BOM version effective today.").format(header.name),
			}
		]
	else:
		items = _bom_items(header.name, header.method, version)
	if items:
		raise BlockedError(_bom_block(header.name, items))

	department = _check_department(department or header.department)
	derived = set_type_service.derived_max_cycles(header.name, version)["value"]
	max_cycles = _check_max_cycles(max_cycles, derived)
	cycles_used = _check_cycles_used(origin, cycles_used, max_cycles)
	warnings = []
	if derived and max_cycles > derived:
		warnings.append(
			{
				"code": "MAX_CYCLES_ABOVE_DERIVED",
				"message": _(
					"Max cycles {0} is higher than {1}, the lowest max cycles of the instruments in the BOM."
				).format(max_cycles, derived),
			}
		)
	return {
		"set_type": header.name,
		"type_code": header.type_code,
		"department": department,
		"max_cycles": max_cycles,
		"origin": origin,
		"cycles_used": cycles_used,
		"bom_version": version,
		"derived_max_cycles": derived,
		"warnings": warnings,
	}


# --- Cấp ---------------------------------------------------------------------------------------------------------


def _insert_units(
	set_type, count, department, max_cycles, origin="New", cycles_used=0, fields=None
) -> list[str]:
	"""Tạo `count` Set Unit (không savepoint, không kiểm điều kiện); trả Set ID theo thứ tự cấp."""
	names = []
	for _index in range(count):
		doc = frappe.new_doc("Set Unit")
		doc.update(fields or {})
		doc.update({"set_type": set_type, "department": department, "max_cycles": max_cycles})
		doc.flags.tc_set_issue = True
		step_gate.init_unit(doc, cycles_used)
		doc.cycles_source = CYCLES_SOURCE[origin]
		doc.insert(ignore_permissions=True)  # autoname → code_registry.next_set_id + register
		names.append(doc.name)
	return names


def _create_units(
	set_type, count, department=None, max_cycles=None, origin="New", cycles_used=0, fields=None
):
	"""Đường ghi của ``issue_batch`` không kèm ``precheck``, cho factory test (``tests.factories.make_set_unit``) dựng
	bộ như dữ liệu có trước FEAT-016 (loại bộ chưa có BOM/khoa). Vẫn qua cờ cấp + ``step_gate.init_unit`` và savepoint;
	`fields`: trường không phải vòng đời (vd ``is_loaner``) — trường vòng đời truyền vào bị ``init_unit`` đặt lại.
	Không dùng cho nghiệp vụ: nghiệp vụ (kể cả import FEAT-011) gọi ``issue_batch``.
	"""
	frappe.db.savepoint(SAVEPOINT)
	try:
		return _insert_units(set_type, count, department, max_cycles, origin, cycles_used, fields)
	except Exception:
		frappe.db.rollback(save_point=SAVEPOINT)
		raise


def issue_batch(
	set_type: str, count, department: str | None = None, max_cycles=None, origin: str = "New", cycles_used=0
) -> list[str]:
	"""Cấp Set ID cho `count` bộ của loại bộ `set_type` trong một transaction (FR-M1-05, .1; G1); trả Set ID theo thứ tự.

	`count` ngoài 1..MAX_BATCH hoặc không phải số nguyên → ``BlockedError(COUNT_OUT_OF_RANGE)``; rồi ``precheck``. Mỗi bộ
	một Set Unit Mới tạo (Audit ``Create`` lý do ``issue``) + dòng ``Code Registry``; thêm một Audit ``Create`` của lô
	trên ``Instrument Set Type`` (``new = {count, first, last, department, origin}``). Lỗi ở bất kỳ bộ nào → hoàn tác
	savepoint (không còn Set Unit/sổ/Audit/bộ đếm của lô) rồi ném lại; hết dải series → ``SET_SERIES_EXHAUSTED``.
	"""
	number = parse_count(count)
	if number is None:
		raise BlockedError(count_block())
	ctx = precheck(set_type, department, max_cycles, origin, cycles_used)
	frappe.db.savepoint(SAVEPOINT)
	try:
		names = _insert_units(
			ctx["set_type"], number, ctx["department"], ctx["max_cycles"], origin, ctx["cycles_used"]
		)
		audit.log(
			"Create",
			"Instrument Set Type",
			ctx["set_type"],
			new={
				"count": number,
				"first": names[0],
				"last": names[-1],
				"department": ctx["department"],
				"origin": origin,
			},
			reason=ISSUE_REASON,
		)
	except code_registry.SeriesExhaustedError:
		frappe.db.rollback(save_point=SAVEPOINT)
		raise BlockedError(_exhausted_block(ctx["set_type"])) from None
	except Exception:
		frappe.db.rollback(save_point=SAVEPOINT)
		raise
	return names


# --- Thanh lý (G14) ------------------------------------------------------------------------------------------------


def _dispose_reason_block() -> Block:
	return Block(
		"REASON_REQUIRED",
		_("Reason is required"),
		_("A reason of 1 to {0} characters is required to dispose a set.").format(REASON_MAX),
		_("Enter why the set is disposed, at most {0} characters.").format(REASON_MAX),
	)


def dispose(set_unit: str, reason: str) -> dict:
	"""Thanh lý bộ (FR-M1-06, FR-M1-05.2; BRU-ID-001; G14); trả ``{set_unit, status}``.

	Bộ không có → ``SET_NOT_FOUND``; lý do (bỏ khoảng trắng) rỗng hoặc quá ``REASON_MAX`` ký tự → ``REASON_REQUIRED``;
	trạng thái ngoài Mới tạo / Hết vòng đời hoặc còn Cycle ID → ``STATUS_INVALID_FOR_ACTION`` (từ ``step_gate.dispose``).
	Đổi trạng thái (``step_gate``) và vô hiệu mã Set ID (``code_registry.disable``, lý do = lý do thanh lý) trong một
	savepoint: một bước lỗi thì không bước nào còn. Bộ cũ chưa có dòng Code Registry vẫn thanh lý được.
	"""
	if not isinstance(set_unit, str) or not set_unit or not frappe.db.exists("Set Unit", set_unit):
		raise BlockedError(set_tags.not_found_block(set_unit))
	text = reason.strip() if isinstance(reason, str) else ""
	if not text or len(text) > REASON_MAX:
		raise BlockedError(_dispose_reason_block())
	frappe.db.savepoint(DISPOSE_SAVEPOINT)
	try:
		step_gate.dispose(set_unit, text)
		if frappe.db.get_value("Code Registry", set_unit, "status") == "Active":
			code_registry.disable(set_unit, text)
	except Exception:
		frappe.db.rollback(save_point=DISPOSE_SAVEPOINT)
		raise
	return {"set_unit": set_unit, "status": "Disposed"}
