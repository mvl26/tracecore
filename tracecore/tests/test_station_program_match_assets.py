"""Màn T2, T5: chương trình theo máy của loại bộ (A-110; FR-M2-03.7/.8, FR-M2-09.7/.8)."""

import csv
import re

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore import hooks

HELPER = ("public", "js", "station_program_match.js")
T2_JS = ("public", "js", "station_t2.js")
T5_JS = ("public", "js", "station_t5.js")
STRINGS = (
	"Default program",
	"Allowed program",
	"Program not listed",
	"No program set for this machine",
	"These sets need different programs",
	"No program is allowed for every set type on this machine.",
	"Load the sets with different programs in separate batches.",
	"Use {0}",
	"These sets have different default programs",
	"Program {0} is allowed for every set type in the list.",
	"Use this program, or load the sets in separate batches.",
	"Reason for using a program not listed for these sets",
)
SCREEN_STRINGS = {
	T2_JS: (
		"reason for the program",
		"Program {0} chosen: the default of set type {1} on this washer.",
		"Program for this set",
	),
	T5_JS: (
		"reason for the program",
		"Program {0} chosen: the default of set type {1} on this sterilizer.",
	),
}


def _read(*parts):
	with open(frappe.get_app_path("tracecore", *parts), encoding="utf-8") as handle:
		return handle.read()


def _translated():
	path = frappe.get_app_path("tracecore", "translations", "vi.csv")
	with open(path, encoding="utf-8", newline="") as handle:
		return {row[0] for row in csv.reader(handle) if row}


class TestStationProgramMatchAssets(FrappeTestCase):
	def test_helper_loads_before_t2_and_t5(self):
		scripts = hooks.page_js["station"]
		helper = scripts.index("public/js/station_program_match.js")
		self.assertLess(helper, scripts.index("public/js/station_t2.js"))
		self.assertLess(helper, scripts.index("public/js/station_t5.js"))

	def test_screens_send_program_and_override_reason(self):
		t2 = _read(*T2_JS)
		start = t2.index('"tracecore.v1.wash.add_set"')
		self.assertIn("program: this.load.program", t2[start : start + 400])
		for script in (t2, _read(*T5_JS)):
			self.assertIn("program_override_reason", script)
			self.assertIn("TcProgramMatch.autoSelect", script)
			self.assertIn("TcProgramMatch.badgeHtml", script)
			self.assertIn("programTouched = true", script)

	def test_strings_are_used_and_translated(self):
		translated = _translated()
		helper = _read(*HELPER)
		for text in STRINGS:
			self.assertIn(f'"{text}"', helper, msg=text)
			self.assertIn(text, translated, msg=text)
		for parts, texts in SCREEN_STRINGS.items():
			script = _read(*parts)
			for text in texts:
				self.assertIn(f'"{text}"', script, msg=text)
				self.assertIn(text, translated, msg=text)

	def test_fit_is_not_shown_by_colour_alone(self):
		helper = _read(*HELPER)
		self.assertIn("data-program-fit", helper)
		self.assertIsNone(re.search(r"(?<![&\w])#[0-9a-fA-F]{3,8}\b", helper))
