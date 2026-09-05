let currentLibrariesSubmenu = null;
function setCookie(name, value, days) {
    try {
        var expires = "";
        if (days) {
            var date = new Date();
            date.setTime(date.getTime() + (days * 24 * 60 * 60 * 1000));
            expires = "; expires=" + date.toUTCString();
        }
        const safeValue = JSON.stringify(value);
        document.cookie = `${name}=${encodeURIComponent(safeValue)}${expires}; path=/`;
        console.log(`Cookie set successfully: ${name}`);
    } catch (e) {
        console.error('Error setting cookie:', e);
    }
}

function getCookie(name) {
    try {
        const nameEQ = name + "=";
        const ca = document.cookie.split(';');
        for (let i = 0; i < ca.length; i++) {
            let c = ca[i];
            while (c.charAt(0) === ' ') {
                c = c.substring(1);
            }
            if (c.indexOf(nameEQ) === 0) {
                const encodedValue = c.substring(nameEQ.length);
                const decodedValue = decodeURIComponent(encodedValue);
                try {
                    return JSON.parse(decodedValue);
                } catch (parseError) {
                    console.error('Error parsing cookie value:', parseError);
                    deleteCookie(name);
                    return null;
                }
            }
        }
    } catch (e) {
        console.error('Error reading cookie:', e);
        return null;
    }
    return null;
}
function deleteCookie(name) {
    document.cookie = name + '=; Path=/; Expires=Thu, 01 Jan 1970 00:00:01 GMT;';
}
var csrfToken;
var sortOrder = 'asc'; 
$('#sortOrderToggle').html(sortOrder === 'asc' ? '<i class="fas fa-sort-up"></i>' : '<i class="fas fa-sort-down"></i>');
$(document).ready(function() {
    // Get server-rendered filter data
    var currentFilters = {};
    var currentPageFromServer = 1;
    var totalPagesFromServer = 0;
    
    try {
        var filtersData = $('body').data('current-filters');
        currentFilters = filtersData || {};
        currentPageFromServer = $('body').data('current-page') || 1;
        totalPagesFromServer = $('body').data('total-pages') || 0;
        console.log('Server-provided filters:', currentFilters);
        console.log('Server pagination:', currentPageFromServer, '/', totalPagesFromServer);
    } catch (e) {
        console.error('Error reading server filter data:', e);
    }
    
    var userPerPage = $('body').data('user-per-page');
    var userDefaultSort = $('body').data('user-default-sort');
    var userDefaultSortOrder = $('body').data('user-default-sort-order');
    console.log("User preferences:", userPerPage, userDefaultSort, userDefaultSortOrder);
    
    // Initialize pagination from server data
    var currentPage = currentPageFromServer;
    var totalPages = totalPagesFromServer;
    var activeGamesRequest = null;
    var gamesRequestSequence = 0;
    
    // Initialize pagination display
    if (totalPages > 0) {
        $('#currentPageInfo, #currentPageInfoBottom').text(currentPage + '/' + totalPages);
        updatePaginationControls();
    }
    csrfToken = CSRFUtils.getToken();
    if (userPerPage) {
        $('#perPageSelect').val(userPerPage.toString());
    }
    if (userDefaultSort) {
        $('#sortSelect').val(userDefaultSort);
    }
    sortOrder = userDefaultSortOrder || 'asc';
    $('#sortOrderToggle').html(sortOrder === 'asc' ? '<i class="fas fa-sort-up"></i>' : '<i class="fas fa-sort-down"></i>');

    function populateDropdown(options) {
        const { apiUrl, elementId, defaultText, valueField, textField, paramName, callback } = options;
        return $.ajax({
            url: apiUrl,
            method: 'GET',
            success: function(response) {
                const selectElement = $(elementId);
                selectElement.empty().append($('<option>', { value: '', text: defaultText }));
                response.forEach(function(item) {
                    selectElement.append($('<option>', {
                        value: item[valueField],
                        text: item[textField]
                    }));
                });
                if (typeof callback === "function") {
                    callback();
                }
            },
            error: function(xhr, status, error) {
                console.error(`Error fetching data for ${elementId}:`, error);
            }
        }).done(function() {
            if (paramName) {
                const initialParams = currentFilters;
                if (initialParams[paramName]) {
                    $(elementId).val(initialParams[paramName]);
                }
            }
        });
    }

    function populateLibraries(callback) {
        return populateDropdown({
            apiUrl: '/api/get_libraries',
            elementId: '#libraryNameSelect',
            defaultText: 'All Libraries',
            valueField: 'uuid',
            textField: 'name',
            paramName: 'library_uuid',
            callback: callback
        }).done(function() {
            // Skip initial fetchFilteredGames() - server already rendered correct games
            console.log('Libraries populated, skipping initial fetch since server already rendered filtered games');
        });
    }

    function populateGenres(callback) {
        return populateDropdown({
            apiUrl: '/api/genres',
            elementId: '#genreSelect',
            defaultText: 'All Genres',
            valueField: 'name',
            textField: 'name',
            paramName: 'genre',
            callback: callback
        });
    }

    function populateCollections(callback) {
        return populateDropdown({
            apiUrl: '/api/collections',
            elementId: '#collectionSelect',
            defaultText: 'All Collections',
            valueField: 'slug',
            textField: 'name',
            paramName: 'collection',
            callback: callback
        });
    }

    function populateGameModes(callback) {
        return populateDropdown({
            apiUrl: '/api/game_modes',
            elementId: '#gameModeSelect',
            defaultText: 'All Game Modes',
            valueField: 'name',
            textField: 'name',
            paramName: 'game_mode',
            callback: callback
        });
    }

    function populatePlayerPerspectives(callback) {
        return populateDropdown({
            apiUrl: '/api/player_perspectives',
            elementId: '#playerPerspectiveSelect',
            defaultText: 'All Perspectives',
            valueField: 'name',
            textField: 'name',
            paramName: 'player_perspective',
            callback: callback
        });
    }

    function populateThemes(callback) {
        return populateDropdown({
            apiUrl: '/api/themes',
            elementId: '#themeSelect',
            defaultText: 'All Themes',
            valueField: 'name',
            textField: 'name',
            paramName: 'theme',
            callback: callback
        });
    }

    function populateTags(callback) {
        return populateDropdown({
            apiUrl: '/api/tags',
            elementId: '#tagSelect',
            defaultText: 'All Tags',
            valueField: 'name',
            textField: 'name',
            paramName: 'tag',
            callback: callback
        });
    }

    function getUrlParams() {
        return Object.fromEntries(new URLSearchParams(window.location.search));
    }

    function fetchFilteredGames(page) {
        var urlParams = getUrlParams(); 
        page = page || urlParams.page || 1; 
        var filters = {
            library_uuid: $('#libraryNameSelect').val() || undefined,
            collection: $('#collectionSelect').val() || undefined,
            family: urlParams.family || undefined,
            page: page,
            filters: '1',
            render: 'html',
            per_page: $('#perPageSelect').val() || 20,
            category: $('#categorySelect').val() || urlParams.category,
            genre: $('#genreSelect').val() || undefined,
            game_mode: $('#gameModeSelect').val() || undefined,
            player_perspective: $('#playerPerspectiveSelect').val() || undefined,
            theme: $('#themeSelect').val() || undefined,
            tag: $('#tagSelect').val() || undefined,
            rating: $('#ratingSlider').val() !== '0' ? $('#ratingSlider').val() : undefined, 
            sort_by: $('#sortSelect').val(),
            sort_order: sortOrder,
        };
        console.log("Fetching games with filters:", filters);
        var queryString = $.param(filters);
        console.log(`Full query URL: /browse_games?${queryString}`);

        if (activeGamesRequest) {
            activeGamesRequest.abort();
        }
        const requestSequence = ++gamesRequestSequence;
        const paginationButtons = $('#firstPage, #firstPageBottom, #prevPage, #prevPageBottom, #nextPage, #nextPageBottom, #lastPage, #lastPageBottom');
        paginationButtons.prop('disabled', true);
        const skeletonCards = Array.from({length: 8}, () => `
            <div class="game-card-skeleton" aria-hidden="true">
                <span class="app-skeleton game-card-skeleton-cover"></span>
                <span class="app-skeleton game-card-skeleton-line is-title"></span>
                <span class="app-skeleton game-card-skeleton-line"></span>
            </div>`).join('');
        $('#gamesContainer').attr('aria-busy', 'true').html(`<div class="sr-only" role="status">Loading games…</div>${skeletonCards}`);
        activeGamesRequest = $.ajax({
            url: '/browse_games',
            data: filters,
            method: 'GET',
            timeout: 20000,
            success: function(response) {
                if (requestSequence !== gamesRequestSequence) return;
                totalPages = response.pages;
                currentPage = response.current_page;
                $('#currentPageInfo, #currentPageInfoBottom').text(currentPage + '/' + totalPages);
                $('#gamesContainer').html(response.html);
                $('#libraryFilterChips').html(response.chips_html);
                $('.library-browser-count').text(`${response.total} ${response.total === 1 ? 'game' : 'games'}`);
                const nextParams = new URLSearchParams();
                Object.entries(filters).forEach(([key, value]) => {
                    if (key !== 'render' && value !== undefined && value !== '') nextParams.set(key, value);
                });
                nextParams.set('page', currentPage);
                const view = document.querySelector('[data-library-view][aria-pressed="true"]')?.dataset.libraryView;
                if (view) nextParams.set('view', view);
                window.history.pushState({}, '', `/library?${nextParams}`);
                setCookie('libraryFilters', filters, 30);
                updatePaginationControls();
            },
            error: function(xhr, status, error) {
                if (status === 'abort' || requestSequence !== gamesRequestSequence) return;
                console.error("AJAX error:", error);
                const message = status === 'timeout' ? 'The library request timed out. Try a smaller page size or narrower filter.' : 'Games could not be loaded. Please try again.';
                $('#gamesContainer').html(`<div class="game-grid-empty game-grid-error" role="alert"><i class="fas fa-triangle-exclamation" aria-hidden="true"></i><p>${message}</p><button type="button" class="btn btn-secondary" id="retryGamesRequest">Retry</button></div>`);
                $('#retryGamesRequest').on('click', function() { fetchFilteredGames(currentPage); });
            },
            complete: function() {
                if (requestSequence !== gamesRequestSequence) return;
                activeGamesRequest = null;
                $('#gamesContainer').attr('aria-busy', 'false');
                updatePaginationControls();
            }
        });
    }

    $('#sortOrderToggle').click(function() {
        sortOrder = sortOrder === 'asc' ? 'desc' : 'asc';
        $(this).html(sortOrder === 'asc' ? '<i class="fas fa-sort-up"></i>' : '<i class="fas fa-sort-down"></i>'); 
        console.log('sortOrderToggle clicked, new sort order:', sortOrder);
        fetchFilteredGames(currentPage);
    });

    function updatePaginationControls() {
        // Update top pagination controls
        $('#firstPage, #firstPageBottom').prop('disabled', currentPage <= 1);
        $('#prevPage, #prevPageBottom').prop('disabled', currentPage <= 1);
        $('#nextPage, #nextPageBottom').prop('disabled', currentPage >= totalPages);
        $('#lastPage, #lastPageBottom').prop('disabled', currentPage >= totalPages);

        // Legacy support for old pagination
        $('#prevPage').parent().toggleClass('disabled', currentPage <= 1);
        $('#nextPage').parent().toggleClass('disabled', currentPage >= totalPages);
    }

    $('#perPageSelect').change(function() {
        fetchFilteredGames(1);
        console.log('perPageSelect changed to ' + $(this).val());
    });

    // First page handlers
    $('#firstPage, #firstPageBottom').click(function(e) {
        e.preventDefault();
        if (currentPage > 1) {
            currentPage = 1;
            fetchFilteredGames(currentPage);
        }
    });

    // Previous page handlers
    $('#prevPage, #prevPageBottom').click(function(e) {
        e.preventDefault();
        if (currentPage > 1) {
            fetchFilteredGames(--currentPage);
        }
    });

    // Next page handlers
    $('#nextPage, #nextPageBottom').click(function(e) {
        e.preventDefault();
        if (currentPage < totalPages) {
            fetchFilteredGames(++currentPage);
        }
    });

    // Last page handlers
    $('#lastPage, #lastPageBottom').click(function(e) {
        e.preventDefault();
        if (currentPage < totalPages) {
            currentPage = totalPages;
            fetchFilteredGames(currentPage);
        }
    });

    $('#filterForm').on('submit', function(e) {
        e.preventDefault();
        var filters = {
            library_uuid: $('#libraryNameSelect').val(),
            collection: $('#collectionSelect').val(),
            genre: $('#genreSelect').val(),
            theme: $('#themeSelect').val(),
            tag: $('#tagSelect').val(),
            game_mode: $('#gameModeSelect').val(),
            player_perspective: $('#playerPerspectiveSelect').val(),
            rating: $('#ratingSlider').val()
        };
        console.log('Saving filters to cookie:', filters);
        setCookie('libraryFilters', filters, 30);
        fetchFilteredGames(1);
    });

    $('#ratingSlider').on('input', function() {
        $('#ratingValue').text($(this).val());
    });

    $('#clearFilters').click(function() {
        $('#libraryNameSelect, #collectionSelect, #genreSelect, #themeSelect, #tagSelect, #gameModeSelect, #playerPerspectiveSelect').val('');
        $('#ratingSlider').val(0);
        $('#ratingValue').text('0');
        $('#sortSelect').val('name');
        deleteCookie('libraryFilters');
        const clearedUrl = new URL(window.location.href);
        clearedUrl.searchParams.delete('family');
        clearedUrl.searchParams.delete('category');
        window.history.replaceState({}, '', clearedUrl);
        fetchFilteredGames(1);
    });

    $('#sortSelect').change(function() {
        fetchFilteredGames(currentPage);
    });

    $('#ratingSlider').val(currentFilters.rating || 0);
    $('#ratingValue').text(currentFilters.rating || 0);
    // All option lists are independent; populate them concurrently using the
    // server's canonical filters rather than restoring stale cookie state.
    populateLibraries();
    populateCollections();
    populateGenres();
    populateThemes();
    populateTags();
    populateGameModes();
    populatePlayerPerspectives();
    window.addEventListener('popstate', () => window.location.reload());
});

document.body.addEventListener('click', function(event) {
    if (event.target.classList.contains('refresh-game-images')) {
        event.preventDefault();
        const gameUuid = event.target.getAttribute('data-game-uuid');
        console.log(`Refreshing images for game UUID: ${gameUuid}`);

        // Close the popup menu
        const popupMenu = document.getElementById(`popupMenu-${gameUuid}`);
        if (popupMenu) {
            popupMenu.style.display = 'none';
        }

        fetch(`/refresh_game_images/${gameUuid}`, {
            method: 'POST',
            headers: CSRFUtils.getHeaders({ 
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            }),
            body: JSON.stringify({ /*  */ })
        })
        .then(response => {
            console.log('Response status:', response.status);
            if (!response.ok) {
                throw new Error(`Network response was not ok, status: ${response.status}`);
            }
            return response.text().then(text => {
                try {
                    return JSON.parse(text);
                } catch (error) {
                    console.error('Error parsing JSON:', error);
                    console.log('Raw text response:', text);
                    throw new Error('Failed to parse JSON');
                }
            });
        })
        .then(data => {
            console.log('Game images refreshed successfully', data);
            if (data.message) {
                $.notify(data.message, "success");
            }
        })
        .catch(error => {
            console.error('There has been a problem with your fetch operation:', error);
            $.notify("An error occurred while refreshing game images.", "error");
        });
    }

});

// Helper functions to hide/show card buttons (shared with popup_menu.js functionality)
function hideCardButtons(gameCard) {
    if (!gameCard) return;

    var favoriteBtn = gameCard.querySelector('.favorite-btn');
    var statusBtn = gameCard.querySelector('.game-status-btn');
    var statusBadge = gameCard.querySelector('.game-status-badge');
    var statusDropdown = gameCard.querySelector('.status-dropdown');

    if (favoriteBtn) favoriteBtn.style.display = 'none';
    if (statusBtn) statusBtn.style.display = 'none';
    if (statusBadge) statusBadge.style.display = 'none';
    if (statusDropdown) statusDropdown.style.display = 'none';
}

function showCardButtons(gameCard) {
    if (!gameCard) return;

    var favoriteBtn = gameCard.querySelector('.favorite-btn');
    var statusBtn = gameCard.querySelector('.game-status-btn');
    var statusBadge = gameCard.querySelector('.game-status-badge');

    if (favoriteBtn) favoriteBtn.style.display = '';
    if (statusBtn) statusBtn.style.display = '';
    if (statusBadge) statusBadge.style.display = '';
    // Note: status dropdown should remain hidden unless explicitly opened by user
}

window.addEventListener('click', function() {
    document.querySelectorAll('.popup-menu').forEach(function(menu) {
        menu.style.display = 'none';
        // Show favorite button and game status elements when menu closes
        var gameCard = menu.closest('.game-card');
        if (gameCard) {
            gameCard.classList.remove('menu-open');
            var cardContainer = gameCard.closest('.game-card-container');
            if (cardContainer) cardContainer.classList.remove('menu-open');
            showCardButtons(gameCard);
        }
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
