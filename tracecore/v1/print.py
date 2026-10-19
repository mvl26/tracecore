"""RPC tracecore.v1.print.* — dành cho Station Agent (role TC Agent, API key)."""

import base64

import frappe

from tracecore.core import print as core_print
from tracecore.core.idempotency import idempotent
from tracecore.v1._common import AGENT_ROLE, require_role, require_station


@frappe.whitelist(methods=["POST"])
@idempotent
def test_label(station, client_ts=None):
	"""Tạo Print Job nhãn thử cho trạm; trả ZPL và ảnh xem trước (base64)."""
	require_role(AGENT_ROLE)
	require_station(station)
	label = core_print.render_test_label(station)
	job = core_print.create_job(
		station, label["zpl"], {"giai": label["giai"], "hri": label["hri"]}, "test-label"
	)
	return {
		"print_job": job,
		"giai": label["giai"],
		"zpl": label["zpl"],
		"preview_png_b64": base64.b64encode(label["preview_png"]).decode("ascii"),
	}


@frappe.whitelist(methods=["POST"])
@idempotent
def ack(print_job, status, output_mode, client_ts=None, output_ref=None, error=None):
	"""Agent báo kết quả in."""
	require_role(AGENT_ROLE)
	return core_print.ack(print_job, status, output_mode, output_ref=output_ref, error=error)
