# Task 3 brief — Add the independent Vite application foundation

Project context: TraceCore is a Frappe v15 application. We are building a real React/TypeScript Home served outside the Frappe Desk shell, but using the same-origin Frappe session and server-authorized route keys.

Read first:

- `CLAUDE.md`
- `docs/superpowers/plans/2026-10-24-tracecore-independent-home.md` (Global Constraints and Task 3)
- `docs/superpowers/specs/2026-10-24-tracecore-independent-home-design.md`
- `.superpowers/sdd/progress.md`
- `docs/tokens.json`
- current `.gitignore`

Scope: implement only Task 3 from the plan.

Required files:

- create `frontend/package.json`, `frontend/package-lock.json`, `frontend/tsconfig.json`, `frontend/vite.config.ts`, `frontend/index.html`
- create `frontend/src/main.tsx`, `frontend/src/api.ts`, `frontend/src/routes.ts`, `frontend/src/routes.test.ts`
- modify `.gitignore`
- generate and commit `tracecore/public/home/home.js` and `tracecore/public/home/home.css` if the configured build emits CSS at this stage; the build must at least produce stable `home.js`, with CSS guaranteed once imported by the application task.

Requirements:

- Use TDD: write route tests and capture the intended failing result before implementing `routes.ts`.
- Scripts: `dev: vite`, `build: tsc -b && vite build`, `test: vitest run`, `test:watch: vitest`.
- Pin React/React DOM 18.3.1, React Router DOM 6.30.1, Vite 5.4.x, TypeScript 5.7.x, Vitest 2.1.x, jsdom and Testing Library; commit the generated lockfile.
- `resolveRoute("search") === "/tracecore/search"`; `resolveRoute("frappe-admin") === "/app"`; unknown or URL-like values throw `Unknown TraceCore route`.
- Closed mappings exactly: search, station, set-units, packs, equipment, par-levels, frappe-admin using the destinations in the plan.
- `api.ts` calls `GET /api/method/tracecore.v1.home.context` with `credentials: "same-origin"`, parses Frappe's `message`, maps 401 to `SessionExpiredError` and 403 to a custom permission error, and never depends on `window.frappe`.
- Define accurate TypeScript types matching the Task 2 payload.
- Vite base `/assets/tracecore/home/`, outDir `../tracecore/public/home`, `emptyOutDir: true`, stable entry names `home.js` and `home.css`.
- `main.tsx` should be the minimal mount foundation only; Task 4 owns the real Home UI.
- Run `npm test` and `npm run build`; run relevant pre-commit checks.
- Do not rebuild the operational screenshots or add sample data.
- Self-review and commit only Task 3 files with exactly `feat(home): add independent React foundation`.
- Write `.superpowers/sdd/task-3-report.md` with red/green TDD evidence, exact dependency versions, verification results, generated assets, commit hash and concerns. Do not commit `.superpowers`.
