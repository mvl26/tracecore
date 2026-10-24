# TraceCore Independent Home Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a real React Home at `/tracecore` that replaces the normal Frappe landing experience, uses the current Frappe session, shows role-authorized TraceCore actions and real summary data, and retains controlled links to Frappe Desk.

**Architecture:** A React/TypeScript/Vite application lives in `frontend/`, builds into `tracecore/public/home/`, and is served by a Frappe website route rather than the Desk shell. Frappe remains authoritative for authentication, permissions, data, and routing capabilities through `tracecore.v1.home.context`; frontend routes resolve only registered `route_key` values.

**Tech Stack:** Frappe v15, Python 3.11, Node 18, React 18.3.1, TypeScript 5, Vite 5, Vitest, Testing Library, Playwright Python.

## Global Constraints

- The current feature is the Home replacement only; do not rebuild the 21 operational screenshots.
- Use the existing Frappe cookie session and CSRF behavior; do not add token authentication.
- Do not import Frappe Desk JavaScript, CSS, router, or UI components into `frontend/`.
- All permission and business decisions remain on the server; hiding a link in React is not authorization.
- Routes under `/tracecore/*` belong to the new application; `/app/*` is an allowlisted fallback.
- Preserve the visual language of the supplied screenshots and use values generated from `docs/tokens.json`.
- Vietnamese is the user-facing language; stable API identifiers remain untranslated.
- Never return or log patient identifiers in Home context, browser logs, recent records, or telemetry.
- Use TDD. Run each failing test before implementation and the focused passing test afterward.
- Do not commit `.superpowers/` mockup files.

---

## File map

| File | Responsibility |
| --- | --- |
| `docs/architecture.md` | Proposed amendment permitting the independent SPA and recording its boundary |
| `docs/srs.md` | Revision note pointing to the Home amendment without adding FR/BRU IDs |
| `frontend/package.json` | Reproducible frontend scripts and dependencies |
| `frontend/vite.config.ts` | Build into Frappe public assets with `/assets/tracecore/home/` base |
| `frontend/src/api.ts` | Frappe-session API adapter and typed Home contract |
| `frontend/src/routes.ts` | Closed route registry for SPA and Frappe fallback destinations |
| `frontend/src/App.tsx` | Application shell and Home composition |
| `frontend/src/styles.css` | Screenshot-aligned responsive Home styles using `--tc-*` tokens |
| `frontend/src/*.test.tsx` | Route, state, rendering, and permission-presentation tests |
| `tracecore/www/tracecore.py` | Authenticated Frappe website context for the SPA shell |
| `tracecore/www/tracecore.html` | Minimal root element plus built asset tags; no Desk chrome |
| `tracecore/v1/home.py` | Authoritative role-personalized Home context endpoint |
| `tracecore/v1/tests/test_home_api.py` | API contract and permission tests |
| `tracecore/core/account.py` | Login landing route selection without weakening password checks |
| `tracecore/core/tests/test_account.py` | Landing-route tests |
| `tracecore/hooks.py` | Website route rules for `/tracecore` and deep routes |
| `tracecore/tests/test_home_page.py` | Website shell, hooks, and built-asset registration tests |
| `tests_e2e/test_home.py` | Desktop/PDA redirect, Home, fallback, and logout flows |

---

### Task 1: Record the architecture amendment

**Files:**
- Modify: `docs/architecture.md`
- Modify: `docs/srs.md`

**Interfaces:**
- Consumes: approved design `docs/superpowers/specs/2026-10-24-tracecore-independent-home-design.md`
- Produces: an amendment number checked against the current revision table and a normative exception to ADR-002

- [ ] **Step 1: Check the next amendment number**

Run:

```powershell
rg -n "Amendment A-" docs/architecture.md | Select-Object -First 40
```

Expected: every allocated amendment is visible; choose the next unused number and use it consistently below.

- [ ] **Step 2: Add the revision entry and ADR-002 exception**

Add a revision entry stating exactly:

```markdown
TraceCore may serve an independent React application at `/tracecore/*`. Frappe remains the system of record and authorization boundary. `/app/*` remains a temporary, allowlisted administration fallback. The first deployment uses the same-origin Frappe session; `AuthProvider` and `ApiClient` isolate that choice for later separate-domain deployment.
```

Update the ADR-002 section so the old “Không SPA riêng” sentence points to this amendment rather than remaining an unconditional rule.

- [ ] **Step 3: Add the SRS revision note**

State that no FR/BRU IDs change and scope is only the Home entry experience.

- [ ] **Step 4: Verify documentation formatting**

Run:

```powershell
pre-commit run --files docs/architecture.md docs/srs.md
```

Expected: all hooks pass.

- [ ] **Step 5: Commit**

```powershell
git add -- docs/architecture.md docs/srs.md
git commit -m "docs: allow independent TraceCore home"
```

---

### Task 2: Add the authoritative Home context API

**Files:**
- Create: `tracecore/v1/home.py`
- Create: `tracecore/v1/tests/test_home_api.py`

**Interfaces:**
- Consumes: `tracecore.v1.navigation.STEP_ROLES`, current Frappe session, DocType permissions
- Produces: `context() -> dict` with `user`, `capabilities`, `navigation`, `attention`, `metrics`, `shortcuts`, `system`, and `etag`

- [ ] **Step 1: Write failing contract and permission tests**

Cover these concrete cases in `TestHomeContext(FrappeTestCase)`:

```python
def test_guest_cannot_read_home(self): ...
def test_r03_receives_station_shortcut_without_admin_link(self): ...
def test_system_manager_receives_frappe_admin_capability(self): ...
def test_doctype_shortcut_requires_read_permission(self): ...
def test_metrics_use_real_counts_and_never_patient_fields(self): ...
def test_route_keys_are_closed_identifiers_not_urls(self): ...
def test_context_etag_is_stable_for_equal_payload(self): ...
```

Assert the exact top-level key set and shortcut shape:

```python
{"key", "label", "description", "route_key", "badge"}
```

- [ ] **Step 2: Run the API tests and confirm failure**

Run:

```powershell
wsl -d Ubuntu-22.04 -- bash -lc "cd ~/tracecore-dev && bench --site test_site run-tests --module tracecore.v1.tests.test_home_api"
```

Expected: FAIL because `tracecore.v1.home` does not exist.

- [ ] **Step 3: Implement the minimal typed payload builders**

Implement focused helpers:

```python
ROUTE_KEYS = frozenset({
    "station", "search", "set-units", "packs", "equipment",
    "par-levels", "frappe-admin",
})

def _identity(user: str, roles: set[str]) -> dict: ...
def _navigation(roles: set[str]) -> list[dict]: ...
def _shortcuts(roles: set[str]) -> list[dict]: ...
def _metrics(roles: set[str]) -> list[dict]: ...
def _attention(roles: set[str]) -> list[dict]: ...
def _etag(payload: dict) -> str: ...

@frappe.whitelist(methods=["GET"])
def context(): ...
```

Rules:

- reject `Guest` with `frappe.PermissionError`;
- call `frappe.has_permission` before exposing each DocType shortcut or metric;
- derive station choices from the same active-station query used by `navigation.context`;
- use real aggregate counts only; omit unavailable metric types instead of inventing zero/sample data;
- expose `frappe-admin` only to Administrator/System Manager;
- return stable English identifiers and translated display strings;
- compute SHA-256 over canonical JSON excluding `etag`, truncated to 16 hex characters;
- include `system.api_version = 1` and server timestamp; exclude the timestamp from ETag input.

- [ ] **Step 4: Run focused tests**

Run the Task 2 command again.

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add -- tracecore/v1/home.py tracecore/v1/tests/test_home_api.py
git commit -m "feat(home): add role-personalized context API"
```

---

### Task 3: Add the independent Vite application foundation

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/tsconfig.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/index.html`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/api.ts`
- Create: `frontend/src/routes.ts`
- Create: `frontend/src/routes.test.ts`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `GET /api/method/tracecore.v1.home.context`
- Produces: `homeApi.context(): Promise<HomeContext>` and `resolveRoute(routeKey, params?): string`

- [ ] **Step 1: Add the package manifest and deterministic scripts**

Use these scripts:

```json
{
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "test": "vitest run",
    "test:watch": "vitest"
  }
}
```

Pin React 18.3.1, React DOM 18.3.1, React Router DOM 6.30.1, Vite 5.4.x, TypeScript 5.7.x, Vitest 2.1.x, jsdom, and Testing Library. Commit the generated lockfile after installation.

- [ ] **Step 2: Write failing route-registry tests**

Assert:

```ts
expect(resolveRoute("search")).toBe("/tracecore/search");
expect(resolveRoute("frappe-admin")).toBe("/app");
expect(() => resolveRoute("https://evil.example")).toThrow("Unknown TraceCore route");
```

- [ ] **Step 3: Run and observe the failure**

Run:

```powershell
Set-Location frontend
npm ci
npm test -- --run src/routes.test.ts
```

Expected: FAIL because the registry implementation is absent.

- [ ] **Step 4: Implement API and route adapters**

`api.ts` must call same-origin Frappe endpoints with `credentials: "same-origin"`, parse `message`, translate HTTP 401/403 into `SessionExpiredError`/`PermissionError`, and never depend on `window.frappe`.

`routes.ts` must contain a closed mapping:

```ts
const ROUTES = {
  search: "/tracecore/search",
  station: "/app/station",
  "set-units": "/app/set-unit",
  packs: "/app/pack",
  equipment: "/app/equipment",
  "par-levels": "/app/par-level",
  "frappe-admin": "/app",
} as const;
```

- [ ] **Step 5: Configure build output**

Set Vite `base` to `/assets/tracecore/home/`, `outDir` to `../tracecore/public/home`, `emptyOutDir: true`, and stable entry names `home.js`/`home.css` so the Frappe template can reference them without reading a manifest at request time.

- [ ] **Step 6: Pass frontend tests and build**

Run:

```powershell
npm test
npm run build
```

Expected: tests pass and `tracecore/public/home/home.js` plus `home.css` exist.

- [ ] **Step 7: Commit**

```powershell
git add -- frontend .gitignore tracecore/public/home/home.js tracecore/public/home/home.css
git commit -m "feat(home): add independent React foundation"
```

---

### Task 4: Build the real Home application shell

**Files:**
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/App.test.tsx`
- Create: `frontend/src/styles.css`
- Modify: `frontend/src/main.tsx`

**Interfaces:**
- Consumes: `HomeContext`, `homeApi.context`, `resolveRoute`
- Produces: `<App />` with loading, ready, empty, permission, session-expired, stale, and offline states

- [ ] **Step 1: Write failing component tests**

Test exact user-observable behavior:

```tsx
it("renders identity, attention, metrics and authorized shortcuts", async () => ...);
it("does not render Frappe Admin without its capability", async () => ...);
it("renders Home-shaped skeleton while loading", () => ...);
it("renders inline retry on API failure", async () => ...);
it("labels stale cached content with its timestamp", async () => ...);
it("uses text as well as color for severity", async () => ...);
```

- [ ] **Step 2: Confirm tests fail**

Run:

```powershell
Set-Location frontend
npm test -- --run src/App.test.tsx
```

Expected: FAIL because `App` is absent.

- [ ] **Step 3: Implement the Home shell and hybrid layout**

Create focused internal components in `App.tsx` for `Sidebar`, `HomeHeader`, `AttentionList`, `MetricGrid`, and `ShortcutGrid`. Keep each driven entirely by the API payload. Use semantic `<nav>`, `<main>`, `<section>`, headings, buttons/links, `aria-current`, and visible focus.

Do not add sample operational data. Empty server lists render the approved empty message and no blank cards.

- [ ] **Step 4: Implement screenshot-aligned responsive CSS**

Use only `--tc-*` custom properties. Desktop uses a 270 px sidebar and card grid; at 900 px and below, replace the sidebar with an explicit menu button. Do not use gradients, web fonts, icon fonts, hover-only actions, or color-only statuses.

- [ ] **Step 5: Pass tests and rebuild assets**

Run:

```powershell
npm test
npm run build
```

Expected: all frontend tests pass and built assets update.

- [ ] **Step 6: Commit**

```powershell
git add -- frontend/src tracecore/public/home
git commit -m "feat(home): build personalized hybrid dashboard"
```

---

### Task 5: Serve the SPA outside the Desk shell

**Files:**
- Create: `tracecore/www/tracecore.py`
- Create: `tracecore/www/tracecore.html`
- Create: `tracecore/tests/test_home_page.py`
- Modify: `tracecore/hooks.py`

**Interfaces:**
- Consumes: built `/assets/tracecore/home/home.js` and `home.css`
- Produces: authenticated website route `/tracecore` and deep-route fallback `/tracecore/<path>`

- [ ] **Step 1: Write failing route and shell tests**

Assert:

```python
def test_tracecore_home_is_served_without_desk_shell(): ...
def test_tracecore_deep_route_uses_same_shell(): ...
def test_guest_is_redirected_to_login_with_tracecore_return_route(): ...
def test_home_shell_references_built_assets(): ...
def test_route_rules_do_not_capture_api_or_assets(): ...
```

The shell assertion must require `<div id="tracecore-root"></div>` and reject Desk markers such as `desk.bundle.js`.

- [ ] **Step 2: Run and observe failure**

Run:

```powershell
wsl -d Ubuntu-22.04 -- bash -lc "cd ~/tracecore-dev && bench --site test_site run-tests --module tracecore.tests.test_home_page"
```

Expected: FAIL with missing website page/route.

- [ ] **Step 3: Implement the website shell**

`tracecore.py` sets `no_cache = 1`, rejects Guest by redirecting to `/login?redirect-to=/tracecore`, and otherwise returns only non-sensitive boot values needed before the API call: language and CSRF token.

`tracecore.html` extends `templates/web.html`, disables website navigation/footer for this route, mounts `tracecore-root`, and references only the built Home CSS/JS plus the token bundle required by the design system.

- [ ] **Step 4: Register exact route rules**

Add rules for `/tracecore` and `/tracecore/<path:app_path>` to the same website page. Verify `/api/*` and `/assets/*` remain untouched.

- [ ] **Step 5: Pass tests**

Run the Task 5 command again.

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add -- tracecore/www/tracecore.py tracecore/www/tracecore.html tracecore/tests/test_home_page.py tracecore/hooks.py
git commit -m "feat(home): serve React app outside Frappe Desk"
```

---

### Task 6: Redirect login to the real Home safely

**Files:**
- Modify: `tracecore/core/account.py`
- Modify: `tracecore/core/tests/test_account.py`

**Interfaces:**
- Consumes: successful Frappe login and existing password-expiry check
- Produces: `login_manager.user` landing route `/tracecore` without changing API login responses or station-card sessions

- [ ] **Step 1: Write failing redirect tests**

Add tests proving:

```python
def test_web_login_sets_tracecore_home_after_password_check(): ...
def test_expired_password_still_blocks_before_redirect(): ...
def test_guest_and_api_login_do_not_receive_unsafe_redirect(): ...
```

- [ ] **Step 2: Run focused tests and confirm failure**

Run:

```powershell
wsl -d Ubuntu-22.04 -- bash -lc "cd ~/tracecore-dev && bench --site test_site run-tests --module tracecore.core.tests.test_account"
```

Expected: the new redirect assertion fails while existing password tests remain green.

- [ ] **Step 3: Implement the minimal landing assignment**

After the existing password-expiry guard succeeds, set the supported Frappe login redirect field to `/tracecore`. Do not bypass `redirect-to` validation and do not change station-card authentication.

- [ ] **Step 4: Pass account tests**

Run the Task 6 command again.

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add -- tracecore/core/account.py tracecore/core/tests/test_account.py
git commit -m "feat(home): redirect web login to TraceCore"
```

---

### Task 7: Verify the integrated Home locally

**Files:**
- Create: `tests_e2e/test_home.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: running Frappe dev site, built frontend assets, seeded role users
- Produces: reproducible local test and browser evidence for desktop and PDA

- [ ] **Step 1: Write failing Playwright scenarios**

Cover:

```python
def test_login_redirects_to_tracecore_home(page, role_user): ...
def test_r01_home_opens_authorized_shortcut(page, r01_user): ...
def test_non_manager_cannot_see_frappe_admin(page, operator_user): ...
def test_system_manager_can_open_frappe_admin(page, manager_user): ...
def test_home_is_responsive_on_pda(page, r08_user): ...
def test_direct_home_refresh_keeps_application_shell(page, role_user): ...
```

- [ ] **Step 2: Run once and confirm the new test fails before final wiring/build**

Run:

```powershell
wsl -d Ubuntu-22.04 -- bash -lc "cd ~/tracecore-dev/apps/tracecore && pytest tests_e2e/test_home.py -q"
```

Expected: at least the redirect/Home assertion fails until the site is migrated and assets are built.

- [ ] **Step 3: Document local commands**

Add exact commands to README:

```powershell
Set-Location frontend
npm ci
npm run build
wsl -d Ubuntu-22.04 -- bash -lc "cd ~/tracecore-dev && bench --site tracecore-dev.local migrate && bench start"
```

State that the browser URL is `http://tracecore-dev.local:8000/tracecore`.

- [ ] **Step 4: Build, migrate, and run all focused verification**

Run:

```powershell
Set-Location frontend
npm ci
npm test
npm run build
wsl -d Ubuntu-22.04 -- bash -lc "cd ~/tracecore-dev && bench --site test_site migrate && bench --site test_site run-tests --module tracecore.v1.tests.test_home_api --module tracecore.tests.test_home_page --module tracecore.core.tests.test_account"
wsl -d Ubuntu-22.04 -- bash -lc "cd ~/tracecore-dev/apps/tracecore && pytest tests_e2e/test_home.py -q"
pre-commit run --all-files
```

Expected: frontend tests, focused Frappe tests, Home E2E, and pre-commit all pass.

- [ ] **Step 5: Perform visual verification**

Open the real URL at 1366×768 and 412×915. Confirm the Frappe Desk toolbar/sidebar is absent, the TraceCore sidebar and hybrid content match the screenshot language, every status has text, keyboard focus is visible, and no placeholder/sample values appear.

- [ ] **Step 6: Commit**

```powershell
git add -- tests_e2e/test_home.py README.md frontend/package-lock.json tracecore/public/home
git commit -m "test(home): verify independent landing experience"
```

---

## Final acceptance checklist

- [ ] `/tracecore` is a real application page served by Frappe without Desk chrome.
- [ ] Successful web login lands on `/tracecore`.
- [ ] Home displays real server-derived identity, attention, metrics, and shortcuts.
- [ ] R01/R02, technician, department, and System Manager payloads differ by permission.
- [ ] Only System Manager/Administrator sees `Frappe Admin`.
- [ ] Unknown or server-injected URLs cannot be navigated.
- [ ] Loading, empty, error, expired-session, stale, and offline states are visible and tested.
- [ ] Desktop and PDA E2E pass.
- [ ] Frappe business rules, DocType state, and permissions remain authoritative.
- [ ] The page can later move to a separate domain by replacing adapters, not components.
