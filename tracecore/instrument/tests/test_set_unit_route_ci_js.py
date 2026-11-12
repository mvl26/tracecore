"""A-157 (FR-M1-06.6): form Set Unit — nút Sửa cạnh Quy trình xử lý / Loại chỉ thị hóa học, chỉ người có quyền."""

from tracecore.tests.js_harness import run_js
from tracecore.tests.utils import IsolatedTestCase

FORM = "instrument/doctype/set_unit/set_unit.js"
NAMES = ["tc_su_render_summary", "tc_su_route_ci_payload", "tc_su_route_ci_warning"]
SETUP = """
globalThis.tracecore = {set_unit: {status_html: () => ""}};
let rendered = "";
const frm = {
	doc: {name: "9520000RCJS000001", set_type: "RCJS"},
	fields_dict: {summary_html: {$wrapper: {html(h) { rendered = h; }, find: () => ({on() {}})}}},
};
const summary = {
	set_id: "9520000RCJS000001", set_type: "RCJS", status: "New", cycles_used: 0, max_cycles: 300, remaining: 300,
	processing_route: "Steam", ci_class: "", components: [],
};
const edit = (can_edit) => ({
	can_edit, set_type: "RCJS", methods: ["Steam", "Plasma", "Disinfection"],
	ci_classes: ["", "Not Needed", "4", "5", "6"], units: 3, units_in_cycle: 1,
});
"""


class TestSetUnitRouteCiForm(IsolatedTestCase):
	def _run(self, code):
		return run_js(self, [FORM], [NAMES], SETUP + code)

	def test_edit_button_only_for_editors(self):
		out = self._run(
			"""tc_su_render_summary(frm, {summary, set_type_edit: edit(true)}); const yes = rendered;
			tc_su_render_summary(frm, {summary, set_type_edit: edit(false)}); const no = rendered;
			tc_su_render_summary(frm, {summary}); emit({yes, no, none: rendered});"""
		)
		self.assertEqual(out["yes"].count("tc-su-edit-route-ci"), 2)
		self.assertNotIn("tc-su-edit-route-ci", out["no"])
		self.assertNotIn("tc-su-edit-route-ci", out["none"])

	def test_payload_targets_the_set_type(self):
		out = self._run(
			"""emit([tc_su_route_ci_payload(frm, {method: "Plasma", ci_class: "6"}),
				tc_su_route_ci_payload(frm, {method: "Steam"})]);"""
		)
		self.assertEqual(out[0], {"set_type": "RCJS", "method": "Plasma", "ci_class": "6"})
		self.assertEqual(out[1], {"set_type": "RCJS", "method": "Steam", "ci_class": ""})

	def test_warning_names_the_scope(self):
		out = self._run("""emit(tc_su_route_ci_warning(edit(true)));""")
		self.assertIn("3", out)
		self.assertIn("1", out)
		self.assertIn("RCJS", out)
