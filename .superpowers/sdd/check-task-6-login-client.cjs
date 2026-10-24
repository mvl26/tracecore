// Supplemental verification of the installed Frappe client's exact redirect expression.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const common = fs.readFileSync('apps/frappe/frappe/public/js/frappe/utils/common.js', 'utf8');
const login = fs.readFileSync('apps/frappe/frappe/templates/includes/login/login.js', 'utf8');
const sanitizer = common.slice(
  common.indexOf('frappe.utils.sanitise_redirect ='),
  common.indexOf('frappe.utils.strip_url ='),
);
const expression = login.match(/window\.location\.href = (frappe\.utils\.sanitise_redirect\(frappe\.utils\.get_url_arg\("redirect-to"\)\) \|\| data\.home_page);/)[1];
const cases = [
  [null, '/tracecore'],
  ['/app/station?station=TR-004', '/app/station?station=TR-004'],
  ['http://localhost/app/station', 'http://localhost/app/station'],
  ['https://evil.example/steal', '/tracecore'],
  ['//evil.example/steal', '/tracecore'],
  ['javascript:alert(1)', '/tracecore'],
  ['/\\evil.example/steal', '/tracecore'],
];
for (const [destination, expected] of cases) {
  const context = {
    URL,
    location: new URL('http://localhost/login'),
    frappe: { utils: { get_url_arg: () => destination } },
    data: { home_page: '/tracecore' },
  };
  vm.createContext(context);
  vm.runInContext(sanitizer, context);
  assert.equal(vm.runInContext(expression, context), expected, destination);
}
console.log(`Installed Frappe login client: ${cases.length}/${cases.length} redirect checks passed.`);
