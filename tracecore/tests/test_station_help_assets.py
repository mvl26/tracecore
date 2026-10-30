"""Asset kiosk của trợ giúp theo trạm (FEAT-013, FR-M9-15, A-55 D3, D9, D10): nút, modal, lib chụp màn, che ô nhạy cảm."""

import re
from pathlib import Path

from frappe.tests.utils import FrappeTestCase

from tracecore import hooks

APP = Path(__file__).resolve().parents[1]
JS = APP / "public/js/station_help.js"
LIB = APP / "public/js/lib/html2canvas"
STATION = APP / "ui/page/station"


class TestStationHelpAssets(FrappeTestCase):
	def setUp(self):
		self.js = JS.read_text(encoding="utf-8")
		self.station_js = (STATION / "station.js").read_text(encoding="utf-8")

	def test_script_is_loaded_with_station_page(self):
		self.assertIn("public/js/station_help.js", hooks.page_js["station"])

	def test_help_button_in_station_title_bar(self):
		html = (STATION / "station.html").read_text(encoding="utf-8")
		title = html[html.index('<header class="tc-title">') : html.index("</header>")]
		self.assertIn('data-action="open-help"', title)
		self.assertIn('__("Help")', title)

	def test_station_routes_help_actions_and_keeps_focus_in_modal(self):
		self.assertIn('action === "open-help"', self.station_js)
		self.assertIn("this.help.onAction(action, button)", self.station_js)
		self.assertIn("this.help && this.help.isOpen", self.station_js)
		self.assertIn('method.startsWith("tracecore.v1.feedback.")', self.station_js)

	def test_calls_help_and_feedback_rpcs_with_idempotency_key(self):
		self.assertIn('"tracecore.v1.help.get"', self.js)
		self.assertIn('"tracecore.v1.feedback.create"', self.js)
		self.assertIn("this.key = this.key || uuid4()", self.js)

	def test_vendored_html2canvas_is_lazy_loaded_and_licensed(self):
		self.assertTrue(
			(LIB / "html2canvas.min.js").read_text(encoding="utf-8").startswith("/*!\n * html2canvas 1.4.1")
		)
		self.assertIn("MIT", (LIB / "LICENSE").read_text(encoding="utf-8"))
		self.assertIn("/assets/tracecore/js/lib/html2canvas/html2canvas.min.js", self.js)
		self.assertIn("frappe.require(TC_HTML2CANVAS)", self.js)
		self.assertNotRegex(self.js, r"https?://")

	def test_sensitive_fields_are_masked_and_modal_excluded_from_screenshot(self):
		for selector in ('input[type="password"]', '[name="patient_code"]', "[data-tc-mask]"):
			self.assertIn(selector, self.js)
		self.assertIn("onclone: tcMaskClone", self.js)
		self.assertIn('contains("tc-help-modal")', self.js)

	def test_four_screen_states_and_cached_guide(self):
		for state in ("loading", "empty", "error", "offline"):
			self.assertIn(f'this.state === "{state}"', self.js)
		self.assertIn("localStorage", self.js)
		self.assertIn("try {", self.js)

	def test_user_strings_are_translated_and_escaped(self):
		# bỏ chú thích: chữ tiếng Việt chỉ được nằm trong comment, chuỗi hiển thị đi qua __() bằng tiếng Anh
		code = re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", self.js, flags=re.S))
		self.assertNotRegex(code, r"[ăâđêôơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]")
		self.assertNotIn("innerHTML = step", self.js)
		self.assertIn("esc(step.text)", self.js)
		self.assertIn("esc(step.image)", self.js)

	def test_css_uses_tokens_only_and_touch_sizes(self):
		css = (STATION / "station.css").read_text(encoding="utf-8")
		block = css[css.index("/* trợ giúp theo trạm") :]
		block = block[: block.index("/* end trợ giúp */")]
		self.assertNotRegex(block, r"#[0-9a-fA-F]{3,8}\b")
		self.assertNotRegex(block, r"\d+px")
		self.assertIn("var(--tc-touch-min)", block)
		self.assertIn(".tc-help-btn", block)
