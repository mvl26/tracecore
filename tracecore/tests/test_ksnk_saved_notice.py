"""Trang KSNK: ghi thành công luôn có thông báo "Đã lưu thành công", lỗi chặn không có (người dùng 11/11/2026)."""

import json
import os
import subprocess

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.tests.js_harness import node_or_skip

DESK_CALL = "public/js/tc_desk_call.js"

_PROGRAM = r"""
const fs = require("fs");
const vm = require("vm");
const cases = JSON.parse(process.argv[2]);
const code = fs.readFileSync(process.argv[1], "utf8");
const out = [];
for (const c of cases) {
	const alerts = [];
	const sandbox = {
		tracecore: undefined,
		__: (text) => text,
		frappe: {
			provide(name) { sandbox[name] = sandbox[name] || {}; },
			get_route: () => c.route,
			show_alert: (a) => alerts.push(a),
			call: (o) => (c.http ? o.error({ responseJSON: { message: c.body } }) : o.callback({ message: c.body })),
		},
	};
	vm.createContext(sandbox);
	vm.runInContext(code, sandbox);
	let ok = 0, block = 0;
	sandbox.tracecore.desk_call({
		method: "m", args: {}, success: c.success,
		on_ok: () => ok++, on_block: () => block++,
	});
	out.push({ alerts, ok, block });
}
process.stdout.write(JSON.stringify(out));
"""


class TestKsnkSavedNotice(FrappeTestCase):
	def _run(self, cases):
		node = node_or_skip(self)
		path = os.path.join(frappe.get_app_path("tracecore"), *DESK_CALL.split("/"))
		done = subprocess.run(
			[node, "-e", _PROGRAM, path, json.dumps(cases)], capture_output=True, text=True, check=False
		)
		self.assertEqual(done.returncode, 0, done.stderr)
		return json.loads(done.stdout)

	def test_success_on_ksnk_page_shows_green_notice_with_text(self):
		ok = {"ok": True}
		out = self._run(
			[
				{"route": ["tc-ksnk", "co-cau"], "body": ok},
				{"route": ["tc-ksnk", "co-cau"], "body": ok, "success": "Settings saved successfully"},
			]
		)
		self.assertEqual(out[0]["alerts"], [{"message": "Saved successfully", "indicator": "green"}])
		self.assertEqual(out[0]["ok"], 1)
		self.assertEqual(out[1]["alerts"], [{"message": "Settings saved successfully", "indicator": "green"}])

	def test_screen_can_opt_out_when_it_has_its_own_message(self):
		out = self._run([{"route": ["tc-ksnk", "tuan-thu"], "body": {"ok": True}, "success": False}])
		self.assertEqual(out[0]["alerts"], [])
		self.assertEqual(out[0]["ok"], 1)

	def test_blocked_save_has_no_success_notice(self):
		blocked = {"ok": False, "error": {"title": "Not saved"}}
		out = self._run(
			[
				{"route": ["tc-ksnk", "co-cau"], "body": blocked},
				{"route": ["tc-ksnk", "co-cau"], "body": blocked, "http": 1},
			]
		)
		for row in out:
			self.assertEqual((row["alerts"], row["ok"], row["block"]), ([], 0, 1))

	def test_other_pages_keep_their_own_behaviour(self):
		# form Desk khác (employee, incident…) không tự hiện thông báo; chỉ có khi truyền success rõ ràng
		out = self._run(
			[
				{"route": ["Form", "Employee", "E1"], "body": {"ok": True}},
				{"route": ["Form", "Employee", "E1"], "body": {"ok": True}, "success": "Done"},
			]
		)
		self.assertEqual(out[0]["alerts"], [])
		self.assertEqual(out[1]["alerts"], [{"message": "Done", "indicator": "green"}])
