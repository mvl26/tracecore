"""Ticket 03/11/2026: bài hướng dẫn chung còn nguyên nội dung mặc định cũ thêm bước mở đúng địa chỉ trạm (?station=);
bài R10 đã sửa thì giữ."""

import frappe

from tracecore.ui import station_help

OLD_STEPS = (
	"Scan your employee card to open the station.",
	"Scan the code in the box at the top of the screen.",
	"Read the result: a red message means stop and follow the action shown.",
	"Press Help and then Report a problem if the screen does not work as expected.",
)


def _texts(steps, lang):
	return [frappe._(step, lang=lang) for step in steps]


def execute():
	if not frappe.get_meta("Help Article").has_field("tc_station_key"):
		return
	for row in frappe.get_all(
		"Help Article", filters={"tc_station_key": station_help.GENERAL}, fields=["name", "content"]
	):
		found = [step["text"] for step in station_help.steps_from_html(row.content)]
		for lang in ("en", "vi"):
			if found == _texts(OLD_STEPS, lang):
				frappe.db.set_value(
					"Help Article",
					row.name,
					"content",
					station_help.default_content(station_help.DEFAULT_STEPS[station_help.GENERAL], lang=lang),
					update_modified=False,
				)
				break
