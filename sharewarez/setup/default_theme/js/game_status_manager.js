// game_status_manager.js
// Manages game completion status UI and API interactions

console.log('[GameStatusManager] ===== SCRIPT LOADED =====');
console.log('[GameStatusManager] Script execution started, waiting for DOMContentLoaded...');

document.addEventListener('DOMContentLoaded', () => {
    console.log('[GameStatusManager] ===== INITIALIZING =====');
    console.log('[GameStatusManager] DOMContentLoaded event fired');

    // Check if play status feature is disabled - if no buttons exist, don't proceed
    const statusButtons = document.querySelectorAll('.game-status-btn');
    if (statusButtons.length === 0) {
        console.log('[GameStatusManager] Play status feature is disabled or no status buttons found. Skipping initialization.');
        return;
    }

    // Status configuration matching models.py
    const STATUS_CONFIG = {
        'unplayed': {
            icon: 'fa-box',
            label: 'Unplayed'
        },
        'unfinished': {
            icon: 'fa-gamepad',
            label: 'Unfinished'
        },
        'beaten': {
            icon: 'fa-flag-checkered',
            label: 'Beaten'
        },
        'completed': {
            icon: 'fa-trophy',
            label: 'Completed'
        },
        'null': {
            icon: 'fa-ban',
            label: "Won't Play"
        },
        '': {
            icon: 'fa-circle',
            label: 'No Status',
            empty: true
        }
    };

    // Initialize all status buttons on the page
    const initializeStatusButtons = () => {
        console.log('[GameStatusManager] initializeStatusButtons() called');
        // Re-query buttons each time to catch dynamically added ones
        const statusButtons = document.querySelectorAll('.game-status-btn');
        console.log('[GameStatusManager] Found status buttons:', statusButtons.length);

        const csrfToken = CSRFUtils.getToken();
        if (!csrfToken) {
            console.error('[GameStatusManager] CSRF token not found. Cannot proceed.');
            return;
        }
        console.log('[GameStatusManager] CSRF token found:', csrfToken.substring(0, 10) + '...');

        statusButtons.forEach((button, index) => {
            console.log(`[GameStatusManager] Processing button ${index + 1}:`, button);
            // Skip already initialized buttons
            if (button.dataset.statusInitialized) {
                return;
            }
            button.dataset.statusInitialized = 'true';

            const gameUuid = button.dataset.gameUuid;
            console.log(`[GameStatusManager] Button ${index + 1} game UUID:`, gameUuid);
            if (!gameUuid) {
                console.warn('[GameStatusManager] Found a status button without a game-uuid.');
                return;
            }

            // Set initial state from data attribute
            const currentStatus = button.dataset.currentStatus || '';
            console.log(`[GameStatusManager] Button ${index + 1} current status:`, currentStatus);
            updateButtonAppearance(button, currentStatus);
            console.log(`[GameStatusManager] Button ${index + 1} appearance updated`);

            // Add click handler to toggle dropdown
            button.addEventListener('click', (e) => {
                console.log(`[GameStatusManager] Button clicked for game ${gameUuid}`);
                e.preventDefault();
                e.stopPropagation();

                const dropdown = button.nextElementSibling;
                console.log(`[GameStatusManager] Found dropdown:`, dropdown);
                if (dropdown && dropdown.classList.contains('status-dropdown')) {
                    // Toggle this dropdown
                    const isVisible = dropdown.style.display === 'block';

                    // Close all other dropdowns first
                    document.querySelectorAll('.status-dropdown').forEach(d => {
                        d.style.display = 'none';
                        d.previousElementSibling?.setAttribute('aria-expanded', 'false');
                    });

                    dropdown.style.display = isVisible ? 'none' : 'block';
                    button.setAttribute('aria-expanded', String(!isVisible));
                    if (!isVisible) {
                        dropdown.querySelector('.status-dropdown-option')?.focus();
                    }
                    console.log(`[GameStatusManager] Dropdown toggled to: ${dropdown.style.display}`);
                } else {
                    console.warn(`[GameStatusManager] Dropdown not found or invalid for button ${gameUuid}`);
                }
            });
            console.log(`[GameStatusManager] Click handler attached to button ${index + 1}`);
        });

        // Initialize dropdown option click handlers
        const dropdownOptions = document.querySelectorAll('.status-dropdown-option');
        dropdownOptions.forEach(option => {
            if (option.dataset.optionInitialized) {
                return;
            }
            option.dataset.optionInitialized = 'true';

            option.addEventListener('click', async (e) => {
                e.preventDefault();
                e.stopPropagation();

                const dropdown = option.closest('.status-dropdown');
                const gameUuid = dropdown.dataset.gameUuid;
                const newStatus = option.dataset.status;
                const button = dropdown.previousElementSibling;

                // Hide dropdown
                dropdown.style.display = 'none';
                button.setAttribute('aria-expanded', 'false');

                // Update status
                await setGameStatus(button, gameUuid, newStatus);
            });
        });

        console.log(`[GameStatusManager] Initialized ${statusButtons.length} status buttons`);
    };

    // Update button appearance based on status
    const updateButtonAppearance = (button, status) => {
        const icon = button.querySelector('i');
        const config = STATUS_CONFIG[status] || STATUS_CONFIG[''];

        if (icon) {
            // Remove all possible status icon classes
            icon.className = '';
            icon.classList.add('fas', config.icon, `status-icon-${status || 'empty'}`);
            icon.style.removeProperty('color');
            icon.style.removeProperty('opacity');
        }

        // Update data attribute
        button.dataset.currentStatus = status || '';
        button.title = config.label;
        const gameName = button.getAttribute('aria-label')?.split('. Current status:')[0]?.replace('Set play status for ', '') || 'game';
        button.setAttribute('aria-label', `Set play status for ${gameName}. Current status: ${config.label}`);
    };

    // Set game status via API
    const setGameStatus = async (button, gameUuid, newStatus) => {
        const icon = button.querySelector('i');
        const originalIconClass = icon.className;

        try {
            // Show loading spinner
            icon.className = 'fas fa-circle-notch fa-spin status-icon-progress';
            button.classList.add('processing');

            const response = await fetch(`/api/set_game_status/${gameUuid}`, {
                method: 'POST',
                headers: CSRFUtils.getHeaders({
                    'Content-Type': 'application/json'
                }),
                body: JSON.stringify({ status: newStatus })
            });

            if (!response.ok) {
                throw new Error(`Failed to set status: ${response.statusText}`);
            }

            const data = await response.json();

            if (data.success) {
                // Keep every instance (card, cover, and mobile action bar) in sync.
                document.querySelectorAll(`.game-status-btn[data-game-uuid="${CSS.escape(gameUuid)}"]`)
                    .forEach(statusButton => updateButtonAppearance(statusButton, data.status));

                // Show success animation
                await showSuccessAnimation(button);

                // Show toast notification
                $.notify(data.message, "success");

                return data;
            } else {
                throw new Error(data.error || 'Failed to set status');
            }
        } catch (error) {
            console.error('[GameStatusManager] Error setting status:', error);

            // Revert appearance
            icon.className = originalIconClass;

            $.notify("Failed to update status", "error");
            throw error;
        } finally {
            button.classList.remove('processing');
        }
    };

    // Show success animation (checkmark)
    const showSuccessAnimation = async (button) => {
        return new Promise((resolve) => {
            const icon = button.querySelector('i');
            const originalClass = icon.className;

            // Show checkmark
            icon.className = 'fas fa-check status-icon-beaten';

            // Restore after 1 second
            setTimeout(() => {
                icon.className = originalClass;
                resolve();
            }, 1000);
        });
    };

    // Close all dropdowns when clicking outside
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.game-status-btn') && !e.target.closest('.status-dropdown')) {
            document.querySelectorAll('.status-dropdown').forEach(dropdown => {
                dropdown.style.display = 'none';
                dropdown.previousElementSibling?.setAttribute('aria-expanded', 'false');
            });
        }
    });

    // Close dropdowns when popup menus open/close
    document.addEventListener('click', (e) => {
        if (e.target.closest('[id^="menuButton-"]')) {
            document.querySelectorAll('.status-dropdown').forEach(dropdown => {
                dropdown.style.display = 'none';
                dropdown.previousElementSibling?.setAttribute('aria-expanded', 'false');
            });
        }
    });

    // Initial run
    initializeStatusButtons();

    // Use MutationObserver to handle dynamically added buttons (e.g., in library view with pagination)
    const observer = new MutationObserver((mutations) => {
        mutations.forEach((mutation) => {
            if (mutation.addedNodes.length) {
                initializeStatusButtons();
            }
        });
    });

    const gamesContainer = document.getElementById('gamesContainer');
    if (gamesContainer) {
        observer.observe(gamesContainer, { childList: true, subtree: true });
    }

    // Also observe the game details container
    const gameDetailsContainer = document.querySelector('.glass-panel-gamecard');
    if (gameDetailsContainer) {
        observer.observe(gameDetailsContainer, { childList: true, subtree: true });
    }

    console.log('[GameStatusManager] Ready');
});
