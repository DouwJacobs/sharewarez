# UI handoff implementation audit — 7 September 2026

**Follow-up:** all confirmed findings below have been addressed. The original
review is retained as historical evidence; see the resolution and verification
record at the end. UI-06's broader coverage gaps remain open.

## Verdict and scope

The implementation is not ready for acceptance. The Game Edit redesign exists,
but valid browser submissions cannot save. UI-02, UI-03, UI-05, and UI-07 need
follow-up; UI-06 remains incomplete. This review changes documentation only.

Reviewed local main through `2b54103`, including `c9d580b` and the verification
claims in `1dc9363`. Used the synthetic authenticated preview on port 5008,
in-app browser inspection, isolated Chrome/Playwright behavior checks, source
review, and targeted regression tests. Network mutations in browser reproductions
were intercepted; no actual game deletion or save was performed.

## Confirmed findings

### A1 — P1: Both editor save actions are cancelled

Source: `sharewarez/setup/default_theme/js/admin_game_identify.js:221–231` and
`:490–495`. Two declarations of `checkFieldsAndToggleSubmit()` exist in the same
scope. The later declaration overrides the earlier Boolean-returning version and
returns undefined. The new submit handler consequently always prevents submission.

Reproduction: open a populated editor, provide valid ID/name/path, and activate
each enabled save action with POST interception installed. Both `save` and
`save_and_refresh` yielded `defaultPrevented: true`, zero POSTs, and no navigation.
The shared identification template may expose other modes to the same defect;
those modes still need browser coverage.

Required fix: retain one authoritative Boolean validator, including library
validation. Add browser behavior regressions for Save, Save & Refresh, Enter,
invalid fields, action payload preservation, and duplicate-submit protection.

### A2 — P2: Desktop list-card actions overlap

Source: `sharewarez/setup/default_theme/css/games/library_browser.css:785–787`
and shared card action positioning. At 1440 × 1000, the list cover is 72 px wide;
hamburger horizontal bounds are 377–411 px and favorite bounds are 399–429 px.
Their targets overlap by 12 px. The mobile cover adjustment does not resolve the
desktop arrangement. Keep the controls reachable and give them disjoint targets
at desktop as well as the previously checked mobile widths.

### A3 — P2: Escape does not cancel a pending menu opening

Source: `sharewarez/setup/default_theme/js/popup_menu.js:184–208,248–253`.
The Escape listener requires focus within an existing popup. During its initial
fetch, focus is on the trigger and no popup exists, so Escape does nothing.

Reproduction: delay the actions GET by 700 ms, click the trigger, press Escape,
then allow the response. The menu opens with `aria-expanded="true"`. Ordinary
Escape inside a loaded menu does close it. Invalidate pending opens on Escape
and test focus/state restoration across loading, replacement, and failure.

### A4 — P2: IGDB identity changes bypass dirty protection

Source: `sharewarez/setup/default_theme/js/admin_game_identify.js:350–367,469–481`.
Dirty tracking listens only for input/change events, while provider selection
assigns field values programmatically. It also overwrites existing field values
without guarding a dirty draft before the identity operation.

Reproduction: from a clean editor, select a stubbed IGDB result named “Provider
replacement”. Name and summary change, but a cancellable beforeunload event is
not prevented. Track programmatic edits and guard replacement of dirty values;
test selection, lookup, custom-game actions, navigation, and conflict resolution.

### A5 — P2: Database removal permits duplicate requests

Source: `sharewarez/setup/default_theme/js/popup_menu.js:61–73`.
The removal handler has no pending guard or disabled/busy state. With a delayed,
intercepted response, two clicks produced two POSTs and the control remained
enabled. This leaves UI-05's pending-state requirement unfinished. Apply the
shared pending/error/retry behavior and verify one in-flight mutation per game.

### A6 — P2: Keyboard and disclosure contracts remain incomplete

Source: `sharewarez/setup/default_theme/js/admin_game_identify.js:315–316,350–369`;
`sharewarez/templates/games/library_cards.html:4`; and
`sharewarez/templates/games/game_details.html:312`.

IGDB search results remain click-only divs. A rendered result has `tabIndex: -1`
and no role, so keyboard users cannot choose it. Use a native interactive control
and verify visible focus plus Enter/Space activation.

Changing `aria-haspopup="menu"` to `aria-haspopup="true"` does not remove the
menu promise: true has menu semantics. The popup still has no corresponding
menu role/item navigation. Finish the intended disclosure model with ordinary
Tab navigation, or implement the full menu contract.

## Additional source-derived gap requiring browser coverage

The error-summary handler at `admin_game_identify.js:453–459` focuses a field
without opening a containing disclosure. The editor initially closes IGDB
identification in edit mode. Exercise server validation errors within that section
and ensure it opens before focus moves. Do not mark this acceptance case passed
based on the presence of an error-summary selector alone.

## What did land

| Item | Audit assessment |
| --- | --- |
| UI-01 | Shared anchor/button styling implemented. Sampled Open IGDB row and ordinary rows measured the same width and single-line height (188.11 × 46.03 px). Full cross-route/theme acceptance remains pending. |
| UI-02 | Common close path implemented; ordinary Escape passed. Loading cancellation and semantics fail. |
| UI-03 | Mobile arrangement implemented and previously measured; desktop still collides. |
| UI-04 | Shared mobile favorite binding implemented; six favorite behavior tests pass. Full persistence/error/theme matrix was not repeated in this review. |
| UI-05 | Secondary Edit, danger menu styling, and notification changes implemented; pending behavior remains inconsistent. |
| UI-06 | Still incomplete: populated states, roles, themes, setup, and token-dependent routes. |
| UI-07 | Flat editor sections, secondary identification, and action layout implemented; save and interaction acceptance fail. |
| UI-08 | Compact list placeholder containment implemented in `2b54103`; no new fallback clipping found in the sampled list. |

Library and Favorites retain shared card-template ownership. This review does
not revoke the earlier Favorites outer-border fix, but it is not a fresh full
Favorites/theme visual sweep.

## Verification and limitations

Fresh isolated PostgreSQL run: **130 passed in 27.97 seconds** across:

```text
tests/test_ui_consistency_routes.py
tests/test_ui_control_contract.py
tests/test_ui_polish_contract.py
tests/test_accessibility_audit.py
tests/test_routes_apis_user.py
tests/test_routes_library.py
tests/test_mobile_navigation.py
tests/test_routes_games_ext_edit.py
tests/test_metadata_provenance.py
```

Used database `sharewarezregressiontest` on local port 55441, separate from the
synthetic preview database. `node tests/favorites_manager.test.cjs`: **6 passed**.
The green route/source-contract tests do not exercise native browser editor
submission and therefore miss A1. Browser tests must cover observable behavior.

Default-theme synthetic records were sampled. Ember/light palettes, production-
scale content, the full mobile interaction matrix, non-admin menus, and all
failure/confirmation flows were not freshly verified. Prior screenshots and
measurements remain historical evidence, not proof that these cases pass.
The unrelated existing VERSION edit remains untouched. No application fixes,
release, deployment, or publication were performed as part of this audit.

## Resolution and verification — implementation follow-up

- [x] A1: removed the overriding validator; valid Save and Save & Refresh each
  submit once with their correct action payload. Enter in Name performs ordinary
  Save. Repeated submission is blocked; all save controls expose pending state.
- [x] A2: desktop list covers use 104 px width, matching the mobile arrangement.
  Browser assertions confirm disjoint favorite/hamburger targets and no document
  overflow at 1440 × 1000, 390 × 844, and 320 × 844.
- [x] A3: Escape and trigger toggling invalidate pending menu requests and clear
  busy state. Stale successes/errors cannot reopen the dismissed menu. Loaded
  Escape closes the disclosure and restores its trigger focus.
- [x] A4: provider selection, ID lookup, and custom identity mark the editor dirty
  and guard replacement of existing dirty values before applying changes.
- [x] A5: database removal has a per-game pending guard and disabled/busy state;
  failed requests restore retry. Move destinations also have pending/retry state,
  and a failed destination fetch clears loading and reports recovery guidance.
- [x] A6: search results and library destinations are native buttons. Game-action
  triggers use aria-expanded/aria-controls with ordinary Tab navigation, without
  aria-haspopup promising an unimplemented menu model.
- [x] Additional error-focus gap: server error fields open their containing
  disclosures and receive aria-invalid/aria-describedby; initial error focus and
  error-summary links reveal and focus the target field.

Reusable browser coverage lives in `tests/ui_handoff.browser.cjs`. It requires an
explicit disposable `UI_AUDIT_BASE_URL` and `UI_AUDIT_GAME_UUID`, uses the preview's
`/_preview/session` login, stubs provider responses, and intercepts POST requests.
Set `PLAYWRIGHT_MODULE` if Playwright is installed outside the normal module path.
Service workers are blocked in test contexts so they cannot bypass interception.
Optional `UI_AUDIT_SCREENSHOTS` saves screenshots to a local directory.

All **17 browser regression scenarios passed**. The run covers save payloads,
Enter, invalid input, repeated submit,
keyboard provider selection, dirty protection, custom identity, guarded lookup,
server-error disclosure/focus, responsive list geometry, pending/loaded Escape,
removal duplicate protection/retry, and keyboard move/retry. The error case uses
an intercepted HTML fixture; it does not claim end-to-end validation persistence.

The 130 targeted Python regressions passed (27.75 seconds), and six favorite
behavior cases passed. JavaScript syntax and diff whitespace checks passed.
Canonical and installed copies of all four changed theme assets were synchronized.
In-app desktop inspection and separate 390 px rendered screenshots confirmed the
list/editor presentation. UI-06's themes, large populated records, roles, setup,
and token-dependent flows remain outside this focused fix verification.
The unrelated VERSION edit is preserved; no deployment or publication occurred.
