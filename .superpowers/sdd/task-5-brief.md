# Task 5 brief — Serve the SPA outside the Desk shell

Project context: TraceCore is a Frappe v15 application with built React Home assets. Serve them as an authenticated website application at `/tracecore` and deep links, without Frappe Desk chrome.

Read first:

- `CLAUDE.md`
- `docs/superpowers/plans/2026-10-24-tracecore-independent-home.md` (Global Constraints and Task 5)
- `docs/superpowers/specs/2026-10-24-tracecore-independent-home-design.md`
- `.superpowers/sdd/progress.md`
- `frontend/src/App.tsx` (especially the CSRF meta contract)
- current `tracecore/hooks.py` and existing website route/page tests/templates

Scope: implement only Task 5.

Required files:

- create `tracecore/www/tracecore.py`
- create `tracecore/www/tracecore.html`
- create `tracecore/tests/test_home_page.py`
- modify `tracecore/hooks.py`

Required behavior/tests:

- `/tracecore` serves the Home root without `desk.bundle.js` or Desk shell markers.
- `/tracecore/<path>` resolves to the same SPA shell for client-side deep routes.
- Guest redirects to `/login?redirect-to=/tracecore` using safe Frappe redirect behavior.
- Shell contains exactly the React mount `<div id="tracecore-root"></div>` and references built `/assets/tracecore/home/home.js` plus `home.css`.
- Route rules must not capture `/api/*` or `/assets/*`.
- `tracecore.py` sets `no_cache = 1` and returns only language and CSRF token boot values.
- Render `<meta name="csrf-token" content="...">` with the non-empty authenticated token required by Task 4 logout; do not expose unrelated `frappe.boot` data.
- Avoid Frappe website navbar/footer/Desk navigation in the rendered page. If extending `templates/web.html` leaks website chrome, use the narrowest supported Frappe template approach that produces a valid standalone HTML document.
- Do not import Frappe Desk JS/CSS/components into the React app.
- Keep `/api/*` and `/assets/*` untouched and do not weaken authentication/permission boundaries.
- Use TDD: write route/shell tests and observe failure before implementation.
- Run `bench --site test_site run-tests --module tracecore.tests.test_home_page` after syncing current branch into the WSL bench checkout, or clearly report environment constraints. Also run relevant existing launcher/navigation tests if hooks/routing overlap.
- Run relevant pre-commit checks.
- Self-review and commit only Task 5 files with exactly `feat(home): serve React app outside Frappe Desk`.
- Write `.superpowers/sdd/task-5-report.md` with TDD evidence, exact route rules, rendered-shell assertions, verification results, commit hash and concerns. Do not commit `.superpowers`.
