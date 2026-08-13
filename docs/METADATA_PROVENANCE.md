# Metadata provenance and conflict resolution

Game metadata stores field-level source information in `games.metadata_provenance`.
The latest value returned by IGDB is retained in `games.metadata_provider_values`,
including its provider and refresh timestamp.

Provider refreshes update fields that remain provider-owned. When an administrator
changes an editable provider field, that field becomes manual. Later refreshes
preserve the manual value and expose a conflict on the game edit page when IGDB's
latest value differs. An administrator can keep the manual value or accept the
provider value per field.

The tracked conflict-capable fields are name, summary, storyline, URL, videos,
release date, aggregated rating, release type, and release status. Provider-only
rating/count fields also record provenance but are not directly editable. Local
package metadata such as filesystem path, install instructions, package version,
edition name, and tags remains locally owned and is never replaced through this
mechanism.

Choosing **Keep manual** dismisses the current provider candidate. A future refresh
will surface the conflict again if the provider still differs. Choosing the provider
value changes ownership back to that provider, allowing subsequent refreshes to
update the field normally.

Migration `20260813_13` initializes existing games with empty provenance. Their
fields remain unchanged; ownership is learned through the next provider refresh or
administrator edit.
