"""Kiểm dữ liệu, khóa kỳ và phân bổ theo ngày của Cost Entry (FEAT-044; FR-M7-01 .1-.4, FR-M7-02 .1-.2; UC-27; A-47 C4-C7).

Controller `CostEntry` chỉ gọi vào đây. `amount_in` / `split` / `allocated_to` là đầu vào cho báo cáo `Cost by Target` và
Cost Sheet (FEAT-046): chi phí theo kỳ chia đều theo ngày, ngày cuối nhận phần dư để tổng khớp từng đồng.
"""

import frappe
from frappe import _
from frappe.utils import cint, date_diff, flt, formatdate, getdate

DOCTYPE = "Cost Entry"
SETTINGS = "Cost Settings"
PERCENT_PRECISION = 3


def validate(doc):
	"""Dữ liệu hợp lệ trước khi lưu (Nháp). Trường bắt buộc do Frappe kiểm sau, nên ở đây chịu được giá trị trống."""
	check_category(doc)
	check_numbers(doc)
	check_period(doc)
	compute_quantity(doc)
	check_allocations(doc)
	check_period_unlocked(doc)


def before_submit(doc):
	"""Ghi sổ: cần ít nhất một dòng phân bổ (tổng 100 % đã kiểm khi lưu); khoản từ chứng từ khác chỉ ghi sổ khi chứng từ đó còn hiệu lực."""
	if not doc.allocations:
		frappe.throw(_("Add at least one allocation target before submitting the cost entry."))
	if doc.source_doctype and doc.source_name:
		if frappe.db.get_value(doc.source_doctype, doc.source_name, "docstatus") != 1:
			frappe.throw(
				_(
					"The source document {0} {1} is not submitted, so this cost entry cannot be submitted."
				).format(_(doc.source_doctype), doc.source_name)
			)


def check_category(doc):
	if doc.category and frappe.db.get_value("Cost Category", doc.category, "is_active") == 0:
		frappe.throw(_("Cost category {0} is not active.").format(doc.category))


def check_numbers(doc):
	if flt(doc.amount) < 0:
		frappe.throw(_("Amount cannot be negative."))
	if doc.source == "Meter":
		for label, value in (
			(_("Opening Reading"), doc.opening_reading),
			(_("Closing Reading"), doc.closing_reading),
		):
			if value is None or value == "":
				frappe.throw(_("{0} is required for a meter source.").format(label))
			if flt(value) < 0:
				frappe.throw(_("{0} cannot be negative.").format(label))
		if flt(doc.closing_reading) < flt(doc.opening_reading):
			frappe.throw(_("Closing Reading cannot be less than Opening Reading."))


def check_period(doc):
	if doc.period_from and doc.period_to and getdate(doc.period_to) < getdate(doc.period_from):
		frappe.throw(_("Period To cannot be before Period From."))


def compute_quantity(doc):
	"""Lượng tiêu thụ = chỉ số cuối trừ chỉ số đầu khi nguồn là đồng hồ (FR-M7-01.3); nguồn khác không có lượng."""
	doc.quantity = flt(doc.closing_reading) - flt(doc.opening_reading) if doc.source == "Meter" else 0


def check_allocations(doc):
	"""Mỗi dòng có loại và đối tượng, 0 < % ≤ 100, không trùng đối tượng; có dòng thì tổng phải đúng 100 (FR-M7-02.1)."""
	seen = set()
	total = 0.0
	for row in doc.allocations:
		if not row.target_type or not row.target:
			frappe.throw(_("Row {0}: choose the target type and the target.").format(row.idx))
		if not 0 < flt(row.percent) <= 100:
			frappe.throw(_("Row {0}: percent must be greater than 0 and at most 100.").format(row.idx))
		key = (row.target_type, row.target)
		if key in seen:
			frappe.throw(
				_("Row {0}: {1} {2} is already allocated in this entry.").format(
					row.idx, _(row.target_type), row.target
				)
			)
		seen.add(key)
		total += flt(row.percent)
	if doc.allocations and flt(total, PERCENT_PRECISION) != 100:
		frappe.throw(
			_(
				"The allocation percentages total {0} %, but must total 100 %. Adjust the rows and save again."
			).format(flt(total, PERCENT_PRECISION))
		)


def locked_until():
	"""Ngày khóa kỳ của `Cost Settings` hoặc None khi chưa khóa (Frappe trả ngày 0001-01-01 cho Date trống)."""
	value = frappe.db.get_single_value(SETTINGS, "locked_until")
	return getdate(value) if value and getdate(value).year > 1 else None


def check_period_open(period_from):
	"""Kỳ bắt đầu từ ngày `period_from` đã khóa (≤ `Cost Settings.locked_until`) thì chặn (UC-27 E3)."""
	locked = locked_until()
	if period_from and locked and getdate(period_from) <= getdate(locked):
		frappe.throw(
			_(
				"The cost period starting {0} is closed (locked until {1}). Ask the Head of Department to move the lock date back in Cost Settings."
			).format(formatdate(period_from), formatdate(locked)),
			title=_("Period Closed"),
		)


def check_period_unlocked(doc):
	"""Tạo, sửa hoặc ghi sổ không được chạm kỳ đã khóa: kiểm cả kỳ cũ khi chuyển bản Nháp sang kỳ khác."""
	check_period_open(doc.period_from)
	before = doc.get_doc_before_save()
	if before:
		check_period_open(before.period_from)


def amount_in(entry, date_from, date_to):
	"""Phần chi phí của `entry` rơi vào khoảng [date_from, date_to], chia đều theo ngày trong kỳ (FR-M7-01.2).

	Làm tròn VND không lẻ: mỗi ngày nhận phần nguyên, ngày cuối của kỳ nhận thêm phần dư để cộng lại đúng số tiền.
	"""
	start, end = getdate(entry.period_from), getdate(entry.period_to)
	low, high = max(start, getdate(date_from)), min(end, getdate(date_to))
	if low > high:
		return 0
	total = cint(round(flt(entry.amount)))
	days = date_diff(end, start) + 1
	per_day = total // days
	amount = per_day * (date_diff(high, low) + 1)
	if high == end:
		amount += total - per_day * days
	return amount


def split(entry, date_from, date_to):
	"""{(target_type, target): số tiền} của phần chi phí trong khoảng ngày; dòng cuối nhận phần dư nên tổng khớp `amount_in`."""
	total = amount_in(entry, date_from, date_to)
	parts = {}
	given = 0
	rows = list(entry.allocations)
	for number, row in enumerate(rows, 1):
		share = total - given if number == len(rows) else cint(round(total * flt(row.percent) / 100))
		parts[(row.target_type, row.target)] = share
		given += share
	return parts


def allocated_to(entry, target_type, target, date_from, date_to):
	"""Phần chi phí của `entry` gắn cho một đối tượng trong khoảng ngày (0 nếu không gắn)."""
	return split(entry, date_from, date_to).get((target_type, target), 0)
