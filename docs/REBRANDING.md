# Game Library rebranding and compatibility

GameLibrary is the product and repository name. **Game Library** is the default
display title, and administrators may replace it through Branding. The historical
`sharewarez` name still appears in compatibility-sensitive identifiers; those
identifiers must not be changed with a repository-wide search and replace.

## Naming layers

### Display branding

New user-facing copy uses the configured `site_title`. Python defaults come from
`sharewarez.branding.DEFAULT_SITE_TITLE`; the default logo path comes from the same
module. Do not add another hard-coded product-name or logo-path default.

Current documentation should say GameLibrary when it refers to the product.
Historical audit titles and explicit upstream attribution may retain Sharewarez.

### Stable compatibility identifiers

The following names remain supported until a separately versioned migration is
implemented:

- the `sharewarez` Python package and import path;
- `SHAREWAREZ_*` startup environment variables;
- the `sharewarez.json` local-metadata filename and its older schema keys;
- `X-Sharewarez-*` webhook headers and the `Sharewarez-Webhook/1` user agent;
- existing database, volume, image, and filesystem names used by deployments;
- the legacy default-logo asset path.

Documentation may describe these exact identifiers even though the product name is
GameLibrary.

## Migration order

1. Finish display-copy cleanup and keep configurable titles flowing through email,
   templates, notifications, and integrations.
2. Introduce `GAMELIBRARY_*` environment aliases while continuing to accept the
   legacy variables, with deterministic precedence and tests.
3. Add `X-GameLibrary-*` webhook headers alongside the signed legacy headers. A
   signing-version change requires an explicit protocol version and migration guide.
4. Prefer `gamelibrary.json` for newly written local metadata while continuing to
   read `sharewarez.json`; never strand existing library metadata.
5. Move or alias the default logo only after persisted branding paths and installed
   themes have a fallback.
6. Rename the Python package last. Treat it as an application migration with import,
   CLI, Alembic, container-entrypoint, plugin, and operator compatibility coverage.

Each stage should be independently releasable and reversible. Remove a legacy name
only after its replacement has shipped for a documented compatibility window.

## Reusable-component direction

Shared Jinja primitives live in `templates/partials/ui_components.html`; shared
authentication layout lives in `partials/auth_layout.html`; repeated integration
forms are already partials. Migrate one coherent page family at a time instead of
building a second component system.

Near-term candidates are:

- finish moving manual page headers to `page_header` or `admin_page_header` while
  preserving route-specific actions and heading IDs;
- move generic status styling out of download-specific CSS after every current
  status consumer has regression coverage;
- consolidate repeated labelled form errors and field help into a small macro;
- keep route-specific tables and complex workspaces local until their data and
  interaction contracts genuinely match.

The shared surface, control, mobile-gutter, theme-token, and accessibility rules in
`UI_AUDIT.md` remain authoritative for every extraction.
