# Native clean-zone workspace — verification

Date: 2026-10-25. Branch: `codex/tracecore-role-admin-ui`; keep separate, no merge.

R04 opens T3 directly; the separate white sidebar provides T3, T4, instrument lookup, own history and own override requests. Operational counters use permission-filtered real records and current-cycle gates. Queue display is bounded and explains its scope. Scanning reads the pinned BOM, tray/instrument images, current gates and authoritative par evaluation when installed. A link carries the same Set ID into T4, including on reload. Admin and other role shells remain unchanged.

T4 uses the existing station login/heartbeat/logout and pack scan, CI validation, generation and printing RPCs. Tokens stay in memory; a card must match the signed-in account. Switching views, locking or going offline clears the token and set state. Late login results are logged out; stale responses cannot overwrite another view. Business mutations use the existing stable retry key/timestamp helper. Lubrication reminders require their oil lot; maintenance is never implicitly confirmed.

The read adapter never updates gates, lifecycle states, BOMs or approvals. Internal gate rows expose only step/result/current cycle after their Set Unit parent passes a permission-filtered query. Station identity is a deliberate role-gated allowlist, excluding peripheral/network fields. History and override requests filter by the actual session owner, including when Admin browses the role.

## Executed checks

- Initial backend tests failed because `tracecore.v1.ktv` did not exist, before implementation.
- Frappe `tracecore.tests.test_ktv_ui`: **10 passed**. Covers role/step isolation, current versus old cycle, already-packed/completed queue exclusion, actual-owner request/history filters, parent-bound internal gates, denied-parent context, pinned BOM and server par result, absent override service.
- Direct coverage runner for the new adapter: **96% statements** (52 statements, 2 missing). The normal bench coverage command did not include the newly loaded module, so the explicit source runner was used: `coverage run --source=tracecore.v1.ktv -m frappe.utils.bench_helper frappe --site test_site run-tests --module tracecore.tests.test_ktv_ui` from bench `sites/`.
- Frontend `npm run build`: vue-tsc and Vite pass. `npm test`: **8 passed** (shared session/CSRF/safe-error/idempotency tests).
- Playwright `test_ktv_workspace.py` plus existing `test_admin_ui.py`: **11 passed**. Five KTV tests cover real read/navigation and same-set T4, mobile overflow, mocked T4 oil-lot payload, stale station login, and offline recovery. Six existing Admin browser tests remain green.
- The T4 contract test mocks station and pack responses; it verifies UI behavior/payload only, **not** live card authentication, stock posting, label printing or lifecycle completion.
- Ruff scoped checks pass. Desktop and mobile screenshots were inspected; built assets are published to the local bench.
- Independent read-only review found oil-lot, async state, par evaluation and metric-label issues; all four were addressed and corresponding checks added or wording corrected.

## Explicit dependencies

Full T3 assembly RPC is absent on this feature branch. T3 checkboxes are for visual comparison only and completion is disabled; no Assembly Record is fabricated. The separate local bench additionally lacks `Employee.tc_card_id` and full M8 override service, so it exposes read mode and an unavailable request state. Its existing Instrument Set Type DocType was reloaded to synchronize missing image columns already declared in source, enabling the real BOM API. No other business feature was merged or copied over the older checkout, no Employee auth bypass was added, and no global migration was run. Live T3-to-T4 completion and real station writes remain unverified until those backend dependencies are installed.
