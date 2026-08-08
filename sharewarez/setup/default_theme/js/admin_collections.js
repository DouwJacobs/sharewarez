document.addEventListener('DOMContentLoaded', () => {
    const editor = document.querySelector('[data-collection-editor]');
    if (!editor) return;

    const orderInput = editor.querySelector('[name="game_order"]');
    const searchInput = editor.querySelector('[data-game-search]');
    const results = editor.querySelector('[data-search-results]');
    const selectedList = editor.querySelector('[data-selected-list]');
    const emptyState = editor.querySelector('[data-selected-empty]');
    const count = editor.querySelector('[data-selected-count]');
    const spinner = editor.querySelector('[data-search-spinner]');
    let searchTimer;
    let searchController;

    const selectedRows = () => [...selectedList.querySelectorAll('[data-game-uuid]')];
    const sync = () => {
        const rows = selectedRows();
        orderInput.value = rows.map(row => row.dataset.gameUuid).join(',');
        count.textContent = rows.length;
        emptyState.hidden = rows.length > 0;
    };

    const makeAction = (icon, label, attribute) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.setAttribute(attribute, '');
        button.setAttribute('aria-label', label);
        const iconNode = document.createElement('i');
        iconNode.className = `fas ${icon}`;
        button.append(iconNode);
        return button;
    };

    const addGame = (game) => {
        if (selectedList.querySelector(`[data-game-uuid="${CSS.escape(game.uuid)}"]`)) return;
        const row = document.createElement('div');
        row.className = 'collection-selected-game';
        row.dataset.gameUuid = game.uuid;
        row.dataset.gameName = game.name;
        const handle = document.createElement('span');
        handle.className = 'collection-drag-handle';
        handle.innerHTML = '<i class="fas fa-grip-vertical" aria-hidden="true"></i>';
        const name = document.createElement('span');
        name.className = 'collection-game-name';
        name.textContent = game.name;
        const actions = document.createElement('span');
        actions.className = 'collection-order-actions';
        actions.append(
            makeAction('fa-chevron-up', `Move ${game.name} up`, 'data-move-up'),
            makeAction('fa-chevron-down', `Move ${game.name} down`, 'data-move-down'),
            makeAction('fa-times', `Remove ${game.name}`, 'data-remove')
        );
        row.append(handle, name, actions);
        selectedList.insertBefore(row, emptyState);
        sync();
    };

    selectedList.addEventListener('click', event => {
        const button = event.target.closest('button');
        const row = event.target.closest('[data-game-uuid]');
        if (!button || !row) return;
        if (button.matches('[data-remove]')) row.remove();
        if (button.matches('[data-move="up"], [data-move-up]')) {
            const previous = row.previousElementSibling;
            if (previous?.matches('[data-game-uuid]')) selectedList.insertBefore(row, previous);
        }
        if (button.matches('[data-move="down"], [data-move-down]')) {
            const next = row.nextElementSibling;
            if (next?.matches('[data-game-uuid]')) selectedList.insertBefore(next, row);
        }
        sync();
    });

    const renderResults = games => {
        results.replaceChildren();
        const selected = new Set(selectedRows().map(row => row.dataset.gameUuid));
        games.forEach(game => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'collection-search-result';
            button.disabled = selected.has(game.uuid);
            const label = document.createElement('span');
            label.textContent = game.name;
            const action = document.createElement('span');
            action.textContent = button.disabled ? 'Added' : 'Add';
            button.append(label, action);
            button.addEventListener('click', () => {
                addGame(game);
                button.disabled = true;
                action.textContent = 'Added';
            });
            results.append(button);
        });
        if (!games.length) {
            const message = document.createElement('div');
            message.className = 'collection-search-result';
            message.textContent = 'No matching games found.';
            results.append(message);
        }
        results.hidden = false;
    };

    const search = async () => {
        searchController?.abort();
        searchController = new AbortController();
        spinner.hidden = false;
        try {
            const url = new URL(editor.dataset.searchUrl, window.location.origin);
            url.searchParams.set('q', searchInput.value.trim());
            const response = await fetch(url, { signal: searchController.signal, headers: { Accept: 'application/json' } });
            if (!response.ok) throw new Error('Search failed');
            renderResults((await response.json()).games || []);
        } catch (error) {
            if (error.name !== 'AbortError') renderResults([]);
        } finally {
            spinner.hidden = true;
        }
    };

    searchInput.addEventListener('input', () => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(search, 220);
    });
    searchInput.addEventListener('focus', () => { if (results.hidden) search(); });
    document.addEventListener('click', event => {
        if (!event.target.closest('.collection-game-picker')) results.hidden = true;
    });
    editor.addEventListener('submit', sync);
    sync();
});
