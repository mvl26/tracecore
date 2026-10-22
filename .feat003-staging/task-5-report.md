# FEAT-003 Task 5 report

Status: DONE

Commit: `340f490e8022d1da531c04dc96e3ab2fbc70de91`

Branch: `feat/FEAT-003-rbac-station-auth`

Base: `26cc740`

Repository: `/home/tien2003/tracecore-codex/apps/tracecore`

Only the isolated Codex bench and its `test_codex` site were used. No files under `/home/tien2003/tracecore-dev` or tracked source under `D:/tracecore` were modified. Windows `.feat003-staging` was used for sandbox-safe `apply_patch` edits followed by mechanical copies. The pre-existing untracked `.superpowers/` brief was preserved; this report is an untracked handoff artifact, not part of the implementation commit.

## Files

- `tracecore/core/account.py`: password policy and expiry, native recovery override, old-secret changes, authorized resets, single-use station PIN proofs, lifecycle guards, offboarding and secret-free audit events.
- `tracecore/core/tests/test_account.py`: 19 focused integration/regression tests.
- `tracecore/fixtures/custom_field.json`: Employee `tc_pin_reset_required` check field. Existing PIN storage remains the encrypted Password field containing bcrypt.
- `tracecore/hooks.py`: User/Employee lifecycle and no-delete hooks, login expiry enforcement, native password method override, policy application after migration.
- `tracecore/setup/install.py`: password/lockout settings and native role-based OTP App 2FA configuration.
- `tracecore/setup/provision.py`: R10-only provisioning, minimum password validation, password-date initialization.
- `tracecore/translations/vi.csv`: Vietnamese account/PIN/password error strings and reset field label.
- `tracecore/v1/station.py`: privileged PIN verification refuses a reset PIN until changed.

## Test-first evidence

Before implementation:

```sh
cd /home/tien2003/tracecore-codex
bench --site test_codex run-tests --module tracecore.core.tests.test_account --skip-test-records
```

Result: `Ran 15 tests in 0.010s`, `FAILED (failures=15)`. Each test's setup explicitly asserted that the missing account lifecycle module existed, producing `AssertionError: unexpectedly None : Task 5 account lifecycle is missing` rather than import errors.

First implementation run: 12/15 passed, 3 errors. Evidence identified two concrete causes: Redis returns bytes that must be decoded before Frappe JSON parsing; ERPNext requires a relieving date for status Left. Both were fixed without changing the account requirements. The original suite subsequently passed `15 tests in 48.778s`.

Additional self-review regression tests were written and run before their fixes:

```sh
bench --site test_codex run-tests --module tracecore.core.tests.test_account --test test_document_save_cannot_bypass_credential_reset_state --test test_pin_change_audit_uses_authenticated_station_employee --test test_native_password_recovery_clears_forced_expiry --skip-test-records
```

Result: `Ran 3 tests in 12.993s`, `FAILED (failures=2)`. Native recovery already passed. The two failing assertions demonstrated that an Employee document could clear PIN reset state and that PIN change audit attributed the action to the surrounding web/kiosk user instead of the authenticated station employee.

```sh
bench --site test_codex run-tests --module tracecore.core.tests.test_account --test test_document_save_cannot_extend_password_expiry --skip-test-records
```

Result: `Ran 1 test in 2.485s`, `FAILED (failures=1)`, `PermissionError not raised`. This demonstrated a document-save bypass of the password reset date. Guards were then added and PIN change execution was scoped through `as_session_user`.

## Implementation details

- Minimum password length is 10 on account actions, initial User passwords, provisioning, and the overridden Frappe password-change/recovery endpoint. Existing User form password writes are rejected in favor of the old-password/proof-checked account actions.
- Password expiry uses the actual native `User.last_password_reset_date` Date field, with application validation at `date_diff >= 90`. Missing dates fall back to User creation. The login hook also rejects expired direct login operations. Native recovery remains functional through a request-local marker set only after the native old-password/recovery-key verifier succeeds.
- Frappe v15's `LoginManager.force_user_to_reset_password` uses `date_diff > setting`; therefore the setting is **89**, yielding expiry on day **90**, not day 91. No invented `password_expiry` field was added.
- Frappe v15's `LoginAttemptTracker.is_user_allowed` uses `failed_count > setting`; therefore the setting is **4**, yielding denial after the **fifth** consecutive failure. The 300-second lockout and actual tracker boundaries are tested.
- Native OTP App 2FA is enabled for TC R01/R02/R09/R10 and disabled on the other TC R01..R10 roles. Restricted-IP bypass is disabled. Installation and migration apply these native role settings.
- Self-service password and PIN changes require the old secret. Password changes update the native date and invalidate linked station sessions. PIN changes clear the forced-change flag and audit as the station employee.
- R10 resets are permitted. R02 resets require a server-issued, 120-second PIN proof bound to the current user and a live station session. A raw User, Employee name, station bearer token, missing proof, expired proof, consumed proof, wrong actor or closed session is rejected. Proof keys contain SHA-256 of random tokens; proof values contain only user/session identifiers. Atomic Redis MULTI/EXEC GET-and-DELETE ensures one consumer and avoids requiring Redis 6.2 GETDEL.
- Password resets write the native reset date to `1900-01-01`, forcing the next native login through password recovery. PIN resets set persistent Employee reset state, which cannot be cleared by a generic document save; privileged PIN verification returns `PIN_CHANGE_REQUIRED` until the old-PIN-checked change succeeds.
- Employee card IDs are trimmed, uppercased and checked for uniqueness in addition to the existing database unique field.
- Card disable closes every open linked station session. Status Left also disables the card and linked User; the native User lifecycle clears web sessions and the app closes station sessions. Offboarding of a linked enabled User requires R10.
- User creation/enable/disable is guarded at the document layer, including calls using `ignore_permissions=True`; provisioning also checks R10. User, Employee and the existing Station Session/Audit Log no-delete protections preserve history.
- Credential audit payloads contain event names and access-state metadata only. No plaintext password, PIN, encrypted hash, recovery token or reset proof is written to app audit events. Tests inspect audit bodies for old/new secret leakage.

## Exact validation commands and results

All commands below ran in the isolated WSL Ubuntu-22.04 distribution. The Windows wrapper was `wsl -d Ubuntu-22.04 -- bash -lc "..."` with the required sandbox escalation. The default WSL distribution was not used after its initial discovery error (it was docker-desktop, not Ubuntu).

```sh
cd /home/tien2003/tracecore-codex
bench --site test_codex migrate
```

Result: completed successfully, including fixtures and `after_migrate` policy hook; only `test_codex` migrated.

```sh
cd /home/tien2003/tracecore-codex/apps/tracecore
pre-commit run --files tracecore/core/account.py tracecore/core/tests/test_account.py tracecore/hooks.py tracecore/setup/install.py tracecore/setup/provision.py tracecore/fixtures/custom_field.json tracecore/translations/vi.csv tracecore/v1/station.py
```

Result: final run exit 0. All applicable hooks passed: whitespace, conflict, AST, JSON, debug statements, Ruff imports/lint/format, Bandit, architecture rules and BRU coverage. Non-applicable TOML/YAML/JS/CSS hooks skipped. Earlier formatter runs changed only the two new Python files; those changes were staged and the complete checks rerun successfully.

```sh
cd /home/tien2003/tracecore-codex
bench --site test_codex run-tests --module tracecore.core.tests.test_account --skip-test-records
bench --site test_codex run-tests --module tracecore.core.tests.test_station_auth --skip-test-records
bench --site test_codex run-tests --module tracecore.tests.test_provision --skip-test-records
bench --site test_codex run-tests --module tracecore.tests.test_install --skip-test-records
```

Results: **19 account tests OK (67.270s); 6 station-auth tests OK (10.351s); 4 provisioning tests OK (1.261s); 3 installation tests OK (0.026s)**. Total: **32 tests passed**.

After the final portable Redis atomic-consumption refactor, all relevant pre-commit checks were rerun and passed, followed by:

```sh
bench --site test_codex run-tests --module tracecore.core.tests.test_account --test test_r02_reset_requires_single_use_live_station_pin_proof --test test_proof_expires_and_is_bound_to_actor_and_open_session --skip-test-records
```

Result: **2 tests OK (5.746s)**, verifying the exact changed proof-consumption path, expiry, replay, actor/session binding.

```sh
cd /home/tien2003/tracecore-codex/apps/tracecore
git diff --cached --check
git commit -m 'feat(auth): quản trị tài khoản và vô hiệu nhân viên'
chmod 644 tracecore/core/account.py tracecore/core/tests/test_account.py
git add tracecore/core/account.py tracecore/core/tests/test_account.py
git commit --amend --no-edit
git rev-parse HEAD
git status --short
git diff HEAD --check
```

Result: final commit `340f490e8022d1da531c04dc96e3ab2fbc70de91`; exactly eight Task 5 files, 604 insertions / 1 deletion; both new Python files are mode 100644. No tracked worktree changes remain; only the preserved untracked `.superpowers/` handoff directory exists. The last amendment changed file modes only, after verified code had been committed.

## Self-review and concerns

- Re-read Task 5 brief and checked every binding decision against implementation/test coverage.
- Inspected actual local Frappe v15 source to verify settings names, strict comparison boundaries, recovery verification and native disabled-User session clearing.
- Searched every production `verify_pin` caller: station privilege verification and proof issuance enforce forced PIN change; the dedicated change operation intentionally allows the old temporary PIN so it can be replaced.
- Reviewed staged diff, scope, audit payloads, no-delete behavior, role checks, proof storage, Redis atomicity and recovery marker cleanup. No unrelated tracked files changed.
- Frappe's built-in `Administrator` remains the bootstrap/recovery exception to the R10 business-role guard. Ordinary System Manager/TC role users still need TC R10. This is intentional framework administration compatibility, not an R02 reset bypass.
- Expiry follows the native Date field's calendar-day semantics, with the application boundary tested at days 89 and 90. This does not introduce timestamp-based credential-age tracking.
- Actual interactive OTP enrollment/browser login was not exercised. Native 2FA settings and exact selected role flags were verified against database and Frappe source; real OTP delivery/enrollment remains native Frappe behavior.
- No blocking concerns remain. The full broad app suite was not run; the requested account tests plus directly affected station/provision/install modules and all relevant pre-commit checks passed.

---

# Task 5 review-fix report (authoritative update)

Latest status: **DONE_WITH_CONCERNS** — all supported review findings fixed and verified; concurrency coverage is deterministic rather than a live two-connection race, as permitted by the review request.

Fix commit: **`b32936373ae3a052406633b95d0726760d961046`** (`fix(auth): enforce OTP recovery and atomic employee revocation`). Parent commit is the original Task 5 implementation `340f490e8022d1da531c04dc96e3ab2fbc70de91`.

The original report above is retained as historical evidence. Its recovery-marker design and broad Administrator bootstrap exception are superseded by the fixes below.

## Supported findings and final behavior

1. **P1: recovery bypassed mandatory 2FA.** Confirmed that native Frappe `update_password()` calls `login_as()` and does not run the normal OTP login challenge. The app wrapper now uses the native recovery-key verifier only, checks account eligibility, writes the credential/date, invalidates existing sessions through the app credential writer, and returns `/login`. It never delegates to native `update_password()`, never calls `login_as()`, and never creates a session. The temporary `tc_password_update_user` login bypass marker was removed entirely. Authenticated old-password changes also use the credential writer without authenticating a new session.

2. **P1: unlink/offboarding lost the previous User.** Employee validation now checks `before.user_id` and requires an explicitly assigned R10 role for unlinking or reassignment. Offboarding closes sessions and disables both the previous and current linked User when applicable. Simultaneous `user_id=None` plus `status=Left` disables the previous User, card and sessions. Unlink/reassignment closes old station sessions; plain unlink also disables the card. R02 cannot evade the guard by clearing the link while setting Left.

3. **P2: public native email reset remained available.** `frappe.core.doctype.user.user.reset_password` is overridden by `reject_email_reset`. Its dispatched Guest endpoint rejects the request without generating a recovery key or sending email. Users must request an R10 reset or an R02 reset with a valid station PIN proof. The native expired-password change route remains available after verification of the old credential, but it cannot authenticate a session.

4. **P1: login raced card disable/offboarding.** New `station_auth.lock_employee()` acquires an Employee `FOR UPDATE` row lock. Station login resolves the card and then locks/rereads that row **before** checking active status, current card ID, card enablement, linked User and session creation. Employee save/revocation and `close_employee_sessions()` use the same row. Session closure itself selects open sessions with `FOR UPDATE` and reloads each with `for_update=True`, so it sees sessions committed while the revoker waited for the Employee lock even when an earlier ordinary read used an older database snapshot. Session authentication locks Employee then Station Session, rechecks the session-open flag, Employee/card/status/current User link and User enablement, and closes/rejects stale sessions. Proof consumption uses the same Employee-then-session lock order and current relationship check.

5. **Administrator scope:** Business authority now checks the actual `Has Role` child assignment, rather than `frappe.get_roles("Administrator")`, which synthesizes every role. An Administrator without an explicitly assigned TC R10 role cannot reset, create/disable business accounts, or obtain R02 reset authority from synthetic roles. The only exception is **new User creation** during the server-owned `frappe.flags.in_install` lifecycle while acting as Administrator. It is enabled only by the User-insert validator. It never permits reset/disable operations, even during installation. Tests give their fixture Administrator an explicit R10 assignment instead of relying on the former implicit exception, and test both the denial and the narrow installation exception.

## Files in fix commit

- `tracecore/core/account.py`: non-authenticating recovery; blocked email-reset handler; actual-role authorization; narrowly scoped installation creation; previous-link validation/offboarding; proof locking.
- `tracecore/core/station_auth.py`: Employee row serialization, active-credential rechecks, current-read session closure and stale-session rejection.
- `tracecore/core/tests/test_account.py`: real recovery/password/TOTP integration, all review regressions, deterministic race/current-read coverage, reusable isolated synthetic fixtures. Total now 29 account tests.
- `tracecore/core/tests/test_station_auth.py`: fixture Administrator explicitly receives R10.
- `tracecore/tests/test_provision.py`: fixture Administrator explicitly receives R10.
- `tracecore/hooks.py`: native Guest email-reset endpoint override.
- `tracecore/translations/vi.csv`: supervised-reset instruction in Vietnamese.

No other tracked files were modified. The isolated Codex branch and `test_codex` site were used throughout; the normal development bench and tracked Windows source were not touched.

## Red evidence and investigation

The first regression batch added eight tests before production fixes:

```sh
cd /home/tien2003/tracecore-codex
bench --site test_codex run-tests --module tracecore.core.tests.test_account --test test_recovery_keeps_guest_session_until_password_and_real_otp_login --test test_r02_cannot_unlink_or_reassign_employee_user --test test_simultaneous_unlink_and_left_disables_previous_user --test test_guest_cannot_invoke_native_email_reset_endpoint --test test_administrator_without_explicit_r10_cannot_reset_or_disable --test test_install_bootstrap_allows_creation_but_not_account_reset --test test_session_rechecks_card_status_link_and_user_enablement --test test_station_login_locks_employee_before_checking_active_card --skip-test-records
```

Initial result: `Ran 8 tests in 18.431s`, `FAILED (failures=5, errors=3)`. The five actual failures showed unrestricted Administrator resets, R02 unlink, unchanged previous User after simultaneous unlink/Left, accepted stale sessions, and login without an Employee lock. Three fixture errors were then corrected: request IP required by the native rate limiter, the native OTP defaults namespace, and mapping-style installation flags.

The three affected regressions were rerun before changing production behavior:

```sh
bench --site test_codex run-tests --module tracecore.core.tests.test_account --test test_recovery_keeps_guest_session_until_password_and_real_otp_login --test test_guest_cannot_invoke_native_email_reset_endpoint --test test_install_bootstrap_allows_creation_but_not_account_reset --skip-test-records
```

Result included **three meaningful assertion failures**. In particular, actual recovery produced `frappe.session.user == account.supervisor@example.test` when the expected caller was Guest. The native Guest email reset accepted the call, and the former Administrator shortcut still allowed reset during installation. That original real-login RED also caused two teardown errors because native session creation committed fixture data. The final integration test suppresses `Database.commit` class-wide for test isolation and restores session context explicitly; it does **not** mock LoginManager, login_as, password authentication, OTP verification or session creation. The two synthetic Employee/card fixtures that the RED run committed are preserved and reused; no no-delete business/audit records were removed. Any generated native web sessions were invalidated by subsequent credential-reset test setup.

After the principal fixes, seven review tests passed; the remaining real-OTP setup used the wrong enrollment namespace and attempted native email enrollment. Correcting it to `frappe.twofactor.set_default()` exercised native enrolled TOTP successfully. The complete real recovery test then passed in 3.187s, followed by the full requested suite at 28 account + 6 station + 4 provisioning + 3 installation tests. Both recovery tests were also rerun after removing the obsolete mocked-login predecessor: `Ran 2 tests in 8.003s`, `OK`.

A final lock-order self-review identified the older-snapshot session-enumeration edge. Its regression was written and observed RED before its fix:

```sh
bench --site test_codex run-tests --module tracecore.core.tests.test_account --test test_session_closure_uses_current_read_after_waiting_on_employee --skip-test-records
```

Result: `Ran 1 test in 2.294s`, `FAILED (failures=1)`, `AssertionError: 0 != 1`. The fix replaced ordinary session enumeration and document reload with locking current reads, followed by the final complete run below.

## Final exact validation commands/results

```sh
cd /home/tien2003/tracecore-codex/apps/tracecore
pre-commit run --files tracecore/core/account.py tracecore/core/station_auth.py tracecore/core/tests/test_account.py tracecore/core/tests/test_station_auth.py tracecore/tests/test_provision.py tracecore/hooks.py tracecore/translations/vi.csv tracecore/setup/provision.py tracecore/setup/install.py tracecore/fixtures/custom_field.json
```

Result: **exit 0**, all applicable hooks passed. Formatter/import corrections were staged and checks rerun. Relevant passing checks include AST, JSON, Ruff import/lint/format, Bandit, architecture and BRU coverage.

```sh
cd /home/tien2003/tracecore-codex
bench --site test_codex run-tests --module tracecore.core.tests.test_account --skip-test-records
bench --site test_codex run-tests --module tracecore.core.tests.test_station_auth --skip-test-records
bench --site test_codex run-tests --module tracecore.tests.test_provision --skip-test-records
bench --site test_codex run-tests --module tracecore.tests.test_install --skip-test-records
```

Final results after **all** code/test changes: **29 account tests OK (83.802s), 6 station-auth tests OK (11.010s), 4 provisioning tests OK (2.548s), 3 installation tests OK (0.013s)**. Total: **42 tests passed**. Final native recovery coverage verifies:

- A valid expired-password recovery key changes the credential and date but leaves the caller Guest.
- No Session row or `sid` cookie is created by recovery.
- A normal login using the new password without OTP still leaves Guest and creates no Session.
- A real `pyotp.TOTP` matching Frappe's native secret passes the native OTP verifier and then creates the actual R02 session and cookie.
- LoginManager/login_as/OTP/session creation are not replaced by mocks; only transaction commit is suppressed to preserve test savepoints.

```sh
cd /home/tien2003/tracecore-codex/apps/tracecore
git diff --cached --check
git commit -m 'fix(auth): enforce OTP recovery and atomic employee revocation'
git rev-parse HEAD
git status --short
```

Result: commit **`b32936373ae3a052406633b95d0726760d961046`**, seven fix files, 309 insertions / 56 deletions. Tracked worktree clean; only the preserved untracked `.superpowers/` report/brief directory remains.

## Concurrency coverage and remaining limitations

A live two-connection race was not added: these integration fixtures are normally uncommitted and isolated by per-test savepoints, so a secondary connection cannot read freshly created Employee/User/competency rows. Committing fixture data solely for a race would defeat that isolation and complicate the explicit no-delete constraint. The early native-login RED demonstrated that risk and its synthetic records were preserved. The review explicitly permits deterministic lock-order/recheck coverage when two-connection coverage is not feasible.

The deterministic tests exercise actual SQL and record actual lock ordering, inject revocation immediately before the Employee locking read completes, assert login rejects with `CARD_INVALID`, assert card-disable locks Employee before scanning Station Session, simulate an earlier ordinary session-list snapshot and require current-read closure, and independently mutate card enablement, Employee status, linked User and User enablement to require stale-session closure plus `SESSION_INVALID`. This covers both serialization order and post-lock eligibility checks without claiming a live cross-connection scheduler test.

The entire broad application suite was not run. All requested modules and all relevant pre-commit checks pass, including actual native password-plus-TOTP integration. No supported review finding remains unresolved; the only stated concern is the deterministic rather than live two-connection concurrency test limitation.
