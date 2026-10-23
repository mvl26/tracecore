// Unit checks for routing; browser coverage remains in tests_e2e.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");
const source = fs.readFileSync(path.join(__dirname, "../tracecore/public/js/tc_launcher.js"), "utf8");
for (const [roles, route, expected] of [
	[["TC R03"], ["Workspaces", "Home"], ["tracecore"]],
	[["System Manager"], ["Workspaces", "Accounting"], ["tracecore"]],
	[["TC R01"], ["List", "Instrument"], null],
	[["TC R03"], ["station"], null],
	[["Employee"], ["Workspaces", "Home"], null],
]) {
	test(`${roles[0]} / ${route.join("/")}`, () => {
		let destination = null;
		let current = route;
		const context = {
			frappe: {
				user_roles: roles,
				get_route: () => current,
				set_route: (...args) => { destination = args; current = args; },
				after_ajax: (fn) => fn(),
				router: { on: () => {} },
			},
			__: (text) => text,
			$: (arg) => typeof arg === "function" ? arg() : { first: () => ({ length: 0 }) },
		};
		vm.runInNewContext(source, context);
		assert.deepEqual(destination, expected);
	});
}
