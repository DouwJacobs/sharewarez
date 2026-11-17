# Release 1.18.0 audit

Scope: torrent attachments/magnets, catalogue matching and date policy, request
jobs/permissions/source selection, admin access history, UI fixes, and the
validation/publishing workflow. Baseline: published 1.17.0 (`bfdff606`).

## Findings and remediation

| Finding | Impact | Resolution |
| --- | --- | --- |
| Partial catalogue failures were ignored if another catalogue matched | Automation could select an older or nonunique release from incomplete inputs | Fixed: require complete automatic lookup inputs; explicit admin selections remain available |
| Long remote torrent validation did not heartbeat between files | Stale job recovery/cancellation could race slow work | Fixed: heartbeat and cancellation checks per source |
| Unrelated settings changes stopped an otherwise valid lookup | Avoidable skipped requests | Fixed: compare only lookup-affecting settings |
| Duplicate matching releases retained the first source's date | Most-recent selection could depend on catalogue order | Fixed: retain the newest valid timestamp for identical releases |
| Invalid magnet links participated in title/date matching | An unusable newest entry could block a usable release | Fixed: validate/filter magnets before matching |
| Malformed international hostnames could escape friendly source errors | Admin source testing could return an internal error | Fixed: normalize/validate hostnames before connecting; prefer public IPv4 when available |
| Queue deduplication loaded every outstanding torrent lookup | Work grew with unrelated request volume | Fixed: bounded server-side request/job lookup |
| Slow scans shared the only request lookup consumer | Automatic availability could wait behind a library scan | Fixed: independent persistent request queue consumer |
| Legacy requests lacked provider-neutral identity columns | Previously verified IGDB requests could fail game creation | Fixed: retain their verified legacy IGDB identity |
| Unexpected job errors left requests showing Looking up | Admins could not distinguish failed work from running work | Fixed: record an actionable failure/cancellation state while retaining bounded retries |
| Transient remote torrent-file failures were treated as invalid content | A valid source could stop permanently after a temporary outage | Fixed: retry unavailable files; reject invalid content without claiming fulfilment |
| Enrichment could outlive a game identity change | Stale metadata could apply to a different identity | Fixed: capture/recheck expected identities before application |
| An authorized resubmission could not resume skipped work | Requests could remain stuck after permissions were restored | Fixed: resubmission can restart skipped/failed work when no job is active |
| Historical migration tests used today's ORM against old schemas and hard-coded an old head | Valid new migrations appeared broken | Fixed: seed before downgrade, use captured IDs and compare to the actual migration head |
| Release validation always ran every module serially and re-resolved dependencies | Slow path to every push, even for isolated changes | Fixed: conservative affected selection, independent concurrent databases, conditional lock resolution, explicit full/release modes |
| Repeated schema introspection, production-cost fixture hashes, and overlapping truncate cascades | Test setup cost dominated assertions | Fixed: one schema preparation, cheap real fixture hashes with production-policy coverage, single FK-safe cleanup, temporary PostgreSQL storage |
| Source-string UI/script assertions duplicated behavioural checks | Tests froze implementation details without proving rendered behaviour | Retired 28 checks in three files; retained real route/rendering/JS/accessibility and migration regressions |
| Version metadata preceded apt/pip layers | Every version bump invalidated expensive dependency builds | Fixed: version labels/environment follow dependency installation |

## Release verification

Full validation passed with 2,338 tests in 273.18 seconds (154 modules, four
independent workers), down from the 395.91-second audit baseline. Lint, typing,
JavaScript, accessibility, dependency audit, migrations, version and Compose
checks passed. Command: `scripts/quality-gate.sh --full --release --workers 4`;
the image was built separately from the validated source. A final conservative
selection fallback for root startup/configuration files passed all seven
validation-workflow tests afterward.

An isolated read-only 1.17.0-to-1.18.0 container upgrade preserved synthetic
games, requests and torrent attachments. Real HTTP checks covered permissions,
CSRF user edits, magnet/torrent access logging and admin access controls. The
separate request consumer processed a persistent job successfully. The release
image is rebuilt from the exact committed revision and published as 1.18.0,
v1.18.0 and latest; registry verification follows publication. Publishing does
not deploy production or modify the shared production database.
