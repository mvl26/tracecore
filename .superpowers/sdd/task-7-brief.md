# Task 7 brief — Verify the integrated Home locally

Project context: the standalone React Home, server context API, route shell and login redirect are implemented. Add reproducible Playwright coverage and developer instructions; root will perform final live-browser visual verification.

Read first:

- `CLAUDE.md`
- `docs/superpowers/plans/2026-10-24-tracecore-independent-home.md` (Global Constraints, Task 7, final checklist)
- `docs/superpowers/specs/2026-10-24-tracecore-independent-home-design.md`
- `.superpowers/sdd/progress.md`
- `tests_e2e/conftest.py`, `tests_e2e/pytest.ini`, relevant existing E2E tests and `scripts/e2e_prepare.sh`
- current `README.md`

Scope: implement Task 7 test/docs support only. Do not change production behavior unless a real integrated failure proves a minimal fix is required; report and request authorization first in that case.

Required files:

- create `tests_e2e/test_home.py`
- modify `README.md`
- update tracked built assets or lockfile only if a clean rebuild changes them

Required scenarios (adapt fixture names to existing E2E conventions):

- successful interactive web login redirects to `/tracecore`
- an authorized operational user opens an allowed shortcut
- non-manager cannot see Frappe Admin
- System Manager/Administrator can see and open Frappe Admin
- Home is responsive at PDA viewport and uses explicit compact menu
- direct refresh/deep route keeps the standalone application shell
- logout reaches login and does not leave enabled business actions
- assert Desk toolbar/sidebar markers are absent on the Home route

Requirements:

- Use real site/API/session behavior where existing E2E infrastructure supports it; do not encode sample business values into production.
- Prefer existing prepared users/env variables and skip with a clear reason when a role fixture is not configured. Do not hard-code secrets.
- Tests must be deterministic and select by accessible role/name or stable `data-testid`, not fragile style/layout selectors.
- Add exact README commands for `npm ci`, `npm run build`, migrate, prepare E2E, start/serve and run Home tests. Use the actual test site/port conventions already in this repo; do not document a fake hostname.
- State browser URL clearly.
- Run TDD red before any required wiring adjustment; if production already passes and only test file is new, record the first meaningful failure (missing fixture/expectation) honestly.
- Run frontend tests/build, focused Frappe Home/API/account tests, Home E2E where environment allows, and scoped pre-commit.
- Self-review and commit with exactly `test(home): verify independent landing experience`.
- Write `.superpowers/sdd/task-7-report.md` with scenarios, environment variables/fixtures, commands/results/skips, commit hash and remaining visual verification. Do not commit `.superpowers`.
