# FEAT-003 Task 6 report

Status: **DONE_WITH_CONCERNS** (verification limitations below; no failing checks).

Commit: **`2fd02f0e7271478c05938d92b1fcbab6f64af6d2`**

Base: `ab908496576b1c27145f27463634f7c2c574510a`

Branch: `feat/FEAT-003-rbac-station-auth`

Repository: `/home/tien2003/tracecore-codex/apps/tracecore`

Only the isolated Ubuntu Codex bench and its `test_codex` site were used. No files in the normal development bench or tracked source in `D:/tracecore` were modified. Windows `.feat003-staging/task6` held apply_patch edits, followed by mechanical copies. The pre-existing untracked `.superpowers/` handoff directory was preserved. This report and screenshots are untracked handoff artifacts, outside the implementation commit.

## Result and scope

The station page initially exposes only employee-card login. Work and session identity remain hidden until a successful card login or server-validated tab-token restore. The identity row shows employee, station and session expiry, with translated labels and date/time in day/month/year 24-hour form. Blocking auth errors show title, reason and action inline.

The bearer is held in memory and per-station `sessionStorage` only. Protected T4 `pack.*`/printer calls receive the bearer in the JSON body. Existing idempotency keys and original client timestamps survive retries. The token never enters a URL, Authorization header, rendered DOM, error message or console output.

Client inactivity locks and clears work at ten minutes. Logout, the scan-another-card toolbar action, page hide, card removal and any server `SESSION_*` rejection clear the token, identity, scanner values, pending retries, open packing context and dialogs. Session generation checks discard late RPC/print/UI responses so they cannot restore the preceding operator's work. Heartbeats reflect operator activity rather than generating activity on an idle timer; a server denial always returns to login. Server expiry and revocation remain authoritative.

Reader adapters have explicit window event contracts:

```javascript
window.dispatchEvent(new Event("tc-card-removed"));
window.dispatchEvent(new CustomEvent("tc-card-scanned", {
  detail: { card_id: scannedCardId }
}));
```

A card-scanned event while logged out logs in directly. While active, it immediately clears/ends the old session, then logs in with the newly scanned card after logout completes. Session/event generation checks prevent an intervening removal or later reader event from reopening an earlier card. Values typed into the T4 main Set/Cycle/roll scanner are not reinterpreted as employee cards.

As explicitly requested during Task 6, indicator lots now use a dedicated labelled input within the existing Indicator Lot block. Its protected `tracecore.v1.pack.resolve_ci` endpoint delegates to the existing `packing.resolve_ci_batch` method/class/expiry validation, with station session authorization before idempotency lookup. Main `pack.scan` no longer treats unknown scans as CI, even with an open set. The selected lot and expiry render through the existing CI display, and focus returns to the main scanner after submission. Existing packing, printing, BOM, maintenance and completion rules are unchanged.

All missing FEAT-003 source/DocType field translations from Tasks 1–6 were added, with context on generic labels. Existing `Login` translation is reused. No unrelated translation sweep was performed.

## Files committed

- `tracecore/ui/page/station/station.{js,html,css}`: auth wrapper, session lifecycle, secure body transport, focus, reader contracts and token-based spacing/layout.
- `tracecore/public/js/station_t4.js`: session clear/generation barriers, dedicated CI input/request and focus handling.
- `tracecore/v1/pack.py`: separate protected CI resolver and main-scanner CI rejection.
- `tracecore/translations/vi.csv`: Task 1–6 auth labels/errors and new shell/CI strings.
- `tracecore/tests/test_station_page.py`: auth shell/static token storage assertions; full translation regression.
- `tracecore/v1/tests/test_pack_api.py`: separate-CI, schema, expiry/method, main-scanner rejection and replay/revocation checks; existing CI tests target the dedicated endpoint.
- `tracecore/v1/tests/test_station_security.py`: all packing endpoints require a session, plus real second-physical-station login rejecting the first heartbeat.
- `scripts/tests/station_auth.test.js`: seven behavioral Node tests loading the actual station/T4 scripts.
- `tests_e2e/test_station_auth.py`: fifteen Playwright Chromium cases loading actual scripts/template/CSS and routing the RPC boundary deterministically.
- `tests_e2e/conftest.py`: existing live-site fixtures scan `TC_E2E_CARD_ID`/`TC_E2E_T4_CARD_ID` after Desk login.
- `tests_e2e/test_station_t4.py`: existing CI scans use the dedicated input.
- `tests_e2e/test_station_smoke.py`: missing-station auth error selector follows the wrapper.

Exactly 14 files, 1076 insertions / 37 deletions. Both newly created source/test files are mode 100644. Tracked worktree is clean after the commit.

## Test-first evidence

Commands below ran through `wsl.exe -d Ubuntu-22.04 -u tien2003 -- bash -lc "..."` with required sandbox escalation. The initial default WSL invocation hit docker-desktop rather than Ubuntu; it was corrected before repository access or mutations.

From the app directory:

```sh
node --test scripts/tests/station_auth.test.js
```

Before production code, the meaningful RED rerun reported **6 tests, 0 pass, 6 fail**. Assertions showed a missing JSON bearer, unauthorized network access without a session, missing storage/clear/idle behavior, and a stale T4 callback being applied. An earlier harness run had missing `performance`; that harness error was corrected before accepting the meaningful RED rerun.

From the bench directory:

```sh
bench --site test_codex run-tests --module tracecore.tests.test_station_page --test test_station_auth_shell_gates_the_existing_work_surface --test test_station_bearer_never_uses_persistent_storage --skip-test-records
bench --site test_codex run-tests --module tracecore.v1.tests.test_pack_api --test test_main_scan_never_resolves_indicator_lots_even_with_open_set --test test_dedicated_ci_endpoint_uses_existing_method_and_expiry_rules --skip-test-records
```

RED: **2 static tests failed**, because the auth form/hidden work wrapper and sessionStorage contract were absent. **2 API tests failed**, because main scanning returned `ok:true` for CI and the dedicated endpoint did not exist.

From the app directory:

```sh
uv run --offline --with pytest-playwright --python /home/tien2003/tracecore-codex/env/bin/python pytest tests_e2e/test_station_auth.py -q --maxfail=1
```

RED: **1 failed**, missing `#tc-card-input`; the browser still showed the pre-auth packing scanner. Chromium and all dependencies were already cached. No browsers or packages were downloaded. This initial uv command created an ignored local `.venv` and an untracked `uv.lock`; the lock was moved to `.superpowers/sdd/task-6-offline-uv.lock`, and subsequent commands use `--no-project`.

Further self-review RED/GREEN cycles:

- Expanded offline browser test exposed a late ping overwriting the offline login reason: **1 failed, 11 passed**. Handshake now rechecks offline state after the response; subsequent full run passed.
- Node test for a card arriving while the initial ping was pending showed **6 pass, 1 fail**, expected one login but observed zero. Login now awaits the initial handshake and checks session generation/offline state before proceeding; final **7/7 passed**.
- Reader-event browser tests ran before their handler existed: **2 failed, 12 deselected**, for logged-out card scan and active-session replacement. After the event implementation, both passed in the full browser run.

The initial full station-page run found the missing FEAT-003 translation labels inherited from Tasks 1–5 as well as the new `Log in` spelling. Authorized FEAT-003 translations were completed and existing `Login` reused; the final full translation suite passes.

## Final verification commands and results

```sh
cd /home/tien2003/tracecore-codex/apps/tracecore
node --test scripts/tests/station_auth.test.js
uv run --offline --no-project --with pytest-playwright --python /home/tien2003/tracecore-codex/env/bin/python pytest tests_e2e/test_station_auth.py -q --screenshot=on --output=.superpowers/sdd/task6-browser-artifacts
```

Final results after all production changes and formatting: **7/7 Node tests passed; 15/15 Playwright tests passed in 4.63s**. Browser coverage includes 1366×768 kiosk and 412×915 PDA login/identity/body-token/logout; second station replacement; idle/removal/rescan/server expiry clearing; real full T4 CI renderer and dedicated input at both sizes; tab restore validation; inline card rejection; offline login and active packing reconnect; transport retry preserving key/timestamp/token; and both reader scan event states. Horizontal overflow and CI button touch height are asserted. Fifteen screenshots are under `.superpowers/sdd/task6-browser-artifacts/`; kiosk and PDA screenshots were also visually inspected, showing preserved work layout and responsive session controls.

```sh
cd /home/tien2003/tracecore-codex
bench --site test_codex run-tests --module tracecore.tests.test_station_page --skip-test-records
bench --site test_codex run-tests --module tracecore.v1.tests.test_station_security --skip-test-records
bench --site test_codex run-tests --module tracecore.core.tests.test_station_auth --skip-test-records
```

Results: **11 station-page tests OK (3.796s); 18 bearer-security tests OK (39.711s); 6 server-session tests OK (10.946s)**. The new physical-station regression logs in through Guest station RPC at TR-004, logs in the same Employee at TR-005, verifies old heartbeat returns `SESSION_INVALID`/401, and verifies new heartbeat succeeds at TR-005.

```sh
cd /home/tien2003/tracecore-codex
env PYTHONPATH=/home/tien2003/.cache/uv/archive-v0/NKwABb-qbyvo3e43 bench --site test_codex run-tests --app tracecore --module tracecore.v1.tests.test_pack_api --coverage --skip-test-records
cd apps/tracecore
diff-cover /home/tien2003/tracecore-codex/sites/coverage.xml --compare-branch=ab908496576b1c27145f27463634f7c2c574510a --fail-under=70
```

Final result: **51 packing tests OK (201.504s)** with coverage enabled. Packing generation P95 **503 ms**, max **834 ms**, under the existing 1-second P95 requirement. A preceding non-coverage run passed **50 tests in 113.104s**, P95 **226 ms**, before adding the final CI schema/replay regression. Changed Python coverage: **17 lines, 0 missing, 100%**, exceeding the required 70%. The first coverage invocation lacked the optional `coverage` package; the successful command reused its already-cached archive via PYTHONPATH without installing dependencies.

```sh
cd /home/tien2003/tracecore-codex/apps/tracecore
pre-commit run --files tracecore/ui/page/station/station.js tracecore/ui/page/station/station.html tracecore/ui/page/station/station.css tracecore/public/js/station_t4.js tracecore/v1/pack.py tracecore/v1/tests/test_pack_api.py tracecore/v1/tests/test_station_security.py tracecore/tests/test_station_page.py tracecore/translations/vi.csv tests_e2e/test_station_auth.py tests_e2e/conftest.py tests_e2e/test_station_t4.py tests_e2e/test_station_smoke.py scripts/tests/station_auth.test.js
```

Final result: **exit 0**, every applicable hook passed (whitespace, conflicts, AST, debug statements, Ruff imports/lint/format, Prettier, ESLint, Bandit, architecture R1–R4 and BRU coverage). Initial runs applied normal formatter corrections only to Task 6 files; the complete final check passed after the final reader-event addition.

```sh
cd /home/tien2003/tracecore-codex
bench build --app tracecore
```

Final result after the last production change: **exit 0**, assets linked, CSS/RTL bundle built and translations compiled. Only the existing caniuse-lite age advisory appeared; no dependency update was made.

```sh
cd /home/tien2003/tracecore-codex/apps/tracecore
git diff --check
git add <the fourteen explicitly listed Task 6 files>
git diff --cached --check
git commit -m 'feat(station): add card session shell and dedicated indicator scan'
git rev-parse HEAD
git status --short
```

Result: commit **`2fd02f0e7271478c05938d92b1fcbab6f64af6d2`**; only untracked `.superpowers/` remains. No unrelated tracked changes.

## Self-review and remaining concerns

- Re-read Task 6 and Task 4 body-token contracts and checked every requested behavior against code and tests. Explicit project steering authorized the separate CI field and reader event contract.
- Reviewed auth/session clearing, late response barriers, transport headers/body, translations, focus and offline/idempotent behavior. Main scanner rejection preserves the existing open packing context; dedicated CI validation uses the same existing business resolver.
- Client heartbeat does not count as human activity. A no-activity kiosk locks at ten minutes; any authoritative server invalid/idle/expired/station-mismatch response clears it immediately. No client-only authorization is relied on.
- The Playwright cases run actual production frontend files and Chromium, but deterministically route the RPC boundary. They are **not** a live web-server-plus-MariaDB browser test. Real Frappe RPC/session/CI behavior is separately exercised in the 86 server/static tests. This division is explicit, not claimed as full-stack browser coverage.
- Physical card-reader hardware was not available. Removal/rescan adapter events are implemented and browser-tested, but a deployment's reader adapter must dispatch the documented events. No raw T4 barcode values are guessed to be cards.
- The existing live-site E2E fixtures now require `TC_E2E_CARD_ID` and `TC_E2E_T4_CARD_ID`. Task 7 devdata/e2e_prepare must export matching enabled Employee cards and valid competencies. The full existing live-site demo E2E suite was not run in this task.
- Python changed-code coverage is measured at 100%; JavaScript is verified with the seven unit and fifteen browser cases, without a separate JS percentage report.
- Already-authorized print HTTP requests cannot be retracted from a physical printer after logout; generation barriers prevent their late responses from restoring UI state. No packing business rules were changed.

No failing checks or blocking implementation concerns remain. The stated verification/hardware limitations are the reason for DONE_WITH_CONCERNS.
