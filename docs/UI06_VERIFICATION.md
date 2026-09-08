# UI-06 verification — 8 September 2026

UI-06 is complete for the handoff's specified UI coverage. The remaining
verification tasks were exercised using disposable PostgreSQL databases and local
preview servers, without changing the user's library, credentials, or theme.

## Coverage and results

**138 route/theme/viewport checks passed:** 46 each in Default, Ember, and an
isolated high-luminance palette. Each palette was verified from its computed
accent, rather than assuming that the requested theme loaded. Desktop was
1440 × 1000; mobile was 390 × 844. The run explicitly activated grid, compact,
and list views rather than relying on a URL parameter to override a saved view.

| Scope | Populated states checked |
| --- | --- |
| Library, Favorites, Game Details | Administrator and member; every Library layout, missing and present artwork, long spaced and unbroken titles |
| Requests and issues | Populated admin request detail, member request list, admin/member issue detail, comments and long paths |
| Collections | Collection list, populated editor and collection-filtered Library |
| Invitations | Populated admin quota table and five invitation rows; internal horizontal table scrolling on mobile |
| Game Edit and image editor | Populated metadata, cover and screenshot gallery, empty key-art/logo groups, end-of-form mobile actions |

The matrix found no HTTP/page-script failures, document overflow, or undersized
visible enabled ordinary `.btn` controls. These automated measurements were
supplemented by in-app desktop inspection and rendered desktop/mobile screenshots;
they are not presented as a complete automated accessibility certification.

**27 interaction/contrast scenarios passed**, covering:

- Administrator/member action menus on Library, Favorites, and Game Details in
  all three palettes; administrator removal is absent for members, the IGDB row
  remains available, Tab traverses the disclosure, and Escape restores focus.
- A populated image gallery with successfully loaded local images; a simulated
  upload failure opens a contained, scrollable error dialog. Tab wraps inside the
  dialog and Escape closes it. The IGDB refresh renders one aggregate progress
  state with matching phase, percentage, bar width, and processed/download counts.
- Reduced-motion page animation, mobile bottom-action clearance, intentional
  table scrolling, an empty filtered Library, and pending/failed action loading.
- Primary-button text contrast of at least 4.5:1 against both gradient endpoints
  in each tested palette; secondary text follows the high-luminance palette.

Initial setup was exercised at desktop and mobile sizes in separate empty
databases: create administrator,
skip SMTP, enter disposable IGDB configuration, finish setup, and reach the login
redirect for library administration. Token-dependent pages were exercised with
disposable accounts: expired confirmation, successful confirmation, already
confirmed state, valid password-reset form, and successful reset returning to
login. Both desktop and mobile completion paths passed. No email, provider
notification, real image upload, or game deletion was
needed for these checks. External service connectivity is outside this UI test.

## Defects fixed

1. **Secondary-button text ignored light palettes.** The shared secondary action
   family now takes its foreground from the active theme instead of keeping a
   pale hard-coded value on a light surface.
2. **Primary-button contrast depended on accent brightness.** Shared primary
   gradients now retain readable white text in Default. Explicit background,
   hover-background, and foreground tokens allow Ember's bright orange buttons
   to use dark text with sufficient contrast. Ordinary controls also expose a
   `--theme-color-scheme` hook for native light/dark input rendering.
3. **Tab could escape a Bootstrap dialog into browser chrome.** The shared modal
   manager explicitly wraps Tab/Shift+Tab for open Bootstrap dialogs as well as
   the existing managed custom dialogs. Bootstrap retains its normal lifecycle.
4. **A lazy-menu test asserted on an obsolete substring.** It now checks that the
   actual popup element is absent while accepting the trigger's `aria-controls`
   reference. Escaping and shared initial/AJAX renderer assertions remain intact.

Canonical theme files and their installed preview copies were synchronized,
including the bundled Ember override. No custom user palette was overwritten.

## Repeating the browser checks

The reusable checks are `tests/ui06_matrix.browser.cjs` and
`tests/ui06_interactions.browser.cjs`. They require an explicitly disposable
`UI_AUDIT_BASE_URL`; the matrix also requires `UI_AUDIT_SCREENSHOTS` for output.
Set `PLAYWRIGHT_MODULE` if Playwright is outside Node's normal module path.

The preview must provide a synthetic `/_preview/session?role=admin|member&theme=…`
login and `/_preview/manifest` returning `game`, `collection`, `request`, and
`issue` identifiers. It needs a collection with slug `ui06-curated`, both roles,
populated favorites, request/issue/comment records, invitations, and a gallery
with at least two local screenshots. These fixture endpoints belong only in the
disposable harness, never in the shipped application. Browser contexts disable
service workers so network interception cannot be bypassed. Interaction POSTs
are intercepted; changing preview role/theme/view affects only synthetic data.

This run used `sharewarezui06test` on PostgreSQL port 55441 with preview port 5010,
and `sharewarezui06setuptest` with setup preview port 5011. Desktop setup used
`sharewarezui06desktoptest` on preview port 5012. The full quality gate
uses its own database/container on port 55443. Screenshot and JSON evidence is
in the host's `C:/Users/douw1/AppData/Local/Temp/ui06-final/`; setup/token evidence
is in the adjacent `ui06/` directory. Fixtures use four games including extreme
titles; this is UI state coverage, not a production-volume performance test.

## Build tracking

The user authorized updating the version and building the Docker image.
`VERSION` advances from the existing 1.14.0 to **1.14.1**. The local quality gate
is configured to build **`douwjacobs/gamelibrary:1.14.1`** after all checks pass.
Build completion and final test totals are recorded below when available.

## Post-audit image refresh follow-up

The Game Images editor now presents image refresh as one overall operation. Its
progress panel reports the current phase, one percentage, and aggregate processed,
downloaded, and failed counts. The server publishes those fields in the existing
progress endpoint.

The refresh continues to use the IGDB API only. A live API check for game `282831`
returned one cover, 15 screenshots, and 9 artworks. The two standalone logos visible
on IGDB's press-kit page were absent from both the expanded game response and the
direct artworks response; no website scraping fallback was added.
