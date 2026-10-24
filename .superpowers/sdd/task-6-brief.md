# Task 6 brief — Redirect login to the real Home safely

Project context: TraceCore now has an authenticated standalone Home at `/tracecore`. Successful interactive web login should land there without weakening password-expiry handling, API login behavior, station-card authentication or safe explicit return routes.

Read first:

- `CLAUDE.md`
- `docs/superpowers/plans/2026-10-24-tracecore-independent-home.md` (Global Constraints and Task 6)
- `.superpowers/sdd/progress.md`
- `tracecore/core/account.py`
- `tracecore/core/tests/test_account.py`
- Frappe v15 login manager redirect conventions used by this repo/framework

Scope: implement only Task 6.

Required behavior/tests:

- `test_web_login_sets_tracecore_home_after_password_check`
- `test_expired_password_still_blocks_before_redirect`
- `test_guest_and_api_login_do_not_receive_unsafe_redirect`
- Existing password/session/station-card account tests must remain green.
- Set the supported Frappe login landing field to `/tracecore` only after the existing password-expiry guard succeeds.
- Preserve a valid explicit same-origin `redirect-to` if framework semantics require it; never allow an unsafe external redirect.
- Do not alter API login responses, Guest behavior, station-card auth, password checks or role permissions.
- Use TDD and capture red/green evidence.
- Run `bench --site test_site run-tests --module tracecore.core.tests.test_account` in the synced WSL checkout (root may handle final sync if necessary).
- Run relevant Home page tests and scoped pre-commit.
- Self-review and commit only `tracecore/core/account.py` and `tracecore/core/tests/test_account.py` with exactly `feat(home): redirect web login to TraceCore`.
- Write `.superpowers/sdd/task-6-report.md` with framework field/rationale, TDD evidence, test results, commit hash and concerns. Do not commit `.superpowers`.
