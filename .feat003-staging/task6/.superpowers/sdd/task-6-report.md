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

---

# Task 6 review-fix report (authoritative update)

Latest status: **DONE_WITH_CONCERNS**. All four supported review findings and the keyboard regression request are implemented and verified. The original hardware/live-stack browser limitations still apply; no review finding remains unresolved.

Fix commit: **`0e773b01aafa6e6581d168074e45868d0df19b7e`**

Parent: `2fd02f0e7271478c05938d92b1fcbab6f64af6d2`.

Seven Task 6 files changed: station JS/template, station heartbeat RPC, security tests, browser tests, Node tests and translations. Commit scope: 511 insertions / 93 deletions. The tracked worktree is clean; `.superpowers/` remains the preserved untracked handoff directory. No normal development bench or tracked Windows source was modified.

## Verified causes and final behavior

1. **New card while login is pending.** The former `authBusy` early return discarded card B while request A was pending. Each valid card login now invalidates the preceding auth generation immediately and replaces the queued intent with the latest card. Requests run serially. An already-sent A response can never activate after B arrives: a successful stale A token is revoked, then B is submitted. Intermediate queued scans can be superseded by the latest scan. This also prevents a late earlier server login from replacing the final desired session in ordinary received-response ordering.

2. **Restore races.** The former handshake assigned `{token}` to the active session before validation, then could clear a newer login when its old heartbeat finished. Restore now holds a separate candidate and leaves `session === null` and work hidden. Success, structured denial and transport failure all check the same auth generation, candidate identity, current visible ownership and exact currently stored candidate token. A later card intent invalidates that candidate. Old success and old HTTP 401 cannot activate, overwrite identity, clear a new session or delete its token. A transport failure does not prove that the stored credential is invalid, so storage is preserved while the local UI stays locked.

3. **Page lifecycle/ownership.** Global reader/network handlers now exist only while the instance is the visible `frappe.tc_station` owner. DOM/global listener wrappers are retained explicitly and removed on disposal; global listeners and the periodic timer are removed on hide. Read/heartbeat requests are aborted and auth generations/queued work are invalidated. A possibly committed login is logically cancelled rather than blindly discarded: its response is still received and its stale token revoked. Replacement waits the predecessor's auth/cleanup barrier before submitting another login. Every intermediate replacement retains that predecessor barrier, even if the intermediate page never starts its own login. Storage cleanup removes only the token belonging to that old active session/candidate; it cannot erase a replacement's different token. Hiding an unvalidated candidate preserves its valid stored token for the next owner to validate.

4. **Roles on login and restore.** The session row now renders translated `Roles: {0}` and translates each TC role code. Vietnamese role labels R01–R10 follow the approved SRS role descriptions. Heartbeat now returns employee display name and current TC roles so validated tab restore has the same display information as login. Roles, identity and expiry clear when the session ends. Neither identity nor role metadata is added to persistent token storage.

5. **Keyboard navigation.** The focus helper preserves deliberate focus on any visible interactive control inside the station. Deferred scanner blur callbacks no longer pull focus away from logout/rescan buttons. Keyboard Shift+Tab navigation and Enter activation are browser-tested for both controls; session transitions still focus the appropriate scanner.

## Exact RED evidence

From the app directory, before production fixes:

```sh
uv run --offline --no-project --with pytest-playwright --python /home/tien2003/tracecore-codex/env/bin/python pytest tests_e2e/test_station_auth.py -q -k 'latest_scan or restore_candidate or late_restore or hidden_page or replaced_page or roles_are or keyboard_tab'
```

Result: **9 failed, 15 deselected in 32.64s**. The failures showed:

- Delayed login A activated `Operator CARD-A`; B was never processed.
- Restore exposed a non-null active session before the server reply.
- Both delayed old restore success and delayed old 401 hid/cleared the newer B work.
- A hidden instance submitted an extra reader login (2 versus 1 expected).
- A replaced instance's leaked listener submitted a duplicate reader login.
- The roles element was absent.
- Both keyboard session-control cases lost button focus to the old 150ms scanner timer.

```sh
node --test scripts/tests/station_auth.test.js
```

Result before production fixes: **7 passed, 2 failed**. The actual login list was `[A]` rather than `[A,B]`, and old-instance cleanup deleted a different owner's stored token. After queue serialization added legitimate asynchronous steps, the pending-login test was updated to wait one Node event-loop turn (`setImmediate`) for the actual pending request instead of assuming one microtask; the original meaningful RED assertions were already observed against the unfixed code.

From the bench directory:

```sh
bench --site test_codex run-tests --module tracecore.v1.tests.test_station_security --test test_guest_heartbeat_logout_and_structured_errors --skip-test-records
```

Result: **1 failure in 1.810s**, `None != 'Station RPC'`, proving the heartbeat lacked display identity; the same test now asserts both name and `["TC R04"]` roles.

After the first implementation, the initial full green run was **24 browser tests** and **9 Node tests**. Further lifecycle self-review added two regressions:

```sh
uv run --offline --no-project --with pytest-playwright --python /home/tien2003/tracecore-codex/env/bin/python pytest tests_e2e/test_station_auth.py -q -k 'repeated_replacements or hiding_pending_restore'
```

Result: **1 failed, 1 passed, 24 deselected in 0.90s**. Two successive replacements lost the original pending login barrier when the intermediate instance had no worker. Including `this.authBarrier` in disposal's returned cleanup promise fixed the chain. The hide/restore test already passed and verifies that a late old denial cannot remove the preserved candidate or supersede the new validation.

## Final GREEN, regressions, lint and build

All commands ran in the isolated Ubuntu-22.04 Codex bench; no downloads were required.

```sh
cd /home/tien2003/tracecore-codex/apps/tracecore
node --test scripts/tests/station_auth.test.js
uv run --offline --no-project --with pytest-playwright --python /home/tien2003/tracecore-codex/env/bin/python pytest tests_e2e/test_station_auth.py -q --screenshot=on --output=.superpowers/sdd/task6-review-browser-artifacts
```

Final result after formatting and all fixes: **9/9 Node tests passed; 26/26 Chromium browser tests passed in 9.81s**. The new eleven browser cases include delayed A→B login, inactive restore candidate, old restore success/401 after B, hidden instance, replacement listener/timer disposal, roles across login/restore/end, logout/rescan keyboard navigation, two replacements retaining the original pending login barrier, and hide/show preserving a pending restore while ignoring its old denial. All original fifteen auth/CI/offline/kiosk/PDA browser cases remain green. Screenshots are under `.superpowers/sdd/task6-review-browser-artifacts/`.

```sh
cd /home/tien2003/tracecore-codex
bench --site test_codex run-tests --module tracecore.tests.test_station_page --skip-test-records
bench --site test_codex run-tests --module tracecore.v1.tests.test_station_security --skip-test-records
bench --site test_codex run-tests --module tracecore.v1.tests.test_pack_api --skip-test-records
```

Final results: **11 station-page tests OK (3.161s); 18 security tests OK (36.622s); 51 packing tests OK (112.188s)**. Packing Cycle ID generation P95 was **146 ms**, maximum **271 ms**. The full packing suite confirms the lifecycle fixes preserve the dedicated CI path and existing packing/idempotency rules. Translation coverage and no-other-app-override checks pass with the new role labels.

```sh
cd /home/tien2003/tracecore-codex/apps/tracecore
pre-commit run --files tracecore/ui/page/station/station.js tracecore/ui/page/station/station.html tracecore/v1/station.py tracecore/v1/tests/test_station_security.py tracecore/translations/vi.csv scripts/tests/station_auth.test.js tests_e2e/test_station_auth.py
cd /home/tien2003/tracecore-codex
bench build --app tracecore
```

Final results: **pre-commit exit 0**, all applicable hooks passed; **build exit 0**, assets/translations compiled. Initial formatter runs reformatted only changed Task 6 files and were followed by the complete clean run. The build emitted only the unchanged caniuse-lite age advisory.

Additional focused coverage command:

```sh
env PYTHONPATH=/home/tien2003/.cache/uv/archive-v0/NKwABb-qbyvo3e43 bench --site test_codex run-tests --app tracecore --module tracecore.v1.tests.test_station_security --test test_guest_heartbeat_logout_and_structured_errors --coverage --skip-test-records
cd apps/tracecore
diff-cover /home/tien2003/tracecore-codex/sites/coverage.xml --compare-branch=2fd02f0e7271478c05938d92b1fcbab6f64af6d2 --fail-under=70
```

Focused test **passed (1 test, 3.873s)** and saved coverage. `diff-cover` exited 0 with **“No lines with coverage information in this diff.”** The two Python changes are additional entries in the existing returned dict; this Python coverage instrumentation attributes execution to the existing return line rather than those two continuation lines. No new percentage is claimed for this review diff. Both fields are asserted against a real Guest heartbeat, and the original Task 6 executable Python diff was previously measured at 100% as recorded above.

```sh
git diff --check
git add scripts/tests/station_auth.test.js tests_e2e/test_station_auth.py tracecore/translations/vi.csv tracecore/ui/page/station/station.html tracecore/ui/page/station/station.js tracecore/v1/station.py tracecore/v1/tests/test_station_security.py
git diff --cached --check
git commit -m 'fix(station): serialize auth attempts and dispose page ownership'
git rev-parse HEAD
git status --short
```

Result: **`0e773b01aafa6e6581d168074e45868d0df19b7e`**; only the preserved untracked `.superpowers/` remains.

## Review-fix self-review and concerns

All four findings were reproduced before their fixes, and the keyboard issue was also reproduced. Re-read the final code for common success/error guards, latest-intent ordering, stale-token revocation, inherited cleanup barriers, listener ownership, storage token matching and translated identity cleanup. Backend role data comes from the authenticated session's linked User, not the surrounding cookie user.

The predecessor chain regression verifies actual request ordering and a successful final heartbeat after two remounts; it does not merely assert a disposed flag. The hidden restore regression verifies the exact stored token survives and the late old 401 cannot affect a new candidate. No known auth-race, ownership or keyboard finding remains open.

Remaining limitations are unchanged: routed-RPC Chromium tests are complemented by real Frappe RPC tests rather than a full live-stack browser run; physical reader hardware was unavailable; Task 7 must supply card env variables for the separate live-site demo suite. These are the reasons for retaining DONE_WITH_CONCERNS, not unresolved review failures.

---

# Task 6 v2 review saved-token fix (authoritative update)

Latest status: **DONE_WITH_CONCERNS**, with only the previously documented hardware/live-stack test limitations. The remaining saved-token P1 is fixed.

Commit: **`4b7d6fb550497bbfea9c26bc72cc857daf448510`**

Parent: `0e773b01aafa6e6581d168074e45868d0df19b7e`.

Exactly three files changed: `tracecore/ui/page/station/station.js`, `scripts/tests/station_auth.test.js`, and `tests_e2e/test_station_auth.py` (122 insertions / 4 deletions). No backend or packing-rule code changed. The tracked worktree is clean; only the preserved untracked `.superpowers/` handoff artifacts remain.

## Cause, behavior and ownership safeguards

Explicit removal previously looked only at `session.token` and `restoreCandidate.token`. Before initial restore, or after a transport-failed restore deliberately preserved storage, both were null while the saved bearer remained in `sessionStorage`. The removal therefore neither deleted nor revoked it, and a later handshake could restore the removed operator.

`endSession()` now captures the saved token when the current visible owner explicitly ends the session and no active/candidate token exists. It clears that exact stored token synchronously, invalidates auth attempts through the existing clear path, and attempts server logout with the captured token. Both before-restore and failed-restore paths remain locked after a subsequent handshake, and browser tests assert the server logout body contains the saved bearer and the synthetic active server session has ended.

Hide/dispose still pass `keepStoredCandidate: true`: they preserve unvalidated saved storage and do not use this explicit-removal fallback. Active-session hide continues its normal logout/clear behavior. Generic cleanup additionally checks current instance ownership before deleting storage. A retired/disposed instance cannot capture a replacement's saved token, erase it even if its old token string matches, or send logout for that replacement credential. Exact token matching is retained, so cleanup cannot remove a different value written under the same storage key.

## RED evidence

Before production changes, from the isolated app directory:

```sh
node --test scripts/tests/station_auth.test.js
uv run --offline --no-project --with pytest-playwright --python /home/tien2003/tracecore-codex/env/bin/python pytest tests_e2e/test_station_auth.py -q -k 'card_removal_before_initial or card_removal_after_failed'
```

Initial Node result: **11 passed, 1 failed**, proving explicit end left the stored bearer present with no active/candidate token. Additional stale-owner/same-token self-review produced **11 passed, 2 failed**, proving retired cleanup could also remove a replacement's equal-valued stored token. The fix makes that case issue no logout request as well. Existing stale-owner/different-token and hide-preservation checks passed before and after the fix.

Browser RED: **2 failed, 26 deselected in 1.08s**. Both tests expected storage to be empty immediately after `tc-card-removed`, but received `browser-private-1`: one test delays the first station ping before any restore candidate exists, and the other injects a restore transport failure that preserves the saved token.

## Final verification

```sh
cd /home/tien2003/tracecore-codex/apps/tracecore
node --test scripts/tests/station_auth.test.js
uv run --offline --no-project --with pytest-playwright --python /home/tien2003/tracecore-codex/env/bin/python pytest tests_e2e/test_station_auth.py -q
pre-commit run --files tracecore/ui/page/station/station.js scripts/tests/station_auth.test.js tests_e2e/test_station_auth.py
git diff --check
```

After the final formatter changes: **13/13 Node tests passed; 28/28 Chromium browser tests passed in 12.74s; pre-commit exit 0; diff whitespace check clean**. All prior auth races, delayed restore success/401, ownership/remount barriers, role display, keyboard access, CI, offline and kiosk/PDA cases remain green. The four added Node checks cover saved-only explicit logout, retired saved-token capture, hide-style preservation and retired equal-token cleanup. The two added browser cases verify both removal windows and subsequent handshake behavior.

```sh
cd /home/tien2003/tracecore-codex
bench --site test_codex run-tests --module tracecore.tests.test_station_page --skip-test-records
bench build --app tracecore
```

Results: **11 station-page tests OK (4.715s); build exit 0**, assets/translations compiled. The existing caniuse-lite age advisory remains unchanged. Pre-commit's first pass applied normal formatting to the changed JS/browser test; the full final pass was clean. Server security/packing suites were not repeated for this frontend-only patch; their latest full passing runs are recorded in the previous section.

```sh
git add tracecore/ui/page/station/station.js scripts/tests/station_auth.test.js tests_e2e/test_station_auth.py
git diff --cached --check
git commit -m 'fix(station): revoke saved token on explicit card removal'
git rev-parse HEAD
git status --short
```

Result: **`4b7d6fb550497bbfea9c26bc72cc857daf448510`**; tracked worktree clean. The report remains an untracked handoff artifact, as in prior Task 6 commits. No open saved-token, auth-race or ownership finding remains.
