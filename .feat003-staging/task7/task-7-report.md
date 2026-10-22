# FEAT-003 Task 7 report

Status: verification in progress; final SHA and results will be recorded before handoff.

Branch: `feat/FEAT-003-rbac-station-auth`.
Task baseline: `04a222eaed7ce29cc2c47a369b29289fef60de6f`.
Workspace: `/home/tien2003/tracecore-codex/apps/tracecore` only. Windows `.feat003-staging/task7` held apply_patch edits copied mechanically into this isolated checkout.

## Changes

- Guarded, idempotent Employee/card/competency setup for smoke TR-003, packing TR-004 and second station TR-005. Existing cards and valid competencies are reused; stale demo competency is renewed in place. No demo PIN is seeded.
- Generated native OTP App enrollment for demo users. Seeds remain encrypted in Frappe defaults and are exported only with generated/reused passwords into the bench-local mode-0600 E2E env file. Their values do not appear in this report, the tracked evidence artifact or source.
- Dev/test-only CLI bootstrap temporarily assigns an explicit Administrator R10 role and restores its prior assignment in `finally`. Success, exception, existing-R10 and production refusal cases are tested. Production `require_r10` is unchanged.
- Browser fixtures complete the real native password/OTP challenge and assert the logged-in Desk user before opening the station. A single fresh-code retry is permitted only if the native 30-second TOTP window changed during the request; other authentication failures remain failures.
- New live browser cases verify identity/roles, dedicated T4 indicator-lot input and logout, old-token rejection after a second-station card login, and idle revocation. Direct live heartbeat checks include Frappe CSRF protection.
- Repaired legacy test-only integration assumptions: temporary explicit R10 fixture authority with restoration; effective generated-matrix permission assertions; stable auth HTTP codes; protected PIN-reset field assertions; and Werkzeug Local state preservation in native account tests.
- Added `docs/superpowers/reviews/FEAT-003-acceptance-evidence.md` and scoped FR/NFR RTM evidence links. Partial/future requirements are labeled explicitly.

## TDD and failure investigation

1. New station demo integration initially failed with missing `ensure_station_demo`; minimal seed implementation made all 15 then-existing devdata tests pass.
2. Preparation contract initially lacked `TC_E2E_CARD_ID`, then lacked private OTP exports. Both were observed failing before script wiring; final guard/contract suite passes.
3. Live preparation first failed because Administrator lacks an explicit R10 assignment. A guarded temporary-role bootstrap was added rather than changing production authorization.
4. Native live login first failed trying to send OTP enrollment email (no outgoing account). Generated dev-only native OTP enrollment and real challenge completion resolved it while retaining enabled 2FA. The pre-fix browser fixture also reproduced a 30-second timeout awaiting station login because the HTTP-200 challenge had not authenticated Desk.
5. Initial full coverage run: 712 tests in 525.724s; 4 failures and 121 errors. Root causes were obsolete pre-FEAT-003 permission/status/schema tests, legacy unprivileged fixture creation and Frappe Local state loss. Two additional failures were during development (new translations missing; script/fake contract loaded across a source change), corrected before final runs.
6. Added response-identity assertion to the native OTP recovery test: RED was `AttributeError: response` after its mock context. The root is `patch.object(..., create=True)` on Werkzeug Local deleting existing fields on exit. A preserving `local_context` made the same native-login regression GREEN; no downstream production response default was added.
7. The comprehensive rerun identified the remaining Pack test's obsolete assumption that R02/R05 can only read. It is replaced by checks for every role/permission against the accepted generator/matrix, preserving no-delete. No production role is relaxed.

## Verification already completed

| Check | Result |
| --- | --- |
| Migrate `test_codex` | Success |
| Migrate `tracecore-codex.local` | Success |
| Final assets/translations build | Success; existing caniuse-lite age advisory only |
| Affected integration regressions | 61 passed across account, idempotency, errors, auth models, effective matrices, norms, devdata and station page |
| Final seed/bootstrap suite | 19 passed in 24.149s, including role restoration after failure and encrypted OTP enrollment |
| Live station + smoke + T4 Chromium | 13 passed in 98.79s; real Frappe/MariaDB/Redis |
| Entire Chromium E2E suite | 51 passed in 232.36s, including Desk admin/equipment and 29 routed auth lifecycle tests |
| Node auth regression suite | 15/15 passed |
| All-files pre-commit | All hooks passed, including staged new files |
| Architecture | Exit 0 |
| BRU checker | Exit 0; 17/49 existing application BRUs covered, including BRU-HR-001; no claim future BRUs are implemented |
| Whitespace checks | Staged and unstaged diffs clean |

Final complete-suite, changed-code coverage and commit results: pending the last verification gate.

## Commands and artifact locations

All commands below run from the isolated bench/app. `--skip-test-records` skips automatic Frappe fixture generation only; it excludes no TraceCore test module or test method. The migrated site already has ERPNext/HRMS dependency records.

```sh
cd /home/tien2003/tracecore-codex
bench --site test_codex migrate
bench --site tracecore-codex.local migrate
bench build --app tracecore
env PYTHONPATH=/home/tien2003/.cache/uv/archive-v0/NKwABb-qbyvo3e43 \
  bench --site test_codex run-tests --app tracecore --coverage --skip-test-records
```

The PYTHONPATH package is the already-cached optional coverage runtime; no dependency was downloaded or installed from the network.

```sh
cd /home/tien2003/tracecore-codex/apps/tracecore
BENCH_DIR=/home/tien2003/tracecore-codex \
TC_E2E_ENV=/home/tien2003/tracecore-codex/.task7-e2e.env \
  bash scripts/e2e_prepare.sh tracecore-codex.local
set -a
source /home/tien2003/tracecore-codex/.task7-e2e.env
set +a
TC_BASE_URL=http://127.0.0.1:8100 \
  uv run --offline --no-project --with pytest-playwright \
  --python /home/tien2003/tracecore-codex/env/bin/python \
  pytest tests_e2e -q --screenshot=on --output=.superpowers/sdd/task7-all-browser-artifacts
node --test scripts/tests/station_auth.test.js
pre-commit run --all-files
python3 scripts/check_architecture.py
python3 scripts/check_bru_coverage.py
diff-cover ../../sites/coverage.xml --compare-branch=04a222eaed7ce29cc2c47a369b29289fef60de6f --fail-under=70
```

Live screenshots are under `.superpowers/sdd/task7-live-browser-artifacts`; complete-suite screenshots under `.superpowers/sdd/task7-all-browser-artifacts`. The live T4 generated-cycle/label screenshot was visually inspected. Label output is explicitly test data; printer-agent transport is intercepted by existing packing E2E, not a physical print validation.

## Limits and isolation

- No physical reader or label printer was available. Keyboard/reader-event software flows and native browser/server authentication are verified; hardware acceptance is not claimed.
- Live idle testing advances last human activity in the controller, then verifies actual server logout/rejection. Exact server absolute/idle expiry boundaries are integration-tested; no eight-hour wall-clock soak was performed.
- FR-M4-01/03 are intentionally partial HRMS/competency foundations. Future certificates/personnel UI, R08 departmental behavior on future documents, quarterly permission reviews and anomaly alerting remain outside this implemented slice.
- No Task 7 command wrote to `~/tracecore-dev` or tracked `D:/tracecore` source. The normal development bench already contained unrelated active work and its status changed independently during this task, so this report does not claim that unrelated worktree was globally static or clean.
- No push, merge, cherry-pick, PR creation or deployment was performed. Keep the verified branch and request review before any integration action.
