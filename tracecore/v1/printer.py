"""RPC tracecore.v1.printer.* — đổi cuộn nhãn của máy in tại trạm T4 (FR-M2-08.2, AC-9)."""

import frappe
from frappe import _

from tracecore.core import gs1
from tracecore.core import print as core_print
from tracecore.core.client_time import parse_client_ts
from tracecore.core.errors import Block, BlockedError
from tracecore.core.idempotency import idempotent
from tracecore.v1._common import PACKING_ROLES, BadRequestError, require_any_role, run_at_step

STEP = "T4"


def _printer_unknown(reason, action):
	return BlockedError(Block("ROLL_PRINTER_AMBIGUOUS", _("Printer not identified"), reason, action))


def change_roll(roll_code, station, printer=None):
	"""Đổi cuộn nhãn `roll_code` cho máy in của `station`; trả kết quả `core.print.set_roll`.

	`printer` (tên Printer) do người gọi chọn, phải thuộc `station`. Không truyền thì trạm phải có đúng một máy in
	hoạt động: không có máy nào hoặc nhiều hơn một → ``ROLL_PRINTER_AMBIGUOUS`` (lý do nói rõ trường hợp nào).
	Dùng chung cho `printer.set_roll` và `pack.scan` (mã ``CN-``).
	"""
	if printer is not None and not isinstance(printer, str):
		raise BadRequestError(_("printer must be a printer name."))
	active = [row["name"] for row in core_print.station_printers(station)]
	if printer:
		if frappe.db.get_value("Printer", printer, "station") != station:
			raise _printer_unknown(
				_("Printer {0} is not a printer of station {1}.").format(printer, station),
				_("Choose a printer of this station."),
			)
	elif not active:
		raise _printer_unknown(
			_("Station {0} has no active printer to load the roll into.").format(station),
			_("Ask R10 to set up a printer for this station."),
		)
	elif len(active) > 1:
		raise _printer_unknown(
			_("Station {0} has {1} active printers, so it is not clear which one got the roll.").format(
				station, len(active)
			),
			_("Ask R10 to choose the printer for this roll."),
		)
	else:
		printer = active[0]
	return core_print.set_roll(printer, gs1.clean_scan(roll_code))


@frappe.whitelist(methods=["POST"])
@idempotent
def set_roll(roll_code, station, printer=None, client_ts=None):
	"""Ghi nhận đổi cuộn nhãn (mã ``CN-#####``) và phát hành nhãn đang chờ đúng loại nhãn (AC-9).

	Trả ``{"ok": true, "roll": {"printer", "label_type", "method", "released_jobs"}}``; kiosk gửi từng
	``released_jobs`` tới Station Agent. Từ chối nghiệp vụ: ``ROLL_NOT_FOUND`` (404), ``ROLL_NOT_LABEL`` (422),
	``ROLL_PRINTER_AMBIGUOUS`` (409), ``STATION_WRONG_STEP`` (422).
	"""
	require_any_role(*PACKING_ROLES)
	timestamp = parse_client_ts(client_ts)
	return run_at_step(
		STEP,
		station,
		timestamp,
		lambda: {"ok": True, "roll": change_roll(roll_code, station, printer)},
		raw=roll_code,
	)
