document.addEventListener('DOMContentLoaded', () => {
    const pending = new Set();

    const initializeFavoriteButtons = () => {
        const favoriteButtons = document.querySelectorAll('.favorite-btn');
        if (favoriteButtons.length === 0) {
            return;
        }

        const csrfToken = CSRFUtils.getToken();
        if (!csrfToken) {
            console.error('[FavoritesManager] CSRF token not found. Cannot proceed.');
            return;
        }

        favoriteButtons.forEach(button => {
            // Skip already initialized buttons
            if (button.dataset.favoriteInitialized) {
                return;
            }
            button.dataset.favoriteInitialized = 'true';

            const gameUuid = button.dataset.gameUuid;
            if (!gameUuid) {
                console.warn('[FavoritesManager] Found a favorite button without a game-uuid.');
                return;
            }

            // Set initial state from data attribute
            const isFavorite = button.dataset.isFavorite === 'true';
            updateButtonAppearance(button, isFavorite);

            // Add click handler
            button.addEventListener('click', async (e) => {
                e.preventDefault();
                e.stopPropagation();

                if (pending.has(gameUuid)) return;

                try {
                    await toggleFavorite(button, gameUuid);
                } catch (error) {
                    $.notify('Could not update favorites. Please try again.', 'error');
                }
            });
        });
    };

    const updateButtonAppearance = (button, isFavorite) => {
        const gameName = button.dataset.gameName || 'game';
        button.classList.toggle('favorited', isFavorite);
        button.setAttribute('aria-pressed', String(isFavorite));
        button.setAttribute('aria-label', `${isFavorite ? 'Remove' : 'Add'} ${gameName} ${isFavorite ? 'from' : 'to'} favorites`);
    };

    const toggleFavorite = async (button, gameUuid) => {
        pending.add(gameUuid);
        button.classList.add('processing');
        button.disabled = true;
        button.setAttribute('aria-busy', 'true');

        try {
            const response = await fetch(`/api/toggle_favorite/${gameUuid}`, {
                method: 'POST',
                headers: CSRFUtils.getHeaders({
                    'Content-Type': 'application/json'
                })
            });

            if (!response.ok) {
                throw new Error(`Failed to toggle favorite: ${response.statusText}`);
            }
            const data = await response.json();

            document.querySelectorAll('.favorite-btn').forEach(peer => {
                if (peer.dataset.gameUuid !== gameUuid) return;
                updateButtonAppearance(peer, data.is_favorite);
                peer.dataset.isFavorite = String(data.is_favorite);
            });
            $.notify(data.is_favorite ? 'Added to favorites' : 'Removed from favorites', 'success');

            return data;
        } catch (error) {
            console.error('[FavoritesManager] Error toggling favorite:', error);
            throw error;
        } finally {
            pending.delete(gameUuid);
            button.classList.remove('processing');
            button.disabled = false;
            button.removeAttribute('aria-busy');
        }
    };

    // Initial run
    initializeFavoriteButtons();

    // Use MutationObserver to handle dynamically added buttons (e.g., in library view with pagination)
    const observer = new MutationObserver((mutations) => {
        mutations.forEach((mutation) => {
            if (mutation.addedNodes.length) {
                initializeFavoriteButtons();
            }
        });
    });

    const gamesContainer = document.getElementById('gamesContainer');
    if (gamesContainer) {
        observer.observe(gamesContainer, { childList: true, subtree: true });
    }

});
