# Task 1 report — Record the architecture amendment

Status: DONE

## Summary

Recorded the approved independent React Home exception as Amendment A-19 with the plan's normative text preserved verbatim, including Markdown backticks. Updated ADR-002, the C-02 constraint summary, and the solution strategy to point to that exception. Added an SRS revision note limiting scope to the Home entry experience without changing any FR/BRU IDs. No application code changed.

## Exact files changed

- `docs/architecture.md` — revision row, last-updated date, ADR-002 exception and corresponding architecture summaries.
- `docs/srs.md` — A-19 revision note only.
- `.superpowers/sdd/task-1-report.md` — this report; intentionally untracked and excluded from the commit.

## Amendment number

Chosen: **A-19**. Audited all allocated references in `docs/architecture.md`, including the A-17 revision row's cross-branch reservations: A-13/A-15 for FEAT-019, A-14 for FEAT-011, A-16 for FEAT-022, and A-18 for FEAT-032. A-19 was the next unused number.

## Verification and self-review

- Required command: `pre-commit run --files docs/architecture.md docs/srs.md`.
- Direct PowerShell invocation failed because `pre-commit` is not installed on the Windows PATH.
- Ran the same required command against the actual working tree through the existing WSL installation:

  ```powershell
  wsl -d Ubuntu-22.04 -- bash -lc "cd /mnt/d/tracecore && pre-commit run --files docs/architecture.md docs/srs.md"
  ```

  Result: **exit 0**. `check for merge conflicts` passed; every other hook reported `Skipped (no files to check)` for these Markdown files.
- `git diff --check`: exit 0, no whitespace errors.
- PowerShell compared the architecture normative text against the plan's Markdown code block verbatim: PASS.
- PowerShell compared the unique FR/BRU ID set in the SRS against the pre-change HEAD: PASS, unchanged.
- Reviewed the complete diff: changes are confined to the two scoped documents; table continuity is preserved; no operational screen scope was added.
- Post-commit `git show --stat --oneline HEAD` confirms exactly the two scoped docs were committed (7 insertions, 5 deletions). `git status --short` shows only pre-existing/scratch `.superpowers/` directories as untracked.

## Commit

`2e01593b55ca5d0862e85441497c12600bb1c5f1`

Message: `docs: allow independent TraceCore home`

## Concerns

No implementation concerns. The documentation checks used WSL because Windows lacks the executable; WSL access and Git index writes required sandbox escalation and succeeded. `.superpowers/` artifacts remain outside the commit as required.
