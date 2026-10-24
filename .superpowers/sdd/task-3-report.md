# Task 3 implementation report

Commit: `fa26b5aa6f102bce9561fec416ed087ec1b9b4cf`
Message: `feat(home): add independent React foundation`

## Scope

Implemented only the independent frontend foundation: pinned manifest/lockfile, TypeScript/Vite configuration, development HTML, minimal empty React mount, typed same-origin Home API adapter, and the closed route registry. No Home UI, operational screens, sample operational data, or Frappe runtime imports were added.

The types match the implemented Task 2 payload rather than the earlier illustrative design: no `ok` or `recent`, `user.stations` contains name/label/step/implemented, shortcuts include a null badge, and `attention` is currently always empty (`never[]`). Future actionable attention data needs a corresponding backend contract/type change.

In addition to the brief's required files, added `frontend/src/api.test.ts` to verify the new API adapter. The parent explicitly authorized the minimal `.pre-commit-config.yaml` extension: existing generated-bundle exclusions now include `tracecore/public/home/` alongside `public/dist/` for Prettier and ESLint. This prevents formatting compiled dependencies or linting third-party React internals. No other hook settings changed.

## TDD evidence

Before creating `routes.ts` or `api.ts`, ran:

```text
npm test -- --run src/routes.test.ts src/api.test.ts
Exit 1: 2 failed suites
Error: Failed to load url ./routes ... Does the file exist?
Error: Failed to load url ./api ... Does the file exist?
```

This was the intended missing-implementation RED result from the plan. Then implemented both adapters and reran the suite:

```text
Test Files  2 passed (2)
Tests       21 passed (21)
```

The 16 route cases cover all seven exact destinations, unknown/empty/URL-like values, and inherited object keys (`constructor`, `toString`, `__proto__`). Five API cases cover Frappe's `message`, explicit GET and same-origin credentials, HTTP 401 and 403 error classes without requiring JSON error bodies, generic server failure without body disclosure, and missing message rejection. The success fixture also type-checks against `HomeContext`.

## Exact direct dependency versions

| Package | Version |
| --- | --- |
| react | 18.3.1 |
| react-dom | 18.3.1 |
| react-router-dom | 6.30.1 |
| @testing-library/jest-dom | 6.6.3 |
| @testing-library/react | 16.1.0 |
| @testing-library/user-event | 14.5.2 |
| @types/react | 18.3.18 |
| @types/react-dom | 18.3.5 |
| jsdom | 25.0.1 |
| typescript | 5.7.3 |
| vite | 5.4.21 |
| vitest | 2.1.9 |

Installed with `npm install --ignore-scripts --fetch-retries=0`, generated the committed npm lockfile, and verified a clean `npm ci --ignore-scripts --fetch-retries=0` (145 packages added). Installation required approved network access outside the sandbox. Native execution used Node 24.14.1/npm 11.11.0; the package supports Node >=18 but was not executed on Node 18 during this task.

## Verification and generated assets

- Final `npm test`: exit 0, 21/21 passing across two files.
- Final `npm run build`: exit 0 (`tsc -b && vite build`), Vite 5.4.21, 27 modules transformed.
- `npm ls --depth=0`: exit 0 and every direct dependency matches its exact manifest pin.
- Scoped pre-commit through the existing WSL environment: exit 0. Whitespace/conflicts/JSON/YAML and architecture checks passed; irrelevant hooks skipped. The existing JS hooks do not apply to TS source; strict TypeScript compilation passed.
- `git diff --cached --check`: exit 0 before commit.
- Self-review checked the staged source, lockfile presence, complete registry allowlist, inherited-key rejection, API payload compatibility, error mapping, empty mount boundary, and build configuration against the brief.
- Final Git status after commit: only pre-existing/uncommitted `.superpowers/` artifacts remain; no Task 3 tracked modifications or staged files remain.

Committed generated asset: `tracecore/public/home/home.js`, 141,747 bytes (45.42 kB gzip reported by Vite). SHA-256:

```text
1940C1EDFF2737321E5F673D250C5722C5F87DFA090D42AE90353BE7BAD3B8E4
```

The final foundation imports no CSS, so it intentionally emits no `home.css`, as allowed by the brief. A temporary token-only CSS probe import was built and verified to emit exactly `home.css` (38 bytes), then the probe was removed and the final build regenerated. The final JS SHA-256 matched the preceding build. `cssCodeSplit: false` plus the CSS asset naming rule guarantees the stable CSS filename once Task 4 imports styles. Rollup builds from `src/main.tsx` so the production public directory does not receive a development HTML shell; `frontend/index.html` remains available for Vite development.

## Concerns / follow-up boundaries

`npm audit --json --fetch-retries=0` exited 1 with 9 reported vulnerable packages: 3 moderate, 4 high, 2 critical. These affect the mandated React Router 6.30.1/Vite 5.4/Vitest 2.1 pins and transitive packages. Reported issues include React Router external redirects/XSS, Vite development-server file disclosure, and Vitest/tinypool execution issues. Required pins were preserved; no forced updates or version overrides were applied. React Router is not imported into the current empty mount, while Vite/Vitest are development dependencies. The parent was informed so dependency upgrades can be considered separately from this exact-version task.

No Frappe bench/E2E tests or browser UI checks were run because this task has no website route or real Home UI; those belong to later tasks. Coverage instrumentation is not configured in this new foundation. All `.superpowers/` artifacts, including this report, remain uncommitted.
