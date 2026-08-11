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

    let dragState = null;

    selectedList.addEventListener('pointerdown', event => {
        const handle = event.target.closest('.collection-drag-handle');
        const row = handle?.closest('.collection-selected-game');
        if (!row) return;
        event.preventDefault();
        const rowRect = row.getBoundingClientRect();
        dragState = {
            handle,
            row,
            pointerId: event.pointerId,
            startX: event.clientX,
            startY: event.clientY,
            offsetX: event.clientX - rowRect.left,
            offsetY: event.clientY - rowRect.top,
            width: rowRect.width,
            height: rowRect.height,
            preview: null,
            moved: false
        };
        try {
            handle.setPointerCapture?.(event.pointerId);
        } catch (_error) {
            // Pointer capture can be unavailable in older embedded browsers.
        }
        row.classList.add('collection-sortable-chosen');
    });

    selectedList.addEventListener('pointermove', event => {
        if (!dragState || event.pointerId !== dragState.pointerId) return;
        if (!dragState.moved && Math.hypot(
            event.clientX - dragState.startX,
            event.clientY - dragState.startY
        ) < 5) return;
        event.preventDefault();

        if (!dragState.moved) {
            dragState.moved = true;
            dragState.preview = dragState.row.cloneNode(true);
            dragState.preview.classList.remove('collection-sortable-chosen');
            dragState.preview.classList.add('collection-sortable-preview');
            dragState.preview.setAttribute('aria-hidden', 'true');
            dragState.preview.style.width = `${dragState.width}px`;
            dragState.preview.style.height = `${dragState.height}px`;
            document.body.append(dragState.preview);
        }

        dragState.preview.style.left = `${event.clientX - dragState.offsetX}px`;
        dragState.preview.style.top = `${event.clientY - dragState.offsetY}px`;

        const target = document.elementFromPoint(event.clientX, event.clientY)
            ?.closest('.collection-selected-game');
        if (!target || target === dragState.row || !selectedList.contains(target)) return;

        const targetRect = target.getBoundingClientRect();
        const insertBeforeTarget = event.clientY < targetRect.top + (targetRect.height / 2);
        selectedList.insertBefore(
            dragState.row,
            insertBeforeTarget ? target : target.nextElementSibling
        );
    });

    const finishDrag = event => {
        if (!dragState || event.pointerId !== dragState.pointerId) return;
        dragState.row.classList.remove('collection-sortable-chosen');
        dragState.preview?.remove();
        try {
            if (dragState.handle.hasPointerCapture?.(event.pointerId)) {
                dragState.handle.releasePointerCapture(event.pointerId);
            }
        } catch (_error) {
            // The pointer may already have been released by the browser.
        }
        const orderChanged = dragState.moved;
        dragState = null;
        if (orderChanged) sync();
    };

    selectedList.addEventListener('pointerup', finishDrag);
    selectedList.addEventListener('pointercancel', finishDrag);

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
        handle.title = `Drag to reorder ${game.name}`;
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
