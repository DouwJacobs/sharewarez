# Audit remediation — 5 September 2026

This tracks the fixes for [the full audit](FULL_AUDIT_2026-09-05.md). The audit
remains the original evidence record. An item is only marked verified for the
scope of the checks recorded here; final full-suite and browser verification
remain outstanding until explicitly recorded.

| Finding | Status | Implementation and evidence |
| --- | --- | --- |
| A1: member catalogue mutation | Fixed; focused tests pass | Administrator guard on move endpoint; member denial preserves library assignment. |
| A2: disabled sessions | Fixed; focused tests pass | Flask loader and user authentication state reject disabled records; direct downloads use SSE account validation in a thread. Existing-session read/mutation and direct-download regressions pass. |
| A3: AJAX attribute injection | Pending | |
| A4: sensitive logs | Fixed; focused tests pass | Removed form/token dumps and SMTP protocol debugging. Request logs use route patterns, including a safe unmatched-route marker. Synthetic password/path token regressions pass. |
| A5: fresh search bootstrap | Pending | |
| A6: reset timestamps | Pending | |
| A7: blocking download admission | Pending | |
| A8: theme replacement/isolation | Fixed; focused tests pass | Stage and validate all packaged themes, serialize resets, roll back failed publication, retain originals if rollback fails. 43 theme route tests and 2 recovery tests pass using temporary assets. |
| B1: email normalization | Pending | |
| B2: invite transaction | Pending | |
| B3: recovery/delivery feedback | Pending | Invalid confirmation also links to a nonexistent activation endpoint; fix with the resend flow. |
| B4: Library state | Pending | |
| B5: malformed cookie | Pending | |
| B6: folder boundary | Fixed; focused tests pass | Canonical paths plus common-path containment reject sibling, parent, absolute and symlink escapes. Tests use actual temporary directories. |
| B7: indexed candidate search | Pending | |
| B8: unbounded legacy search | Pending | |
| B9: startup failure | Fixed; focused tests pass | Strict shell error handling; stub initializer exit 17 prevents Uvicorn launch. |
| C1: page semantics | Pending | |

## Verification so far

The initial 71 focused tests passed across audit security, filesystem browser, game API,
authentication utilities and observability. Ruff passed before the final
verification run. Tests use the explicitly disposable PostgreSQL database
`sharewarezfixestest` in container `sharewarez-fixes-test` on port 55439.

## Remaining improvement work

- Reduce duplicated Library markup and share safe card/menu rendering.
- Consolidate/parallelize filter options and combine notification counts.
- Add realistic PostgreSQL, browser and concurrency regressions for remaining findings.
- Complete full isolated-module verification and retry visual/accessibility checks.
- Measure revised search and Library response costs and exercise real disposable
  archive/interruption/concurrent-stream behavior; record production/WAN limits.
Subsequent isolated checks passed for model behavior (32), API tokens (4), SSE
(15), download ranges (18), HTTP security (3), SMTP diagnostics (31), SMTP sending
(28), the expanded audit security module (10), container layout (2), quality-gate
contracts (1), theme routes (43), and theme rollback recovery (2). Older tests
that expected unconditional active state or SMTP protocol debugging were updated
to assert the corrected security contract.
