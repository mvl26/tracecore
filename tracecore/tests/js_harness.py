"""Chạy mã giao diện trạm trong Node để test hành vi thay vì soi chuỗi nguồn."""

import json
import shutil
import subprocess

import frappe

_PRELUDE = r"""
const vm = require("vm");
const fs = require("fs");
// Bù mọi global của Desk: gọi được, đọc thuộc tính nào cũng được.
const stub = () => new Proxy(function () {}, {
	get: (_t, key) => (key === Symbol.toPrimitive ? () => "" : stub()),
	apply: () => stub(),
	construct: () => stub(),
});
const sandbox = {
	console,
	URLSearchParams,
	setTimeout: () => 0,
	clearTimeout: () => 0,
	setInterval: () => 0,
	clearInterval: () => 0,
	T5Load: stub(),
	T2Wash: stub(),
	frappe: stub(),
	document: stub(),
	navigator: { onLine: true },
	localStorage: stub(),
	location: { search: "", pathname: "/app/station" },
	__: (text, args) =>
		String(text).replace(/\{(\d+)\}/g, (_m, i) => (args && args[i] !== undefined ? args[i] : "")),
	esc: (value) =>
		String(value === null || value === undefined ? "" : value).replace(/[&<>"]/g, (c) => ({
			"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;",
		}[c])),
	uuid4: () => "uuid",
	clientTs: () => "2026-11-01T08:00:00+07:00",
	STATUS_BADGE: {},
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
function load(path, names) {
	const code = fs.readFileSync(path, "utf8");
	const exports = names.map((n) => `globalThis.${n} = ${n};`).join("\n");
	vm.runInContext(code + "\n" + exports, sandbox, { filename: path });
}
function element() {
	return {
		value: "",
		placeholder: "",
		attrs: {},
		dataset: {},
		innerHTML: "",
		setAttribute(key, value) { this.attrs[key] = String(value); },
		getAttribute(key) { return this.attrs[key]; },
		addEventListener() {},
		querySelector() { return null; },
		querySelectorAll() { return []; },
		classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
		focus() {},
		remove() {},
	};
}
sandbox.element = element;
"""


def node_or_skip(testcase):
	node = shutil.which("node")
	if not node:
		testcase.skipTest("node not installed")
	return node


def run_js(testcase, files, names, body):
	"""Nạp `files` (đường dẫn trong app, xuất `names`) rồi chạy `body` trong sandbox; `emit(x)` trả JSON về Python."""
	node = node_or_skip(testcase)
	loads = "".join(
		f"load({json.dumps(frappe.get_app_path('tracecore', *path.split('/')))}, {json.dumps(names_)});\n"
		for path, names_ in zip(files, names, strict=True)
	)
	script = "(async () => {\n" + body + "\n})().catch((e) => { fail(e); });"
	program = (
		_PRELUDE
		+ loads
		+ "sandbox.emit = (v) => process.stdout.write(JSON.stringify(v));\n"
		+ "sandbox.fail = (e) => { console.error(e); process.exitCode = 1; };\n"
		+ f"vm.runInContext({json.dumps(script)}, sandbox);\n"
	)
	done = subprocess.run([node, "-e", program], capture_output=True, text=True, check=False)
	testcase.assertEqual(done.returncode, 0, done.stderr)
	return json.loads(done.stdout) if done.stdout else None
