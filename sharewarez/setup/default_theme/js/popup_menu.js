document.addEventListener('DOMContentLoaded', function() {
    
    let currentLibrariesSubmenu = null;
    const pendingRemovals = new Set();
    var csrfToken = CSRFUtils.getToken();

    function getMenuContainer(menu) {
        return menu?.closest('.game-card') || menu?.closest('.game-card-coverimage');
    }

    function closeMenu(menu, options = {}) {
        if (!menu) return;
        const trigger = document.getElementById(menu.id.replace('popupMenu-', 'menuButton-'));
        const container = getMenuContainer(menu);
        menu.style.display = 'none';
        menu.style.removeProperty('--popup-menu-max-height');
        trigger?.setAttribute('aria-expanded', 'false');
        container?.classList.remove('menu-open');
        container?.closest('.game-card-container')?.classList.remove('menu-open');
        showCardButtons(container);
        if (options.restoreFocus) trigger?.focus();
        if (options.remove) menu.remove();
    }

    function fitDetailsMenuToViewport(menu) {
        menu.style.removeProperty('--popup-menu-max-height');
        if (!menu.closest('.game-storefront') || !window.matchMedia('(max-width: 768px)').matches) {
            return;
        }

        const bottomNavigation = document.querySelector('.mobile-bottom-nav');
        const bottomInset = bottomNavigation && getComputedStyle(bottomNavigation).display !== 'none'
            ? Math.max(24, window.innerHeight - bottomNavigation.getBoundingClientRect().top + 12)
            : 24;
        const availableHeight = Math.max(220, window.innerHeight - menu.getBoundingClientRect().top - bottomInset);
        menu.style.setProperty('--popup-menu-max-height', `${availableHeight}px`);
    }

    window.addEventListener('resize', () => {
        document.querySelectorAll('.game-storefront .popup-menu').forEach(menu => {
            if (menu.style.display === 'block') fitDetailsMenuToViewport(menu);
        });
    });

    // Adjusted for dynamic content using event delegation
    document.body.addEventListener('click', function(event) {
        if (event.target.classList.contains('refresh-game-metadata-updates')) {
            event.preventDefault();
            event.stopPropagation();
            const button = event.target;
            const gameUuid = button.getAttribute('data-game-uuid');
            const originalText = button.textContent;
            button.disabled = true;
            button.innerHTML = '<i class="fas fa-circle-notch fa-spin" aria-hidden="true"></i> Refreshing…';

            const popupMenu = document.getElementById(`popupMenu-${gameUuid}`);
            fetch(`/refresh_game_metadata_updates/${gameUuid}`, {
                method: 'POST',
                headers: CSRFUtils.getHeaders({
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest'
                }),
                body: JSON.stringify({})
            })
            .then(async response => {
                const data = await response.json();
                if (!response.ok) throw new Error(data.message || 'Refresh request failed');
                $.notify(data.message, 'success');
                if (popupMenu) popupMenu.style.display = 'none';
                setTimeout(() => window.location.reload(), 700);
            })
            .catch(error => {
                console.error('Metadata and updates refresh failed:', error);
                $.notify(error.message || 'Could not refresh metadata and updates.', 'error');
            })
            .finally(() => {
                button.disabled = false;
                button.textContent = originalText;
            });
            return;
        }

        // Handling deletion of a game (not from disk)
        if (event.target.classList.contains('delete-game')) {
            event.stopPropagation();
            const button = event.target;
            const gameUuid = event.target.getAttribute('data-game-uuid');
            if (pendingRemovals.has(gameUuid)) return;
            pendingRemovals.add(gameUuid);
            button.disabled = true;
            button.setAttribute('aria-busy', 'true');
            console.log(`Removing game from library UUID: ${gameUuid}`);

            fetch(`/delete_game/${gameUuid}`, {
                method: 'POST',
                headers: CSRFUtils.getHeaders({
                    'Content-Type': 'application/json'
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    console.log('Game removed successfully');
                    $.notify(data.message, "success");
                    
                    // Check if we're on game details page by looking for game-specific elements
                    const isGameDetailsPage = document.querySelector('.game-card-q1, .game-card-q2') !== null;
                    
                    if (isGameDetailsPage) {
                        // On game details page, redirect to library after a short delay to show the notification
                        setTimeout(() => {
                            window.location.href = '/library';
                        }, 1000);
                    } else {
                        // On library page, remove the game card with fade out animation
                        const gameCard = document.querySelector(`[data-game-uuid="${gameUuid}"]`).closest('.game-card-container');
                        if (gameCard) {
                            gameCard.style.transition = 'opacity 0.3s ease';
                            gameCard.style.opacity = '0';
                            setTimeout(() => {
                                gameCard.remove();
                                
                                // Check if this was the last game and show empty message if needed
                                const remainingCards = document.querySelectorAll('.game-card-container');
                                if (remainingCards.length === 0) {
                                    const container = document.querySelector('.game-library-container');
                                    if (container) {
                                        container.innerHTML = '<p>No games found in this library.</p>';
                                    }
                                }
                            }, 300);
                        }
                    }
                } else {
                    console.error('Error removing game:', data.message);
                    $.notify(data.message, "error");
                }
            })
            .catch(error => {
                console.error('There has been a problem with your fetch operation:', error);
                $.notify("An error occurred while removing the game.", "error");
            })
            .finally(() => {
                pendingRemovals.delete(gameUuid);
                button.disabled = false;
                button.removeAttribute('aria-busy');
            });
        }

        // Handling "Delete Game from Disk" with modal instead of alert
        if (event.target.classList.contains('delete-game-from-disk')) {
            event.preventDefault(); // Prevent any default action
            const gameUuid = event.target.getAttribute('data-game-uuid');
            console.log(`Preparing to delete from disk UUID: ${gameUuid}`);

            // Set the UUID in the modal's form hidden input
            document.getElementById('deleteGameUuid').value = gameUuid;
            // Display the modal
            document.getElementById('deleteGameModal').style.display = 'block';
        }

        // Handling Discord notification trigger
        if (event.target.classList.contains('trigger-discord-notification')) {
            event.stopPropagation();
            const gameUuid = event.target.getAttribute('data-game-uuid');
            console.log(`Triggering Discord notification for game UUID: ${gameUuid}`);

            // Disable the button to prevent double-clicks
            const button = event.target;
            const originalText = button.textContent;
            button.disabled = true;
            button.textContent = 'Sending...';

            fetch(`/trigger_discord_notification/${gameUuid}`, {
                method: 'POST',
                headers: CSRFUtils.getHeaders({ 'Content-Type': 'application/json' })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    button.textContent = 'Sent!';
                    $.notify(data.message || 'Discord notification sent.', 'success');
                    console.log('Discord notification sent successfully:', data.message);
                    
                    // Reset button after 2 seconds
                    setTimeout(() => {
                        button.textContent = originalText;
                        button.disabled = false;
                    }, 2000);
                } else {
                    button.textContent = 'Failed';
                    console.error('Failed to send Discord notification:', data.message);
                    $.notify(data.message || 'Failed to send Discord notification.', 'error');
                    
                    // Reset button after 2 seconds
                    setTimeout(() => {
                        button.textContent = originalText;
                        button.disabled = false;
                    }, 2000);
                }
            })
            .catch(error => {
                console.error('Error sending Discord notification:', error);
                button.textContent = 'Error';
                $.notify('An error occurred while sending the Discord notification.', 'error');
                
                // Reset button after 2 seconds
                setTimeout(() => {
                    button.textContent = originalText;
                    button.disabled = false;
                }, 2000);
            });
        }
    });

    let menuRequestSequence = 0;
    let pendingMenuTrigger = null;
    document.body.addEventListener('click', async function(event) {
        var clickedElement = event.target.closest('[id^="menuButton-"]');
        if (clickedElement) {
            console.log('Menu button or its child clicked');
            event.stopPropagation();

            if (pendingMenuTrigger === clickedElement) {
                ++menuRequestSequence;
                pendingMenuTrigger.removeAttribute('aria-busy');
                pendingMenuTrigger = null;
                return;
            }
            ++menuRequestSequence;
            pendingMenuTrigger?.removeAttribute('aria-busy');
            pendingMenuTrigger = null;

            var uuid = clickedElement.id.replace('menuButton-', '');
            var popupMenu = document.getElementById('popupMenu-' + uuid);
            if (!popupMenu && clickedElement.closest('#gamesContainer')) {
                const sequence = ++menuRequestSequence;
                pendingMenuTrigger = clickedElement;
                clickedElement.setAttribute('aria-busy', 'true');
                try {
                    const response = await fetch(`/library/game-actions/${encodeURIComponent(uuid)}`);
                    if (!response.ok) throw new Error('Game actions could not be loaded.');
                    const html = await response.text();
                    if (sequence !== menuRequestSequence || !clickedElement.isConnected) return;
                    document.querySelectorAll('#gamesContainer .popup-menu').forEach(menu => closeMenu(menu, { remove: true }));
                    clickedElement.closest('.game-card').insertAdjacentHTML('beforeend', html);
                    popupMenu = document.getElementById('popupMenu-' + uuid);
                } catch (error) {
                    if (sequence !== menuRequestSequence) return;
                    $.notify(error.message, 'error');
                    return;
                } finally {
                    if (sequence === menuRequestSequence) {
                        clickedElement.removeAttribute('aria-busy');
                        pendingMenuTrigger = null;
                    }
                }
            }
            if (!popupMenu) return;


            // Handle both library page (.game-card) and game details page (.game-card-coverimage)
            var gameCard = clickedElement.closest('.game-card');
            var coverImage = clickedElement.closest('.game-card-coverimage');
            var parentContainer = gameCard || coverImage;

            document.querySelectorAll('.popup-menu').forEach(function(menu) {
                if (menu.id !== 'popupMenu-' + uuid) {
                    closeMenu(menu);
                }
            });

            // Close any open screenshot slideshows when opening popup menu
            if (typeof hideDetails === 'function') {
                hideDetails();
            }

            // Toggle the popup menu
            var isOpening = popupMenu.style.display !== 'block';
            popupMenu.style.display = isOpening ? 'block' : 'none';
            clickedElement.setAttribute('aria-expanded', String(isOpening));
            parentContainer.classList.toggle('menu-open', isOpening);
            var cardContainer = parentContainer.closest('.game-card-container');
            if (cardContainer) cardContainer.classList.toggle('menu-open', isOpening);

            // Hide or show the favorite button and game status elements
            if (isOpening) {
                popupMenu.scrollTop = 0;
                fitDetailsMenuToViewport(popupMenu);
                hideCardButtons(parentContainer);
                popupMenu.querySelector('button:not([disabled]), a')?.focus();
            } else {
                closeMenu(popupMenu);
            }
        }
    });

    document.addEventListener('keydown', event => {
        if (event.key !== 'Escape') return;
        if (pendingMenuTrigger) {
            event.preventDefault();
            ++menuRequestSequence;
            pendingMenuTrigger.removeAttribute('aria-busy');
            pendingMenuTrigger.focus();
            pendingMenuTrigger = null;
        }
        const menu = event.target.closest('.popup-menu');
        if (!menu) return;
        if (event.key === 'Escape') {
            event.preventDefault();
            closeMenu(menu, { restoreFocus: true });
        }
    });

    // Handle "Move Library" button click
    document.body.addEventListener('click', function(event) {
        if (event.target.classList.contains('move-library')) {
            event.stopPropagation();
            
            const gameUuid = event.target.getAttribute('data-game-uuid');
            const submenuContainer = event.target.closest('.move-library-container').querySelector('.submenu-libraries');
            
            // Close any other open libraries submenu
            if (currentLibrariesSubmenu && currentLibrariesSubmenu !== submenuContainer) {
                currentLibrariesSubmenu.style.display = 'none';
            }
            
            // Toggle the submenu
            if (submenuContainer.style.display === 'none') {
                submenuContainer.style.display = 'block';
                currentLibrariesSubmenu = submenuContainer;
                
                // Show loading indicator
                const loadingElement = submenuContainer.querySelector('.loading-libraries');
                const librariesList = submenuContainer.querySelector('.libraries-list');
                loadingElement.style.display = 'block';
                librariesList.style.display = 'none';
                
                // Fetch libraries
                fetch('/api/get_libraries')
                    .then(response => response.json())
                    .then(libraries => {
                        // Hide loading, show libraries list
                        loadingElement.style.display = 'none';
                        librariesList.style.display = 'block';
                        
                        // Clear previous libraries
                        librariesList.innerHTML = '';
                        
                        // Add libraries to the submenu
                        libraries.forEach(library => {
                            const libraryItem = document.createElement('button');
                            libraryItem.type = 'button';
                            libraryItem.className = 'library-item menu-button';
                            libraryItem.textContent = library.name;
                            libraryItem.setAttribute('data-library-uuid', library.uuid);
                            libraryItem.setAttribute('data-game-uuid', gameUuid);
                            
                            libraryItem.addEventListener('click', function(e) {
                                e.stopPropagation();
                                const targetLibraryUuid = this.getAttribute('data-library-uuid');
                                const gameUuid = this.getAttribute('data-game-uuid');
                                
                                // Confirm with the user
                                if (confirm(`Are you sure you want to move this game to the "${library.name}" library?`)) {
                                    libraryItem.disabled = true;
                                    libraryItem.setAttribute('aria-busy', 'true');
                                    // Send request to move the game
                                    fetch('/api/move_game_to_library', {
                                        method: 'POST',
                                        headers: CSRFUtils.getHeaders({ 'Content-Type': 'application/json' }),
                                        body: JSON.stringify({
                                            game_uuid: gameUuid,
                                            target_library_uuid: targetLibraryUuid
                                        })
                                    })
                                    .then(response => response.json())
                                    .then(data => {
                                        if (data.success) {
                                            window.location.reload();
                                        } else {
                                            $.notify(data.message || 'Could not move the game.', 'error');
                                        }
                                    })
                                    .catch(error => {
                                        console.error('Error moving game:', error);
                                        $.notify('An error occurred while moving the game.', 'error');
                                    })
                                    .finally(() => {
                                        libraryItem.disabled = false;
                                        libraryItem.removeAttribute('aria-busy');
                                    });
                                }
                            });
                            librariesList.appendChild(libraryItem);
                        });
                    })
                    .catch(() => {
                        loadingElement.style.display = 'none';
                        $.notify('Unable to load libraries. Close and reopen Move Library to retry.', 'error');
                    });
            } else {
                submenuContainer.style.display = 'none';
                currentLibrariesSubmenu = null;
            }
        }
    });

    // Helper functions to hide/show card buttons
    function hideCardButtons(gameCard) {
        if (!gameCard) return;

        // Handle library page buttons
        var favoriteBtn = gameCard.querySelector('.favorite-btn');
        var statusBtn = gameCard.querySelector('.game-status-btn');
        var statusBadge = gameCard.querySelector('.game-status-badge');
        var statusDropdown = gameCard.querySelector('.status-dropdown');

        // Handle game details page buttons (with -cover suffix)
        var favoriteBtnCover = gameCard.querySelector('.favorite-btn-cover');
        var statusBtnCover = gameCard.querySelector('.game-status-btn-cover');

        if (favoriteBtn) favoriteBtn.style.display = 'none';
        if (statusBtn) statusBtn.style.display = 'none';
        if (statusBadge) statusBadge.style.display = 'none';
        if (statusDropdown) statusDropdown.style.display = 'none';
        if (favoriteBtnCover) favoriteBtnCover.style.display = 'none';
        if (statusBtnCover) statusBtnCover.style.display = 'none';
    }

    function showCardButtons(gameCard) {
        if (!gameCard) return;

        // Handle library page buttons
        var favoriteBtn = gameCard.querySelector('.favorite-btn');
        var statusBtn = gameCard.querySelector('.game-status-btn');
        var statusBadge = gameCard.querySelector('.game-status-badge');

        // Handle game details page buttons (with -cover suffix)
        var favoriteBtnCover = gameCard.querySelector('.favorite-btn-cover');
        var statusBtnCover = gameCard.querySelector('.game-status-btn-cover');

        if (favoriteBtn) favoriteBtn.style.display = '';
        if (statusBtn) statusBtn.style.display = '';
        if (statusBadge) statusBadge.style.display = '';
        if (favoriteBtnCover) favoriteBtnCover.style.display = '';
        if (statusBtnCover) statusBtnCover.style.display = '';
        // Note: status dropdown should remain hidden unless explicitly opened by user
    }

    window.addEventListener('click', function() {
        ++menuRequestSequence;
        pendingMenuTrigger?.removeAttribute('aria-busy');
        pendingMenuTrigger = null;
        document.querySelectorAll('.popup-menu').forEach(function(menu) {
            closeMenu(menu);
        });

        // Also close any open libraries submenu
        if (currentLibrariesSubmenu) {
            currentLibrariesSubmenu.style.display = 'none';
            currentLibrariesSubmenu = null;
        }
    });

    document.body.addEventListener('click', function(event) {
        if (event.target.closest('.popup-menu')) {
            event.stopPropagation();
        }
    });

});
