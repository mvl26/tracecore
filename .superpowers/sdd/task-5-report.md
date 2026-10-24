# Task 5 — Frappe website shell

Commit: `9d36830` — `feat(home): serve React app outside Frappe Desk`

Only the four requested files are committed:

- `tracecore/www/tracecore.py`
- `tracecore/www/tracecore.html`
- `tracecore/tests/test_home_page.py`
- `tracecore/hooks.py`

## Implementation and self-review

The page uses Frappe's supported standalone `www` HTML template rendering. Installed v15 `templates/web.html` inherits `templates/base.html`, which injects website wrappers, navbar/footer, `frappe-web.bundle.js`, and `frappe.boot`; the standalone document avoids all of these. Its literal React mount is `<div id="tracecore-root"></div>`. The only script is the module `/assets/tracecore/home/home.js`; the only stylesheet is `/assets/tracecore/home/home.css`, which already bundles generated `--tc-*` design tokens through Vite.

Controller sets module-level `no_cache = 1`. Guest is rejected before token generation with `frappe.flags.redirect_location = "/login?redirect-to=/tracecore"` and `frappe.Redirect(http_status_code=302)`. The static local redirect cannot be influenced by deep-route content. Authenticated context adds only `lang` and `csrf_token`, obtained using `frappe.sessions.get_csrf_token`. Both values are explicitly HTML-escaped. Token is rendered in `<meta name="csrf-token" content="...">`, matching Task 4 logout's selector. No Desk session boot, role logic, permission bypass, business mutation, or frontend change is introduced.

Exact route rules:

```python
website_route_rules = [
    {"from_route": "/tracecore", "to_route": "tracecore"},
    {"from_route": "/tracecore/<path:app_path>", "to_route": "tracecore"},
]
```

The fixed prefix confines the fallback to TraceCore. Actual Frappe resolver tests verify API/assets pass through, a similarly prefixed `tracecore-other` route is untouched, and existing `/app/station` continues resolving to Frappe's `app` endpoint.

## TDD evidence

Tests were written before controller/template/hooks implementation. To preserve the existing clean WSL source checkout at `3f333fe`, tests used its real Frappe/MariaDB/Redis environment with current Windows app sources selected by `PYTHONPATH`; no WSL source files were copied or edited.

```text
wsl -d Ubuntu-22.04 -- bash -lc "cd ~/tracecore-dev && PYTHONPATH=/mnt/d/tracecore bench --site test_site run-tests --module tracecore.tests.test_home_page"

RED: Ran 8 tests; FAILED (failures=9, errors=2).
Root and Guest routes returned 404; deep routes did not resolve;
route rules and CSRF meta were absent; new controller module did not exist.
```

After implementation, the first run found one incorrect test assumption: Frappe already maps `app/station` to `app`. Corrected that existing-route expectation without changing implementation.

Final route run:

```text
PYTHONPATH=/mnt/d/tracecore bench --site test_site run-tests --app tracecore --module tracecore.tests.test_home_page --coverage
Ran 8 tests in 9.710s
OK
Saved Coverage
```

Rendered-shell assertions cover status/mimetype, doctype and one HTML/head/body, exact mount (one only), no nav/footer/website wrappers/Desk markers, exact module/stylesheet references, existing asset files and bundled tokens, identical HTML for Home/search/nested station routes, Guest 302 for root and deep route, only two boot values, real nonempty session CSRF token, and hostile attribute escaping.

## Other verification

- Launcher/navigation: `PYTHONPATH=/mnt/d/tracecore bench --site test_site run-tests --module tracecore.ui.page.tracecore.test_tracecore`: 5/5 pass.
- Home API/permissions: same command with `tracecore.v1.tests.test_home_api`: 8/8 pass.
- Existing website/station: same command with `tracecore.tests.test_station_page`: 18/19 pass. Sole failure is existing `test_vi_translations_cover_source_strings`, listing 12 untranslated strings from Task 2 `tracecore/v1/home.py`.
- Baseline proof: normal bench command WITHOUT PYTHONPATH, on untouched WSL `3f333fe`, with `--module tracecore.tests.test_station_page --test test_vi_translations_cover_source_strings` reproduces the identical 12-string failure. It is outside Task 5 scope.
- Scoped pre-commit on all four Task 5 files passes: whitespace/conflicts/AST/debug checks, Ruff sorting/lint/formatting, Bandit, architecture rules, BRU markers. Inapplicable hooks skipped.
- `git diff --cached --check`: pass before commit.
- Self-reviewed staged diff; commit contains exactly four requested files. `.superpowers` stays uncommitted. WSL `git status --short` remains empty.

## Remaining verification / concerns

Bench's coverage filter uses the installed WSL app source directory even when PYTHONPATH imports Windows sources. Consequently the coverage output above excludes new Windows source files and is not valid changed-code coverage evidence. Root will fast-forward the clean WSL checkout from the committed Windows branch, then rerun the exact normal bench route command (without PYTHONPATH) and app-scoped coverage. No environment obstacle prevents those runs after sync.

The 12 pre-existing missing Vietnamese translation rows should be handled as a separate scope item. No broader translation or Task 6 login change is included here.
