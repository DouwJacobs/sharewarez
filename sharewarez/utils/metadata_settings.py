"""Credential mutation authority shared by setup and administrator endpoints."""
from sharewarez.utils.metadata_providers import validate_provider_order
from sharewarez.utils.settings_sections import locked_settings


def apply_metadata_credentials(data, *, credentials_only=False):
    settings = locked_settings()
    client_id = str(data.get('igdb_client_id') or '').strip() or settings.igdb_client_id
    client_secret = str(data.get('igdb_client_secret') or '').strip() or settings.igdb_client_secret
    if not credentials_only:
        order = validate_provider_order(data.get('metadata_provider_order', settings.metadata_provider_order))
        rawg_enabled = bool(data.get('rawg_enabled', settings.rawg_enabled))
        rawg_key = str(data.get('rawg_api_key') or '').strip() or settings.rawg_api_key
        if 'igdb' in order and not (client_id and client_secret):
            raise ValueError('IGDB credentials are required while IGDB is in the provider order.')
        if rawg_enabled and not rawg_key:
            raise ValueError('A RAWG API key is required before RAWG can be enabled.')
        if 'rawg' in order and not rawg_enabled:
            raise ValueError('Enable RAWG before adding it to the provider order.')
        settings.rawg_api_key, settings.rawg_enabled = rawg_key, rawg_enabled
        settings.metadata_provider_order = list(order)
    settings.igdb_client_id, settings.igdb_client_secret = client_id, client_secret
    return settings
