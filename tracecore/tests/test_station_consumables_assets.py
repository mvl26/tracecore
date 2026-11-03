"""Màn T2, T5, test đầu ngày: vật tư của chương trình (A-111; FR-M2-03.9, FR-M2-09.9, FR-M5-05.5)."""

import csv
import re

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore import hooks

HELPER = ("public", "js", "station_consumables.js")
SCREENS = (
	("public", "js", "station_t2.js"),
	("public", "js", "station_t5.js"),
	("public", "js", "station_daily_test.js"),
)
STRINGS = (
	"Reminder only, not deducted",
	"Actual quantity of {0}",
	"Norm for this run",
	"Leave the quantity empty to use the norm. Scan or choose the lot; the earliest expiry is suggested.",
	"Consumables are ready and the quantities are right",
	# A-112: cột Lô
	"Lot of {0}",
	"Expiry {0} · stock {1}",
	"Expiry {0}",
	"Expires soon",
	"Out of stock",
	"Not in the suggested lots: checked on save",
)


def _read(*parts):
	with open(frappe.get_app_path("tracecore", *parts), encoding="utf-8") as handle:
		return handle.read()


class TestStationConsumablesAssets(FrappeTestCase):
	def test_helper_loads_before_the_screens(self):
		scripts = hooks.page_js["station"]
		helper = scripts.index("public/js/station_consumables.js")
		for parts in SCREENS:
			self.assertLess(helper, scripts.index("/".join(parts)))

	def test_screens_send_the_confirmed_consumables(self):
		for parts in SCREENS:
			script = _read(*parts)
			self.assertIn("TcRunConsumables.html", script, msg=parts)
			self.assertIn("TcRunConsumables.payload", script, msg=parts)
			self.assertIn("consumables_confirmed", script, msg=parts)
			self.assertIn("TcRunConsumables.reset", script, msg=parts)
			# A-112: ô số thực dùng và ô lô đi qua cùng một hàm
			self.assertIn("TcRunConsumables.remember", script, msg=parts)

	def test_lot_column_sends_the_chosen_lot(self):
		helper = _read(*HELPER)
		for part in ("data-consumable-lot", "consumables_lot", "<datalist", "batch"):
			self.assertIn(part, helper, msg=part)

	def test_strings_are_translated_and_no_colour_only_state(self):
		path = frappe.get_app_path("tracecore", "translations", "vi.csv")
		with open(path, encoding="utf-8", newline="") as handle:
			translated = {row[0] for row in csv.reader(handle) if row}
		helper = _read(*HELPER)
		for text in STRINGS:
			self.assertIn(f'"{text}"', helper, msg=text)
			self.assertIn(text, translated, msg=text)
		for text in ("consumables confirmation", "Consumables of program {0}"):
			self.assertIn(text, translated, msg=text)
		self.assertIsNone(re.search(r"(?<![&\w])#[0-9a-fA-F]{3,8}\b", helper))
