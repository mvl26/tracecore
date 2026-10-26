# TraceCore Admin Shell + M1 — verification evidence

Date: 2026-10-25. Branch: `codex/tracecore-role-admin-ui`. User requested separate branch and push, no merge.

## Delivered slice

- Independent Vue 3 / TypeScript / Vite UI at `/tracecore`, including deep links, own login, session/OTP state handling, required-password-reset redirect, logout, offline/errors and role navigation.
- All R01–R10 represented; Administrator sees every space. Ordinary accounts see their assigned TC roles. Optional explicit overview role expands navigation only, not DocType/record/field permissions.
- Safe permission-filtered list/detail endpoints with field allowlists and permlevel filtering, bounded pagination and literal code search. Real counts and supported pending-request/equipment alert sources; no prototype numbers.
- Instrument create/edit with controller validation and optimistic timestamp checks; native set-type header/BOM version UI, BOM creation and PDF; native Set ID issuance, summary/history, tag preview/CSV/reprint and tag verification through existing business RPCs.
- Idempotent mutations preserve key and timestamp on uncertain retry, rotate on changed operation/payload or definitive rejection. No impersonation or frontend lifecycle state changes.
- Optional Desk redirect remains disabled by default; station route is excluded. No production deployment or account permission changes.

## Verification actually run

- `npm --prefix frontend run build`: vue-tsc and Vite production build pass. Vite reports tokens.css is external and served by Frappe at runtime, as intended.
- `npm --prefix frontend test`: 8 tests pass, including CSRF/session, safe errors, internal navigation, same-origin reset, idempotency retry and expiry handling. Also executed successfully with bench Node 18.20.8.
- `npm --prefix frontend audit --audit-level=high`: zero vulnerabilities after patched Vue 3.5.44 and Vite 6.4.4; Node built-in tests avoid outdated test-server dependencies.
- `bench --site test_site run-tests --module tracecore.tests.test_admin_ui`: 13 tests pass, including real DB Instrument create/edit, guest/role isolation, protected-field and lifecycle write refusal, permission-filtered query and higher-permlevel reads.
- Playwright `tests_e2e/test_admin_ui.py` on dev site: 6 tests pass (TraceCore guest login, role menu/form, deep link/forged role, logout, native login with challenge when enabled, returning home during pending request). Native 2FA challenge path only runs when the configured account actually receives a challenge; this run must not be described as exhaustive 2FA enrollment testing.
- Ruff check and `git diff --check` pass for scoped files.
- Independent read-only review found and verified fixes for idempotency retries, stuck loading, forced password reset and read permlevels; no remaining Critical/Important findings for this slice.

## Existing-environment regression limitation

The existing kiosk T4 smoke `test_t4_touch_targets_and_font_sizes` failed in its card-login fixture on this dev bench: HTTP 500, PyMySQL OperationalError, `Unknown column 'tc_card_id'` on Employee. Read-only browser diagnosis confirmed the station route itself renders and no JavaScript error occurs. The new branch does not modify Employee schema or station authentication. This environment needs its existing Employee custom-field/schema setup reconciled before claiming a green kiosk regression suite. No migration or authentication bypass was applied to hide this failure.

## Remaining scope, not claimed complete

This is the initial Admin Shell + M1 slice, not completion of all operational screens for ten roles. Existing station/department workflows have not all been ported to Vue. Unimplemented sources show unavailable state rather than fake data. Patient lookup, role-specific write approvals, media upload/GIAI maintenance actions, complete reporting, complete account administration and all kiosk/PDA/Portal workflows require subsequent work. Keep broad Desk cutover disabled until those workflows are available and tested. Do not merge automatically.
