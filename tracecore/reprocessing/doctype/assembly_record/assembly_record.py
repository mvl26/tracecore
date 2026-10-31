"""Assembly Record: chứng từ kiểm đếm theo BOM tại trạm T3 (M2, FEAT-020, UC-07); ghi sổ thì ghi cổng T3.

Thay stub của FEAT-018 và giữ tương thích: ``set_unit``, ``cycle_no``, ``result`` (``Pass``/``Fail``) và ``notes``
như cũ. Bản nháp là phiên kiểm đếm của (bộ, chu trình hiện hành); mọi số (``bom_qty``, ``line_status``,
``missing_qty``, ``has_shortage``, ``shortage_summary``) do `validate` tính lại, không tin client. Xác nhận thiếu của
R02 chỉ ghi qua `tracecore.reprocessing.assembly` (cờ ``flags.tc_assembly``) vì cần PIN. Cổng T3 vẫn do
`tracecore.core.step_gate` ghi (ADR-005).
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

from tracecore.core import error_codes, step_gate

FLAG = "tc_assembly"
CONFIRM_FIELDS = (
	"shortage_confirmed",
	"shortage_reason",
	"shortage_confirmed_by",
	"shortage_confirmed_at",
	"shortage_confirmed_for",
)
SERVICE_FIELDS = ("nc_pending", "foreign_instruments", "station", "assembled_by_user")


class AssemblyRecord(Document):
	def validate(self):
		if not self.set_unit or not frappe.db.exists("Set Unit", self.set_unit):
			return  # kiểm trường bắt buộc/liên kết sẽ báo
		unit = frappe.db.get_value(
			"Set Unit", self.set_unit, ["current_cycle_no", "set_type", "cycle_bom_version"], as_dict=True
		)
		current = cint(unit.current_cycle_no)
		if not current:
			frappe.throw(_("No cycle has been started for Set Unit {0}.").format(self.set_unit))
		if self.is_new():
			self.cycle_no = current
		elif cint(self.cycle_no) != current:
			frappe.throw(
				_("Set Unit {0} is no longer in cycle {1}; create a new Assembly Record.").format(
					self.set_unit, self.cycle_no
				)
			)
		self.set_type = unit.set_type
		self._count_lines(unit)
		self._guard_confirmation()

	# --- kiểm đếm theo BOM (FR-M2-05.1, .2) ---

	def _bom(self, unit):
		"""``(phiên bản, {mã dụng cụ: số lượng})`` của BOM đã ghim cho chu trình; chưa ghim BOM có dòng → ``(0, {})``."""
		version = cint(self.bom_version) or cint(unit.cycle_bom_version)
		if not version and self.get("lines"):
			version = cint(frappe.db.get_value("Instrument Set Type", unit.set_type, "current_bom_version"))
		if not version:
			return 0, {}
		rows = frappe.get_all(
			"Set BOM Item",
			filters={"set_type": unit.set_type, "bom_version": version},
			fields=["instrument", "qty"],
		)
		return version, {row.instrument: cint(row.qty) for row in rows}

	def _count_lines(self, unit):
		version, bom = self._bom(unit)
		lines = self.get("lines") or []
		if not bom:
			if lines:
				frappe.throw(_("Set type {0} has no BOM to count against.").format(unit.set_type))
			self.bom_version = 0
			self._summarize()
			return
		self.bom_version = version
		seen = set()
		for line in lines:
			if line.instrument not in bom:
				frappe.throw(
					_("{0} is not in BOM version {1} of this set type.").format(line.instrument, version)
				)
			if line.instrument in seen:
				frappe.throw(_("Instrument {0} appears on more than one line.").format(line.instrument))
			seen.add(line.instrument)
		missing = sorted(set(bom) - seen)
		if missing:
			frappe.throw(_("The count must cover every BOM line; missing: {0}.").format(", ".join(missing)))
		names = dict(
			frappe.get_all(
				"Instrument",
				filters={"name": ["in", sorted(seen)]},
				fields=["name", "instrument_name"],
				as_list=True,
			)
		)
		for line in lines:
			line.instrument_name = names.get(line.instrument)
			self._count_line(line, bom[line.instrument])
		self._summarize()

	def _count_line(self, line, bom_qty):
		line.bom_qty = bom_qty
		for field in ("actual_qty", "damaged_qty", "replaced_qty"):
			value = cint(line.get(field))
			if value < 0 or value > 9999:
				frappe.throw(
					_("{0}: quantities must be whole numbers between 0 and 9999.").format(line.instrument)
				)
			line.set(field, value)
		if line.replaced_qty > line.damaged_qty:
			frappe.throw(
				_("{0}: replaced quantity ({1}) cannot exceed damaged quantity ({2}).").format(
					line.instrument, line.replaced_qty, line.damaged_qty
				)
			)
		if line.replaced_qty and not line.replacement_instrument:
			line.replacement_instrument = line.instrument  # thay đúng mã từ kho dự phòng
		if not line.replaced_qty:
			line.replacement_instrument = None
		if not line.damaged_qty:
			line.disposition = None
		elif line.counted and not line.disposition:
			frappe.throw(
				_("{0}: choose Repair or Dispose for the damaged instrument(s).").format(line.instrument)
			)
		if not line.counted:
			line.line_status, line.missing_qty = None, 0
		elif line.actual_qty < bom_qty:
			line.line_status, line.missing_qty = "Short", bom_qty - line.actual_qty
		elif line.actual_qty > bom_qty:
			line.line_status, line.missing_qty = "Over", 0
		else:
			line.line_status, line.missing_qty = "Enough", 0

	def _summarize(self):
		short = [line for line in (self.get("lines") or []) if line.line_status == "Short"]
		self.has_shortage = 1 if short else 0
		self.shortage_summary = (
			"\n".join(
				f"{line.instrument_name or line.instrument} ({line.instrument}) x {line.missing_qty}"
				for line in short
			)
			if short
			else None
		)

	# --- xác nhận thiếu chỉ qua dịch vụ có PIN (FR-M2-06.1, BRU-REP-003) ---

	def _guard_confirmation(self):
		before = None if self.is_new() else self.get_doc_before_save()
		confirming = cint(self.shortage_confirmed) and (
			before is None or any(self._differs(before, field) for field in CONFIRM_FIELDS)
		)
		if confirming and not self.flags.get(FLAG):
			frappe.throw(_("The shortage can only be confirmed by R02 at the station with a PIN."))
		if confirming and not self.shortage_confirmed_for:
			self.shortage_confirmed_for = self.shortage_summary
		# số lượng đổi làm thiếu khác lúc R02 xác nhận thì xác nhận cũ mất hiệu lực
		if cint(self.shortage_confirmed) and (
			not self.has_shortage or (self.shortage_confirmed_for or "") != (self.shortage_summary or "")
		):
			for field in CONFIRM_FIELDS:
				self.set(field, 0 if field == "shortage_confirmed" else None)

	def _differs(self, before, field):
		return (before.get(field) or None) != (self.get(field) or None)

	# --- ghi sổ (FR-M2-06, FR-M2-00.5) ---

	def before_submit(self):
		if not self.result:
			frappe.throw(_("Result is required."), frappe.MandatoryError)
		lines = self.get("lines") or []
		if self.branch:
			if self.result != "Fail":
				frappe.throw(_("A set sent to repair or disposal cannot pass assembly."))
			if not (self.branch_reason or "").strip():
				frappe.throw(_("Give the reason for sending the set to repair or disposal."))
		elif self.result == "Pass":
			uncounted = [line.instrument for line in lines if not line.counted]
			if uncounted:
				frappe.throw(_("Count every BOM line first; not counted: {0}.").format(", ".join(uncounted)))
			# FEAT-052 A-71: DC-001 viện đặt Cảnh báo thì không cần R02 xác nhận; nhãn vẫn in dòng THIẾU
			if self.has_shortage and not self.shortage_confirmed and error_codes.is_blocking("DC-001"):
				frappe.throw(
					_("Missing instruments need the confirmation of R02 before the set can be packed.")
				)
		if self.shortage_confirmed and not (
			self.shortage_confirmed_by and (self.shortage_reason or "").strip()
		):
			frappe.throw(_("The confirmation of a shortage needs the confirming user and a reason."))

	def on_submit(self):
		step_gate.record(
			self.set_unit, "T3", self.result, self.doctype, self.name, self.station, self.client_ts
		)

	def before_cancel(self):
		# Hủy chứng từ phải đưa cổng T3 về lại; chưa hỗ trợ (cùng stub FEAT-018).
		frappe.throw(_("Assembly Record cannot be cancelled in this version."))
