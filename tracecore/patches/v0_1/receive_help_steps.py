"""#1832 T1-02: bài hướng dẫn T1 còn nguyên nội dung mặc định cũ đổi sang 5 bước đúng màn; bài R10 đã sửa thì giữ."""

import frappe

from tracecore.ui import station_help

OLD_STEPS = (
	"Scan your employee card to open the station.",
	"Scan the Set ID on each returned set.",
	"Check the receipt details and mark missing or damaged instruments.",
	"Confirm to send the set to washing.",
)


def _texts(steps, lang):
	return [frappe._(step, lang=lang) for step in steps]


def execute():
	if not frappe.get_meta("Help Article").has_field("tc_station_key"):
		return
	for row in frappe.get_all(
		"Help Article", filters={"tc_station_key": "RECEIVE"}, fields=["name", "content"]
	):
		found = [step["text"] for step in station_help.steps_from_html(row.content)]
		for lang in ("en", "vi"):
			if found == _texts(OLD_STEPS, lang):
				frappe.db.set_value(
					"Help Article",
					row.name,
					"content",
					station_help.default_content(station_help.DEFAULT_STEPS["RECEIVE"], lang=lang),
					update_modified=False,
				)
				break
