# Task 2 — Home context API

Commit: `3f333fe405e5dbc715e4df846b5584c319fae13b`

Exact commit message: `feat(home): add role-personalized context API`

## Scope and implementation

Only these scoped files were committed:

- `tracecore/v1/home.py`
- `tracecore/v1/tests/test_home_api.py`

The whitelisted GET endpoint rejects Guest, returns the exact eight top-level keys, and emits only the seven closed route identifiers. Shortcut objects have the exact five required keys. Administrator/System Manager alone receives `frappe-admin`.

Station choices reuse `navigation.context()` and therefore its active-station query, role-to-step map and implemented-step flags. The Home checks Zone Station read access first. The identity contains `name`, `full_name`, sorted `roles` and permitted `stations`; unimplemented shift/department context is not invented.

Each DocType shortcut/metric checks `frappe.has_permission(..., ptype="read")`. The four possible metrics are real aggregate counts for Set Unit, Pack, Equipment and Par Level. Aggregation uses permission-aware `frappe.get_list` with `count(name) as value`, preserving User Permissions and query conditions rather than bypassing them with `db.count`/`get_all`. No record fields or patient identifiers are read into the payload. Absent aggregate results are omitted; a real database zero remains valid.

`system` contains API version 1 and the existing server-time helper's timestamp. ETag is the first 16 hex characters of SHA-256 over UTF-8 canonical JSON (sorted keys, compact separators, non-ASCII preserved), excluding `etag` and `system.server_time`.

## TDD evidence

Tests were created before `home.py`.

The required command was run first:

```powershell
wsl -d Ubuntu-22.04 -- bash -lc "cd ~/tracecore-dev && bench --site test_site run-tests --module tracecore.v1.tests.test_home_api"
```

Result: exit 1, `ModuleNotFoundError: No module named 'tracecore.v1.tests.test_home_api'`.

The WSL bench checkout was confirmed at `51812bd`, behind this Windows checkout. To observe the intended missing-feature failure without modifying that checkout, an uncommitted runner at `.superpowers/sdd/run-task-2-tests.py` initializes/connects real Frappe `test_site`, prepends the Windows checkout's v1/test package paths and invokes unittest on the actual `FrappeTestCase` module.

```powershell
wsl -d Ubuntu-22.04 -- bash -lc "cd ~/tracecore-dev/sites && ../env/bin/python /mnt/d/tracecore/.superpowers/sdd/run-task-2-tests.py"
```

Before implementation: exit 1; loading the current test file failed with `ImportError: cannot import name 'home' from 'tracecore.v1'`, as expected because the endpoint did not exist.

After implementation: exit 0; all 8 Home tests passed (`Ran 8 tests ... OK`). These include all seven required tests and an additional guard against permission-bypassing aggregate counts.

## Final verification

```powershell
wsl -d Ubuntu-22.04 -- bash -lc "cd ~/tracecore-dev/sites && ../env/bin/python -m coverage run --data-file=/mnt/d/tracecore/.superpowers/sdd/task-2.coverage --include='*/tracecore/v1/home.py' /mnt/d/tracecore/.superpowers/sdd/run-task-2-tests.py tracecore.v1.tests.test_home_api tracecore.ui.page.tracecore.test_tracecore && ../env/bin/python -m coverage report --data-file=/mnt/d/tracecore/.superpowers/sdd/task-2.coverage -m"
```

Result: exit 0; 13 tests passed (8 Home + 5 existing launcher/navigation tests). `home.py`: 51 statements, 0 missed, 100% line coverage. Role and revoked-permission behavior uses the same focused mocking conventions as existing navigation tests; real identity, station selection and database aggregates are exercised by Administrator contract tests.

```powershell
wsl -d Ubuntu-22.04 -- bash -lc "cd /mnt/d/tracecore && pre-commit run --files tracecore/v1/home.py tracecore/v1/tests/test_home_api.py"
```

Result: exit 0; whitespace/conflict/AST/debug checks, ruff import sorting/lint/format, bandit, architecture and BRU checks passed. Nonapplicable hooks skipped.

`git diff --cached --check` passed before commit. Self-review checked exact payload/shortcut shapes, identifier closure, admin gating, guest guard, reused station rules, read-permission checks, real aggregates, no patient fields, ETag timestamp exclusion and scoped staging.

The exact required `bench ... run-tests` command was also rerun after implementation. It still exits 1 with the same missing-module error because that command imports the old WSL checkout. This is not a passing standard bench run; supplemental tests above run current-clone code against the real Frappe test site. The stale checkout was deliberately not changed.

## Concerns / integration notes

- `attention` intentionally returns `[]`: Task 2 has no implemented, specified permission-checked actionable aggregate source. No warning, approval queue or sample value is fabricated. Add concrete attention providers when their source and action authorization contracts are defined.
- Counts represent all readable records, not newly invented workflow KPIs; no new business rules are introduced.
- Display strings pass through `_()`; identifiers remain stable English. Translation CSV additions are outside the two-file scope.
- The standard bench command must be rerun once its checkout contains this commit. The external test loader is a local verification aid, not a committed test infrastructure change.
- `.superpowers` runner/report/coverage artifacts remain uncommitted.

## Integration follow-up — Vietnamese Home translations

Commit: `9c92e19b41b11eab8bc748d84bdaa221864e6655`

Exact message: `fix(home): add Vietnamese dashboard translations`

Changed file: `tracecore/translations/vi.csv` only; added exactly the 12 missing Home source-string translations. Existing translations were not changed. The source/target sentence containing commas is correctly CSV-quoted. Terminology follows existing rows (`Bộ dụng cụ`, `Cơ số`, `trạm`, `gói`, `thiết bị`); Frappe remains the product name.

Before editing, reproduced the failure with the normal synced bench at `9d36830`:

```powershell
wsl -d Ubuntu-22.04 -- bash -lc "cd ~/tracecore-dev && bench --site test_site run-tests --module tracecore.tests.test_station_page --test test_vi_translations_cover_source_strings"
```

Observed `Ran 1 test ... FAILED (failures=1)` and exactly the 12 Home strings reported by integration. Bench returned process exit code 0 despite the test failure, so result is taken from the test summary rather than the process code.

After adding the rows, verified current Windows sources/CSV through the normal bench runner with `PYTHONPATH=/mnt/d/tracecore` (bench checkout itself was not modified):

```powershell
wsl -d Ubuntu-22.04 -- bash -lc "cd ~/tracecore-dev && PYTHONPATH=/mnt/d/tracecore bench --site test_site run-tests --module tracecore.tests.test_station_page --test test_vi_translations_cover_source_strings --test test_vi_csv_parses_without_frappe_warnings --test test_vi_translations_do_not_override_other_apps"
wsl -d Ubuntu-22.04 -- bash -lc "cd ~/tracecore-dev && PYTHONPATH=/mnt/d/tracecore bench --site test_site run-tests --module tracecore.v1.tests.test_home_api"
wsl -d Ubuntu-22.04 -- bash -lc "cd /mnt/d/tracecore && pre-commit run --files tracecore/translations/vi.csv"
```

Results: 3 translation tests `OK`; 8 Home API tests `OK`; scoped pre-commit passed (merge-conflict check passed; hooks inapplicable to CSV skipped). `git diff --check` passed. Self-review confirmed only the required 12 rows were added, no duplicate source rows, valid quoting/column counts, complete Home source coverage, and no overriding translations from Frappe/ERPNext/HRMS. Parent integration can fast-forward the bench to this fix commit for a subsequent normal run without the path override.
