# Task 2 brief — Add the authoritative Home context API

Project context: TraceCore is a Frappe v15 application. The new `/tracecore` React Home must receive a real, role-personalized payload from Frappe; Frappe remains authoritative for permissions, data and allowed navigation.

Read first:

- `CLAUDE.md`
- `docs/superpowers/plans/2026-10-24-tracecore-independent-home.md` (Global Constraints and Task 2)
- `docs/superpowers/specs/2026-10-24-tracecore-independent-home-design.md`
- `.superpowers/sdd/progress.md`
- existing `tracecore/v1/navigation.py` and its tests
- nearby API/test conventions under `tracecore/v1/`

Scope: implement only Task 2 from the plan.

Required files:

- create `tracecore/v1/home.py`
- create `tracecore/v1/tests/test_home_api.py`

Required contract/tests:

- `test_guest_cannot_read_home`
- `test_r03_receives_station_shortcut_without_admin_link`
- `test_system_manager_receives_frappe_admin_capability`
- `test_doctype_shortcut_requires_read_permission`
- `test_metrics_use_real_counts_and_never_patient_fields`
- `test_route_keys_are_closed_identifiers_not_urls`
- `test_context_etag_is_stable_for_equal_payload`
- exact top-level key set: `user`, `capabilities`, `navigation`, `attention`, `metrics`, `shortcuts`, `system`, `etag`
- exact shortcut keys: `key`, `label`, `description`, `route_key`, `badge`

Implementation requirements:

- Use TDD: add tests first and record the expected failing result before implementation.
- Define the closed `ROUTE_KEYS` set from the plan.
- Expose a whitelisted GET `context()` endpoint.
- Reject Guest with `frappe.PermissionError`.
- Check `frappe.has_permission` before exposing every DocType shortcut or metric.
- Derive station choices from the same active-station query used by `navigation.context`; do not create a second incompatible station rule.
- Use real aggregate counts only; omit unavailable metrics instead of inventing zero/sample values.
- Expose `frappe-admin` only to Administrator/System Manager.
- Return stable English identifiers and translated display strings.
- SHA-256 ETag over canonical JSON excluding `etag`, truncated to 16 hex characters; `system.api_version = 1`; server timestamp is excluded from ETag input.
- Never return/log patient identifiers.
- Keep business and authorization decisions server-side.
- Run the focused Frappe test module. Because the active bench checkout may lag the shared Windows checkout, report any environment limitation precisely; do not fake passing output.
- Self-review and commit only the two scoped files with exactly `feat(home): add role-personalized context API`.
- Write `.superpowers/sdd/task-2-report.md` with TDD evidence, verification results, changed files, commit hash, and concerns. Do not commit `.superpowers`.
