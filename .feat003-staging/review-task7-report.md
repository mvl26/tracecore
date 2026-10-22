# FEAT-003 Task 7 handoff

Status: **DONE_WITH_CONCERNS** (physical hardware and later-feature boundaries below; all Task 7 gates pass). Review branch: `feat/FEAT-003-rbac-station-auth` in `/home/tien2003/tracecore-codex/apps/tracecore`. Baseline: `04a222eaed7ce29cc2c47a369b29289fef60de6f`. Commit: **`7e49a91922f997be85774678456f207b914cda34`**.

The scoped source and test changes are committed on this branch only. No push, merge, cherry-pick, deployment, or edit to `~/tracecore-dev` was performed. No production password, PIN, bearer, or OTP seed is recorded here.

## Acceptance evidence

The tracked [FEAT-003 acceptance evidence](../../docs/superpowers/reviews/FEAT-003-acceptance-evidence.md) maps A1–A8 and each in-scope FR/BRU/NFR to server, browser, and security assertions. `docs/rtm.md` links each FEAT-003 subset to that map. The seed is restricted to developer/test sites, reuses the active Employee/card/competency, and records private generated OTP material only in the mode-0600 local E2E env file. Live browser cases exercise card login, identity and roles, dedicated T4 indicator input, logout, second-station replacement, and idle clearing.

## Verification commands and results

All commands ran in the isolated Ubuntu-22.04 bench unless stated otherwise. The bench executable is `/home/tien2003/.local/bin/bench`; `uv` and `diff-cover` are in the same local bin directory. The test site is `test_codex`; the live browser site is `tracecore-codex.local` on port 8100.

```sh
cd /home/tien2003/tracecore-codex
bench --site test_codex migrate
bench --site tracecore-codex.local migrate
bench build --app tracecore
```

Both migrations and the asset build exited 0 again after the final test corrections. The build only printed the existing caniuse-lite age advisory.

```sh
cd /home/tien2003/tracecore-codex/apps/tracecore
BENCH_DIR=/home/tien2003/tracecore-codex TC_E2E_ENV=/home/tien2003/tracecore-codex/.task7-e2e.env bash scripts/e2e_prepare.sh tracecore-codex.local
set -a; source /home/tien2003/tracecore-codex/.task7-e2e.env; set +a
TC_BASE_URL=http://127.0.0.1:8100 uv run --offline --no-project --with pytest-playwright --python /home/tien2003/tracecore-codex/env/bin/python pytest tests_e2e -q
```

After fresh E2E preparation, the final live Chromium suite passed **51/51 in 192.44s**. An earlier focused live station/smoke/T4 run passed **13/13 in 98.79s**. The only routed boundary in the packing browser tests is the physical printer agent; no physical card reader or printer was available.

```sh
cd /home/tien2003/tracecore-codex/apps/tracecore
/home/tien2003/.nvm/versions/node/v18.20.8/bin/node --test scripts/tests/station_auth.test.js
/home/tien2003/.local/bin/pre-commit run --all-files
python3 scripts/check_architecture.py
python3 scripts/check_bru_coverage.py
git diff --check
```

Final Node result: **15 passed, 0 failed**. All pre-commit hooks passed (whitespace, syntax, Ruff, Prettier, ESLint, Bandit, architecture R1–R4, BRU markers, and token assets). Architecture exited 0. BRU check exited 0 with **17/49** catalog markers currently covered; markers outside this feature remain future scope. `git diff --check` exited 0.

The isolated bench Python lacks the optional `coverage` package. The complete run therefore used the package already in the local uv cache, without changing bench dependencies or downloading from the network:

```sh
cd /home/tien2003/tracecore-codex/sites
/home/tien2003/.local/bin/uv run --offline --no-project --with coverage --python /home/tien2003/tracecore-codex/env/bin/python python -m frappe.utils.bench_helper frappe --site test_codex run-tests --app tracecore --coverage --skip-test-records
cd /home/tien2003/tracecore-codex/apps/tracecore
/home/tien2003/.local/bin/diff-cover /home/tien2003/tracecore-codex/sites/coverage.xml --compare-branch=04a222eaed7ce29cc2c47a369b29289fef60de6f --fail-under=70
```

Final full-suite result: **716/716 passed in 742.723s; `OK`; coverage saved**. `diff-cover` reported **94/96 changed executable Python lines covered, 97%**, and exited 0 against the 70% gate. The two uncovered lines are 59 and 102 of `tracecore/setup/devdata.py`. `--skip-test-records` skips Frappe auto-generated prerequisite records, not tests; the integration site already has the ERPNext/HRMS records. No TraceCore module is excluded.

## Regression diagnosis and resolution

The first full coverage run printed **716 tests in 784.154s; 3 failures and 1 error**, even though Frappe's process returned exit code 0. Its printed unittest summary, rather than process status alone, is the pass criterion. The four findings were test assumptions exposed by FEAT-003, not production-auth relaxations:

- Audit Log and Step Gate Result still expected native `System Manager` read access after the generated Custom DocPerm matrix replaced those native rows. Both now compare effective permissions with `build_custom_docperms` for all ten TC roles and assert no delete; immutable audit and step-gate deletion tests remain.
- Label Template preview attempted to create an R10 actor while the session was already R04. The test now provisions both actors under temporary explicit Administrator R10 fixture authority, then switches actor for the permission check. Authority is restored on exit.
- Equipment retire compared a global Audit Log count after `as_user` created `eq-admin-tcr04@example.com`. Focused diagnostics identified the exact extra `Create User` audit event. The assertion now compares audit events for the target Equipment record, proving the denied operation wrote none.

The focused Pack permission module passed **21/21**, including R01–R10 against the generated Pack matrix and a no-delete invariant. After the four corrections, focused modules passed: Audit Log **9/9**, Step Gate Result **5/5**, Label Template API **6/6**, Equipment Admin API **19/19**. An earlier focused affected set passed **61/61**. The full post-fix coverage rerun is the final gate.

## Limits and handoff

The real browser verifies the software card-scan event and server session behavior, but physical reader and printer hardware were unavailable. The live idle case advances the client controller's last-human-activity timestamp; server idle and eight-hour absolute boundaries are exercised by integration tests. NFR-SEC-08 quarterly rights review and anomalous-login alerting remain later work, as do future R08 departmental filters. FR-M4-01 and FR-M4-03 certify only the Employee/card and station-competency subsets, with the broader HR workflows assigned to later features. The audit evidence covers this authentication scope, not every module's future audit trail.

The verified branch is ready for review. No merge or deployment was performed. The only remaining concerns are the stated physical-hardware and later-feature limitations.
