# Game relationships

GameStack imports release relationships and series membership from IGDB during
game identification and metadata refresh. The game-details storefront displays
the information in one flat **Related releases** section.

## Stored relationships

`game_relationships` stores directional links for parent games, editions, DLC,
expansions, standalone expansions, remakes, remasters, expanded releases,
platform ports, and bundles. The related IGDB ID and display name are retained
even when the related title is not in the local library. When that title is
added later, GameStack automatically resolves the stored record to its local
game UUID and makes the relationship navigable.

`game_groups` and `game_group_memberships` normalize IGDB collections (series)
and franchises. Provider identity is unique, so repeated refreshes update and
reuse the same group instead of creating duplicates.

Updates and extras remain file-level children in `game_updates` and
`game_extras`. Edition labels and installed versions remain on the local game;
IGDB `version_parent` supplies the cross-title edition relationship. IGDB ports
supply platform-version relationships.

## Refresh behavior

Provider-owned relationships for a game are replaced atomically from the
latest metadata response. This removes relationships that the provider no
longer returns without touching future manually managed providers. Existing
games receive relationships the next time their metadata is refreshed; newly
identified games receive them during creation.

The public API includes `series`, `franchises`, and `relationships` in the
detailed `GET /api/v1/games/{uuid}` response. It never exposes local paths.

Schema revision: `20260811_12`.
