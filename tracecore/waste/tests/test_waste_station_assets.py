"""Asset màn thu gom chất thải (SCR-38, FEAT-047, UC-34, FR-M9-14, A-60 W2, W4): kiểm tĩnh, không chạy E2E."""

import re
from pathlib import Path

from frappe.tests.utils import FrappeTestCase

from tracecore import hooks
from tracecore.v1 import navigation

APP = Path(__file__).resolve().parents[2]
JS = APP / "public/js/station_waste.js"
STATION = APP / "ui/page/station"


class TestWasteStationAssets(FrappeTestCase):
	def setUp(self):
		self.js = JS.read_text(encoding="utf-8")
		self.station_js = (STATION / "station.js").read_text(encoding="utf-8")

	def test_script_loads_after_the_shared_weigh_line(self):
		scripts = hooks.page_js["station"]
		self.assertLess(
			scripts.index("public/js/tc_weigh_line.js"), scripts.index("public/js/station_waste.js")
		)

	def test_station_opens_the_screen_for_step_wst(self):
		self.assertIn('station.step === "WST" && typeof WasteCollect !== "undefined"', self.station_js)
		self.assertIn('method.startsWith("tracecore.v1.waste.")', self.station_js)
		self.assertIn("WST", navigation.IMPLEMENTED_STEPS)

	def test_calls_waste_rpcs_and_reuses_key_on_retry(self):
		for method in ("catalog", "giver", "collect", "acknowledge"):
			self.assertIn(f'"tracecore.v1.waste.{method}"', self.js)
		self.assertIn("key: uuid4()", self.js)
		self.assertIn("pending.key", self.js)

	def test_giver_is_scanned_not_typed(self):
		self.assertNotIn('data-field="delivered_by"', self.js)
		self.assertIn("this.form.card", self.js)

	def test_manual_weight_needs_the_confirmation_tick(self):
		self.assertIn("TcWeighLine.html", self.js)
		self.assertIn('line.source === "Manual"', self.js)
		self.assertIn("weight_confirmed", self.js)

	def test_misclassified_line_needs_a_note(self):
		self.assertIn('data-field="misclassified"', self.js)
		self.assertIn('data-field="misclass_note"', self.js)

	def test_codes_use_mono_and_receipt_prints_a5_format(self):
		self.assertIn("tc-mono", self.js)
		self.assertIn('"TC Waste Receipt"', self.js)

	def test_session_end_clears_giver_and_form(self):
		body = self.js[self.js.index("clearSession()") :]
		body = body[: body.index("\n\t}")]
		self.assertIn("this.form = this.blankForm()", body)
		self.assertIn("this.pending = null", body)

	def test_four_screen_states(self):
		for marker in ('setState("offline"', "renderLoading()", '"empty"', '"error"'):
			self.assertIn(marker, self.js)

	def test_blocking_errors_are_inline_alerts_not_modal_or_toast(self):
		self.assertIn("tc-alert-${variant}", self.js)
		self.assertNotIn("frappe.msgprint", self.js)
		self.assertNotIn("show_alert", self.js)

	def test_strings_are_translated_english_sources(self):
		code = re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", self.js, flags=re.S))
		self.assertNotRegex(code, r"[ăâđêôơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]")

	def test_desk_button_releases_held_containers_for_r02(self):
		desk = (APP / "waste/doctype/waste_container/waste_container.js").read_text(encoding="utf-8")
		self.assertIn('"tracecore.v1.waste.release_held"', desk)
		self.assertIn('frm.doc.status !== "Held"', desk)

	def test_launcher_links_waste_doctypes(self):
		links = dict(navigation.MANAGEMENT_GROUPS)["Medical waste"]
		self.assertEqual(
			links,
			(
				"Waste Type",
				"Waste Collection",
				"Waste Container",
				"Waste Storage Location",
				"report:Waste Storage Stock",
			),
		)

	def test_store_tab_scans_location_then_bag(self):
		store = (APP / "public/js/station_waste_store.js").read_text(encoding="utf-8")
		for method in ("stock", "check_location", "store", "record_temperature"):
			self.assertIn(f'"tracecore.v1.waste.{method}"', store)
		self.assertIn('wasteTabs("store")', store)
		self.assertIn('wasteTabs("collect")', self.js)
		self.assertIn("new WasteStation(this)", self.station_js)
		self.assertIn("public/js/station_waste_store.js", hooks.page_js["station"])
		for marker in ('setState("offline"', "renderLoading()", '"empty"', '"error"', "tc-alert-${variant}"):
			self.assertIn(marker, store)
		self.assertNotIn("frappe.msgprint", store)
