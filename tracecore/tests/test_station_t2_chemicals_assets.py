"""Màn T2: tình trạng hóa chất, tải lại lô, nháp danh sách nạp dở (ticket T2 31/10/2026; A-72)."""

import csv
import re

import frappe
from frappe.tests.utils import FrappeTestCase

T2_JS = ("public", "js", "station_t2.js")
STRINGS = (
	"Reload chemical lots",
	"Chemical lots reloaded",
	"Chemicals of program {0}",
	"Stock enough",
	"Stock short",
	"Lots expired",
	"Needs {0} {1} per cycle, in stock {2} {1}",
	"No valid lot of chemical {0} - {1}",
	"Program {0} cannot start without a lot of this chemical. Check the list of chemicals below.",
	"Receive a new lot into stock or call R02, then tap Reload chemical lots.",
	"The list of sets was restored from this station session",
)


def _read(*parts):
	with open(frappe.get_app_path("tracecore", *parts), encoding="utf-8") as handle:
		return handle.read()


class TestStationT2ChemicalsAssets(FrappeTestCase):
	def test_script_calls_the_refresh_and_draft_rpcs(self):
		script = _read(*T2_JS)
		for name in (
			"tracecore.v1.wash.refresh_lots",
			"tracecore.v1.wash.save_draft",
			"tracecore.v1.wash.draft",
			'"t2-refresh-lots"',
		):
			self.assertIn(name, script)

	def test_lots_are_looked_up_again_when_the_program_changes(self):
		script = _read(*T2_JS)
		start = script.index('target.id === "tc-t2-program"')
		self.assertIn("this.refreshLots", script[start : start + 400])

	def test_new_strings_are_used_and_translated(self):
		script = _read(*T2_JS)
		path = frappe.get_app_path("tracecore", "translations", "vi.csv")
		with open(path, encoding="utf-8", newline="") as handle:
			translated = {row[0] for row in csv.reader(handle) if row}
		for text in STRINGS:
			self.assertIn(f'"{text}"', script, msg=text)
			self.assertIn(text, translated, msg=text)

	def test_status_is_not_shown_by_colour_alone(self):
		script = _read(*T2_JS)
		self.assertIn("tc-chem-status", script)
		self.assertIsNone(re.search(r"(?<![&\w])#[0-9a-fA-F]{3,8}\b", script))
