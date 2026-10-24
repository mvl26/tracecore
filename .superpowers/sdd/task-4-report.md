# Task 4 implementation report

Commit: `461690f21280af95b57c86bcba6f9fc92dd1a2b2`
Message: `feat(home): build personalized hybrid dashboard`

## Scope and visual choices

Implemented `App.tsx`, `App.test.tsx`, `styles.css`, the real mount in `main.tsx`, and rebuilt the stable Home JS/CSS assets. No Task 2/3 API or registry changes, website route, login landing change, operational screen, or sample production business records were added.

Inspected the supplied `C:\Users\Admin\Downloads\TraceCore_UI_Screenshots.zip` inventory and viewed its overview (`02`), station receiving (`07`), and department (`18`) screenshots. Used their white sidebar, navy structural bar/headings, flat white cards, thin blue-gray borders, green empty-status block, and labeled warning/error surfaces. Reference images extracted only into uncommitted `.superpowers/sdd/references/`.

The desktop sidebar is fixed at 270px, derived from the 250px rail token plus the 20px spacing token. Four metric columns and two shortcut columns form the hybrid dashboard. At the token breakpoint of 900px, an explicit `Mở menu` / `Đóng menu` button expands compact inline navigation; Escape closes it and returns focus. At 480px, shortcuts become one column. Both media condition constants come directly from `docs/tokens.json` because CSS custom properties cannot be used in media conditions.

CSS imports the existing generated tokens, exposes only `--tc-*` properties, uses Arial/Segoe UI, includes visible keyboard focus and a skip link, and has no gradients, external fonts, icon fonts, shadows, or animation. The imported token bundle preserves reduced-motion handling.

Focused internal components are `Sidebar`, `HomeHeader`, `AttentionList`, `MetricGrid`, and `ShortcutGrid`. Navigation, metric links, header search entry, attention actions, and shortcut cards are authorized by the server capability list and resolved exclusively through the closed `resolveRoute` registry. Frappe Admin additionally requires its matching authorized shortcut. Unknown registry keys are omitted. Static Home/skip/login destinations are client-owned and never read from server URLs.

## State behavior

- Loading: a Home-shaped attention/metric/shortcut skeleton with `aria-busy` and loading status.
- Ready: only actual server identity, roles, stations, metrics, navigation, and shortcuts. Metrics are capped at six and shortcuts at eight.
- Empty: positive attention empty state, no empty metric/shortcut card containers, and an explanation when no shortcuts are permitted.
- Generic API failure: inline Vietnamese explanation and retry, without displaying response bodies or logging payloads.
- Permission error: clears identity and prior context and offers a context retry at Home.
- Session expired: clears context and redirects to `/login?redirect-to=%2Ftracecore` with a plain Vietnamese transition message.
- Stale: retains the single last successful in-memory snapshot, explicitly marks it read-only with the exact server timestamp, and replaces business links with disabled text until a fresh response succeeds.
- Offline: keeps an already loaded snapshot read-only, explains disabled server actions, or explains there is no saved data on a first offline visit. Reconnect requires a fresh context request before actions become usable. No current registry destination is declared offline capable, so none is allowed offline.
- API mismatch: clears context and requires controlled page reload.
- Logout: same-origin POST to `/api/method/logout`, clears context on success, and redirects to `/login`. Missing CSRF or a rejected logout shows an inline failure and does not pretend the session ended.

The cache is intentionally one `{ version: 1, context }` ref within the mounted App. No localStorage, sessionStorage, persistent service worker cache, payload logging, or telemetry was introduced. Refreshing or closing the page loses the snapshot, avoiding user identity leakage across browser sessions.

## Integration contracts and limits

Task 5 must supply a non-empty `<meta name="csrf-token" content="...">` from the authenticated website context. Logout reads only that independent boot value; it does not access `window.frappe`. Missing token fails closed and is covered by a component test. The parent confirmed this minimal integration contract.

API v1 intentionally returns `attention: []` / TypeScript `never[]`. Real Home therefore displays the empty attention state. To satisfy the required severity presentation test without inventing real alerts or widening the API contract, AttentionList tolerates only a complete forward-compatible presentation entry (`key`, `label`, `route_key`, `reason`, `severity`, `action_label`), then capability-checks and resolves its route. The test fixture is explicitly marked as future presentation data. A future backend aggregate still needs its own approved API/type change. Severity always includes text (`Khẩn cấp`, `Cảnh báo`, `Thông tin`) as well as color.

The actual identity API contains roles and authorized stations, not department or shift. These missing fields are omitted, not fabricated. Search is an authorized entry link to the registered route, not a new search implementation. No AuthProvider abstraction was added in this bounded task.

## TDD evidence

Before any App implementation, wrote the observable component suite and ran:

```text
npm test -- --run src/App.test.tsx
Exit 1: Failed to resolve import "./App" ... Does the file exist?
Test Files 1 failed (1)
```

This is the plan's intended absent-App RED. After implementing the shell, the initial run passed 15 of 17 tests. Two failures were caused by a test double returning the same already-consumed Response body on retry/reconnect. Corrected it to produce a fresh Response per request and scoped the reconnect link query to its semantic shortcut section. The expanded suite then passed all 19 cases.

The component suite covers all six brief-required observables plus both Frappe Admin gates, empty data, permission revocation, session redirect, offline read-only/reconnect behavior, initial offline, unknown/unauthorized routes, API mismatch, menu open/Escape, logout success, missing CSRF, and rejected logout without raw error disclosure.

The authorized architecture-checker adjustment was separately test-first:

```text
python3 -m unittest scripts.tests.test_check_architecture
RED: Ran 3 tests; FAILED (failures=1)
     expected no violations for exactly home.js/home.css, got R3 and R4
GREEN: Ran 3 tests; OK
```

## Authorized check-tool adjustment

The first scoped pre-commit run correctly exposed checker false positives against newly generated artifacts: minified `home.js` loses source translation wrappers, and bundled `home.css` contains generated primitive token definitions and flattened media queries.

The parent explicitly authorized a minimal change to `scripts/check_architecture.py`: skip exactly `tracecore/public/home/home.js` and `tracecore/public/home/home.css`. Added `scripts/tests/test_check_architecture.py` with three regression cases proving the exemption and proving both other filenames in the Home directory and the same filenames in another directory remain checked. No source rule or directory-wide exclusion was relaxed, and no Vite/tool/dependency config changed.

## Final verification

- `npm test`: exit 0, 40/40 tests across three files (19 App + 21 existing adapter/registry tests).
- `npm run build`: exit 0, strict TypeScript build and Vite 5.4.21, 31 modules transformed.
- `python3 -m unittest scripts.tests.test_check_architecture`: exit 0, 3/3 tests.
- Installed Prettier 2.7.1 `--check` on the four frontend source files: all matched files use Prettier style. This explicit run includes TS/CSS that existing JS-only hooks skip.
- Final scoped `pre-commit run --files ...`: exit 0. Whitespace, conflicts, Python AST/debug checks, Ruff import/lint/format, Bandit, architecture, and BRU marker checks passed. Irrelevant hooks skipped. A previous run overlapped frontend formatting and reported files modified; the final sequential run passed without mutations.
- `git diff --cached --check`: exit 0 before the commit.
- Self-review checked the five internal components, server-driven values, registry-only server destinations, dual admin gate, stale/offline disabling, CSRF fail-closed behavior, no payload storage/logging, semantic labels/focus, and narrow generated exceptions.
- After commit: no tracked changes or staged files remain; only the existing uncommitted `.superpowers/` artifacts remain. This report is also deliberately uncommitted.

WSL access required the normal approved escalation because the sandbox returned `Wsl/Service/E_ACCESSDENIED`. The actual checks then ran in the existing WSL environment. No package or dependency versions were changed.

## Built assets

| Asset | Bytes | Vite gzip |
| --- | ---: | ---: |
| `tracecore/public/home/home.js` | 154,011 | 49.41 kB |
| `tracecore/public/home/home.css` | 12,583 | 3.21 kB |

SHA-256:

```text
home.js  5FF077EB2E45DAF2D8CB427F84D2EFC4079D3298DE573703CD7B094203A46608
home.css E936351E0F39F4EC745F5C946F4E057AB6956FD114E21210B0CDB6C3891DA629
```

## Remaining verification boundaries

No live browser screenshot/E2E or coverage instrumentation was run for this component task. The screenshot ZIP was visually inspected; desktop/PDA rendering, actual website boot/CSRF, real logout, and integrated navigation should be exercised in the planned integration task once the Task 5 route exists. The default WSL Python has no Playwright package. This report does not claim browser-level layout or changed-code coverage results.

In-memory stale/offline reading works only after a successful load in the current mounted session. Durable offline/PWA caching and offline-capable route declarations remain deferred. Existing dependency audit concerns from Task 3 remain unchanged.

## Review follow-up — logout/context concurrency and Escape focus

Fix commit: `cde6f9585a2142074389deab1640a594c78b4824`
Message: `fix(home): serialize logout and context refresh`

The review identified two related request-ordering defects in the initial implementation. Logout invalidated context requests only when it started; a reconnect could start another context request while logout was pending, and that response could restore identity and actions after successful logout. Also, invalidating a pending refresh prevented its `finally` from clearing `refreshing`, so failed logout could strand both refresh and inline retry permanently disabled.

Added a synchronous session gate (`active`, `logging-out`, `ended`) alongside the request generation. Context loads return before fetching unless the session is active, and responses must still match both the active session and current generation before updating presentation. Logout moves the gate synchronously before awaiting, invalidates pending loads and clears their refresh state. Successful logout invalidates requests again and permanently closes the gate for the mounted App; reconnect/offline events cannot reopen the ended session. Failed logout reopens the gate so a fresh explicit refresh/retry can recover. Refresh and retry controls are disabled while logout is pending. Duplicate logout attempts also return through the same synchronous guard.

Self-review found one adjacent edge: if the browser blocks the login redirect after the logout endpoint succeeded, the broad error handler must not reopen the already-ended session. Added a regression test and limited recovery to logout failures before the ended state. A successful server logout remains final even when navigation cannot proceed.

Escape now closes the compact menu and returns focus only when that menu is open. The original menu test asserts actual focus restoration, and a new test confirms Escape preserves focus on the current control when the menu is already closed.

TDD evidence:

```text
Before fixes: npm test -- --run src/App.test.tsx --reporter=dot
25 tests: 6 failed, 19 passed.
- Two deferred response orderings restored Home after successful logout.
- Two failed-logout orderings left refresh stuck in its loading state.
- Stale inline retry remained disabled after a canceled refresh/failed logout.
- Escape stole focus when the menu was closed.

After the request/focus fixes: 25/25 component tests passed.

Additional blocked-redirect regression RED:
npm test -- --run src/App.test.tsx -t "keeps successful logout final"
Expected fetch twice, got three calls after a reconnect.

After sticky-ended-state fix: final npm test passed 47/47
(26 component + 21 existing adapter/registry tests; three files).
```

Deferred tests explicitly resolve refresh before logout and logout before refresh, for both successful and rejected logout. They exercise reconnect while logout is pending and after success, assert no identity/action resurrection, and prove refresh/inline retry can start fresh requests after failure.

Final verification for the fix commit:

- `npm test`: exit 0, 47/47.
- `npm run build`: exit 0, strict TypeScript + Vite, 31 modules transformed.
- Installed Prettier `--check` on both edited source files: exit 0.
- Scoped pre-commit on edited source and built Home assets: exit 0; whitespace, conflict, and architecture checks passed, unrelated hooks skipped.
- `git diff --cached --check`: exit 0 before commit.
- Tracked tree clean after commit; `.superpowers/` remains uncommitted.

Regenerated `home.js`: 154,275 bytes; Vite reports 153.88 kB / 49.49 kB gzip. SHA-256 `C91137616D56A4058F3333AFD4B8D914F279FB209045A0B49CA208F31B3BC55C`. Rebuilt `home.css` remains byte-identical at 12,583 bytes and therefore is not included in the fix commit. No API, route, CSS, checker, dependency, or persistent-cache change was made in this follow-up.

## Re-review follow-up — preserve offline state across rejected logout

Fix commit: `3ebb6ff48abef85896567c79d3951f990ea1a806`
Message: `fix(home): preserve offline state across logout`

The re-review identified an offline transition lost while logout was pending. The offline handler updated connection state but returned before recording a stale phase because the session was `logging-out`. If logout was rejected, reconnect could therefore restore cached business links immediately, either before starting a fresh context request or while that request was still pending.

Changed only the offline handler's guard: it now ignores phase updates for an `ended` session, while both `active` and `logging-out` sessions record the cache as stale and invalidate prior context requests. Successful logout still ends the session and clears context, preserving the previous race/focus fixes.

Added two deferred-response regression cases:

- Reconnect before rejected logout: reconnect cannot fetch while logout is pending; after rejection the snapshot stays explicitly stale/read-only. The user can press inline retry, and actions remain disabled until that fresh response succeeds.
- Reconnect after rejected logout: reconnect starts a fresh deferred context request but cached actions remain disabled throughout the wait; only the successful fresh response restores them.

Both tests assert that station and search links remain absent, the stale label remains visible, the cached metric remains at its previous value, and the fresh response must replace that value before authorized links reappear. They verify no login redirect occurs for rejected logout.

TDD evidence:

```text
npm test -- --run src/App.test.tsx -t "keeps cached actions read-only"
RED: 2 failed, 26 skipped; expected zero station links, received two
     for both reconnect/rejection orderings.

After guard fix:
npm test -- --run src/App.test.tsx
GREEN: 28/28 component tests.
```

Final verification: `npm test` exit 0, 49/49 frontend tests across three files; `npm run build` exit 0 with strict TypeScript and 31 Vite modules; explicit Prettier `--check` exit 0; scoped pre-commit exit 0 (whitespace, conflict, architecture checks pass; irrelevant hooks skipped); staged diff check exit 0. Self-review confirmed the source change is limited to the offline guard and that ended sessions remain protected. Tracked tree is clean after the commit, with `.superpowers/` deliberately uncommitted.

Regenerated JS: 154,274 bytes; Vite reports 153.87 kB / 49.48 kB gzip. SHA-256 `87823C91E89BD6E1A4A238C5923C98D5F64C3D688753EEC86A8DCD954E44DCB5`. CSS rebuilt unchanged at 12,583 bytes and is not part of this fix commit. No additional scope or verification limitations changed.
