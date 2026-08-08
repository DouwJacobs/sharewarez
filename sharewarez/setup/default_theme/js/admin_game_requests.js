document.addEventListener('DOMContentLoaded', () => {
    const escapeHtml = value => String(value ?? '').replace(/[&<>'"]/g, character => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
    }[character]));

    const requestFilterForm = document.getElementById('adminRequestSearchForm');
    const requestFilterInput = document.getElementById('requestAdminSearch');
    if (requestFilterForm && requestFilterInput) {
        let filterTimer;
        const requestFilterWrap = requestFilterInput.closest('.request-search-wrap');
        const showFiltering = () => {
            requestFilterWrap.classList.add('is-loading');
            const icon = requestFilterWrap.querySelector('i');
            if (icon) icon.className = 'fas fa-circle-notch fa-spin';
        };
        requestFilterInput.addEventListener('input', () => {
            clearTimeout(filterTimer);
            showFiltering();
            filterTimer = setTimeout(() => requestFilterForm.requestSubmit(), 350);
        });
        requestFilterForm.addEventListener('submit', showFiltering);
        document.getElementById('requestSort')?.addEventListener('change', () => requestFilterForm.requestSubmit());
    }

    document.querySelectorAll('.admin-request-form').forEach(form => {
        const statusSelect = form.querySelector('select[name="status"]');
        const fulfilledPicker = form.querySelector('[data-fulfilled-picker]');
        if (!statusSelect || !fulfilledPicker) return;
        const searchInput = fulfilledPicker.querySelector('.library-game-search');
        const uuidInput = fulfilledPicker.querySelector('input[name="fulfilled_game_uuid"]');
        const syncFulfillment = () => {
            const isFulfilled = statusSelect.value === 'fulfilled';
            fulfilledPicker.hidden = !isFulfilled;
            searchInput.disabled = !isFulfilled;
            uuidInput.disabled = !isFulfilled;
            searchInput.required = isFulfilled;
            if (!isFulfilled) fulfilledPicker.querySelector('.library-game-results')?.classList.remove('open');
        };
        statusSelect.addEventListener('change', syncFulfillment);
        syncFulfillment();
    });

    document.querySelectorAll('.library-game-picker').forEach(picker => {
        const searchInput = picker.querySelector('.library-game-search');
        const uuidInput = picker.querySelector('input[name="fulfilled_game_uuid"]');
        const resultList = picker.querySelector('.library-game-results');
        let timer;
        let controller;

        const closeResults = () => {
            resultList.classList.remove('open');
            searchInput.setAttribute('aria-expanded', 'false');
        };

        const showMessage = message => {
            resultList.innerHTML = `<span class="library-game-empty">${escapeHtml(message)}</span>`;
            resultList.classList.add('open');
            searchInput.setAttribute('aria-expanded', 'true');
        };

        searchInput.addEventListener('input', () => {
            uuidInput.value = '';
            clearTimeout(timer);
            controller?.abort();
            const term = searchInput.value.trim();
            if (term.length < 2) {
                closeResults();
                return;
            }

            timer = setTimeout(async () => {
                controller = new AbortController();
                showMessage('Searching…');
                try {
                    const response = await fetch(`/api/requests/library-games?q=${encodeURIComponent(term)}`, {
                        signal: controller.signal
                    });
                    if (!response.ok) throw new Error('Library search failed.');
                    const data = await response.json();
                    if (!data.results.length) {
                        showMessage('No matching games found.');
                        return;
                    }
                    resultList.innerHTML = data.results.map(game => `
                        <button type="button" class="library-game-option" role="option"
                                data-uuid="${escapeHtml(game.uuid)}" data-name="${escapeHtml(game.name)}">
                            <span>${escapeHtml(game.name)}</span>
                            ${game.version ? `<small>v${escapeHtml(game.version)}</small>` : ''}
                        </button>
                    `).join('');
                    resultList.classList.add('open');
                    searchInput.setAttribute('aria-expanded', 'true');
                } catch (error) {
                    if (error.name !== 'AbortError') showMessage(error.message);
                }
            }, 250);
        });

        resultList.addEventListener('click', event => {
            const option = event.target.closest('.library-game-option');
            if (!option) return;
            searchInput.value = option.dataset.name;
            uuidInput.value = option.dataset.uuid;
            closeResults();
        });

        searchInput.addEventListener('keydown', event => {
            const options = [...resultList.querySelectorAll('.library-game-option')];
            if (!options.length || !['ArrowDown', 'ArrowUp'].includes(event.key)) return;
            event.preventDefault();
            (event.key === 'ArrowDown' ? options[0] : options.at(-1)).focus();
        });

        resultList.addEventListener('keydown', event => {
            const options = [...resultList.querySelectorAll('.library-game-option')];
            const index = options.indexOf(document.activeElement);
            if (index < 0 || !['ArrowDown', 'ArrowUp', 'Escape'].includes(event.key)) return;
            event.preventDefault();
            if (event.key === 'Escape') {
                closeResults();
                searchInput.focus();
                return;
            }
            options[(index + (event.key === 'ArrowDown' ? 1 : -1) + options.length) % options.length].focus();
        });

        document.addEventListener('click', event => {
            if (!picker.contains(event.target)) closeResults();
        });
    });
});
