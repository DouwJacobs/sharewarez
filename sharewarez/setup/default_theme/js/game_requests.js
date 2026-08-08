document.addEventListener('DOMContentLoaded', () => {
    const input = document.getElementById('requestSearch');
    const form = document.getElementById('requestSearchForm');
    if (!input || !form) return;
    const searchWrap = input.closest('.request-search-wrap');
    const searchIcon = searchWrap.querySelector('.request-search-icon');
    const status = document.getElementById('requestSearchStatus');
    const results = document.getElementById('requestSearchResults');
    const settings = JSON.parse(document.getElementById('requestSettings').textContent);
    const escapeHtml = value => String(value ?? '').replace(/[&<>'"]/g, character => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
    }[character]));
    let searchTimer;
    let searchController;
    let searchSequence = 0;
    let searchResults = [];

    function setLoading(loading) {
        searchWrap.classList.toggle('is-loading', loading);
        searchIcon.className = loading
            ? 'fas fa-circle-notch fa-spin request-search-icon'
            : 'fas fa-magnifying-glass request-search-icon';
    }

    function renderEmpty(message, icon = 'fa-magnifying-glass') {
        results.innerHTML = `<div class="request-results-empty"><i class="fas ${icon}"></i><p>${escapeHtml(message)}</p></div>`;
    }

    function render(items, editionParent = null) {
        status.textContent = `${items.length} result${items.length === 1 ? '' : 's'} found.`;
        results.innerHTML = '';
        if (editionParent) {
            const navigation = document.createElement('div');
            navigation.className = 'request-results-navigation';
            navigation.innerHTML = `<button class="btn btn-secondary" type="button" data-back-results><i class="fas fa-arrow-left"></i> Back to search results</button><span>${items.length} related release${items.length === 1 ? '' : 's'} for ${escapeHtml(editionParent)}</span>`;
            results.appendChild(navigation);
        }
        if (!items.length) {
            if (editionParent) {
                const empty = document.createElement('div');
                empty.className = 'request-results-empty';
                empty.innerHTML = `<i class="fas fa-layer-group"></i><p>No separately catalogued editions were found for ${escapeHtml(editionParent)}.</p>`;
                results.appendChild(empty);
            } else {
                renderEmpty('No matching games found. Try a different title.');
            }
            return;
        }
        items.forEach(item => {
            const card = document.createElement('article');
            card.className = 'request-result';
            const availability = item.available_game_uuid
                ? `<a class="btn btn-primary" href="/game_details/${encodeURIComponent(item.available_game_uuid)}"><i class="fas fa-circle-check"></i> View in library</a>`
                : item.requested_by_user
                    ? '<button class="btn btn-secondary" disabled><i class="fas fa-check"></i> Already requested</button>'
                    : item.request_status === 'fulfilled' || item.request_status === 'not_planned'
                        ? `<button class="btn btn-secondary" disabled><i class="fas fa-ban"></i> ${escapeHtml(item.request_status === 'fulfilled' ? 'Request fulfilled' : 'Not planned')}</button>`
                        : settings.activeRequestCount >= settings.maxActiveRequestsPerUser
                            ? '<button class="btn btn-secondary" disabled><i class="fas fa-gauge-high"></i> Request limit reached</button>'
                            : `<button class="btn btn-primary" data-request="${item.igdb_id}"><i class="fas fa-paper-plane"></i> ${item.can_join_request ? 'Join request' : 'Request game'}</button>`;
            const note = settings.allowRequestNotes && !item.available_game_uuid && !item.requested_by_user
                ? '<label class="request-note"><span>Note for the administrator <small>Optional</small></span><textarea maxlength="1000" placeholder="Edition, language, or other useful details"></textarea></label>' : '';
            const anyEdition = settings.allowRequestAnyEdition && !item.available_game_uuid && !item.requested_by_user
                ? '<label class="request-any-edition"><input type="checkbox"><span><strong>Any edition works</strong><small>A related Gold, Deluxe, or standard edition can fulfill this request.</small></span></label>' : '';
            const requestCount = item.requester_count
                ? `<span class="request-result-demand"><i class="fas fa-users"></i> ${item.requester_count} waiting</span>` : '';
            const availableBadge = item.available_game_uuid
                ? '<span class="request-result-availability"><i class="fas fa-circle-check"></i> Available</span>' : '';
            const platforms = (item.platforms || []).slice(0, 3).map(platform => `<span>${escapeHtml(platform)}</span>`).join('');
            card.innerHTML = `
                <div class="request-result-cover">
                    ${item.cover_url ? `<img src="${escapeHtml(item.cover_url)}" alt="Cover for ${escapeHtml(item.game_name)}" loading="lazy">` : '<span><i class="fas fa-gamepad"></i></span>'}
                    ${availableBadge}
                </div>
                <div class="request-result-content">
                    <div class="request-result-heading">
                        <div><p class="edition-label">${escapeHtml(item.edition_name || 'Base game')}</p><h3>${escapeHtml(item.game_name)}</h3></div>
                        ${requestCount}
                    </div>
                    <div class="request-platforms">${platforms || '<span>Platforms not listed</span>'}</div>
                    ${item.summary ? `<p class="request-result-summary">${escapeHtml(item.summary)}</p>` : ''}
                    ${(note || anyEdition) ? `<details class="request-result-options"><summary>Add request details</summary>${note}${anyEdition}</details>` : ''}
                    <div class="request-result-actions">${availability}${editionParent ? '' : `<button class="btn btn-secondary" data-editions="${item.igdb_id}"><i class="fas fa-layer-group"></i> Editions</button>`}</div>
                </div>`;
            results.appendChild(card);
        });
    }

    async function search(sequence) {
        const term = input.value.trim();
        clearTimeout(searchTimer);
        status.textContent = '';
        if (term.length < 2) {
            results.innerHTML = '';
            if (sequence === searchSequence) setLoading(false);
            return;
        }
        searchController = new AbortController();
        try {
            const response = await fetch(`/api/requests/search?q=${encodeURIComponent(term)}`, {signal: searchController.signal});
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || 'Search failed.');
            if (sequence === searchSequence) {
                searchResults = data.results;
                render(searchResults);
            }
        } catch (error) {
            if (error.name !== 'AbortError' && sequence === searchSequence) {
                status.textContent = error.message;
                renderEmpty(error.message, 'fa-triangle-exclamation');
            }
        } finally {
            if (sequence === searchSequence) setLoading(false);
        }
    }

    input.addEventListener('input', () => {
        clearTimeout(searchTimer);
        searchController?.abort();
        const sequence = ++searchSequence;
        if (input.value.trim().length < 2) {
            results.innerHTML = '';
            status.textContent = '';
            setLoading(false);
            return;
        }
        setLoading(true);
        searchTimer = setTimeout(() => search(sequence), 250);
    });
    form.addEventListener('submit', event => {
        event.preventDefault();
        clearTimeout(searchTimer);
        searchController?.abort();
        const sequence = ++searchSequence;
        setLoading(true);
        search(sequence);
    });
    input.addEventListener('keydown', event => {
        if (event.key !== 'Enter') return;
        event.preventDefault();
        form.requestSubmit();
    });
    results.addEventListener('click', async event => {
        const backButton = event.target.closest('[data-back-results]');
        if (backButton) {
            render(searchResults);
            input.focus();
            return;
        }
        const editionButton = event.target.closest('[data-editions]');
        if (editionButton) {
            editionButton.disabled = true;
            setLoading(true);
            try {
                const response = await fetch(`/api/requests/editions/${editionButton.dataset.editions}`);
                const data = await response.json();
                if (!response.ok) throw new Error(data.error || 'Could not load editions.');
                const parentName = editionButton.closest('.request-result')?.querySelector('h3')?.textContent || 'selected game';
                const related = (data.results || []).filter(item => String(item.igdb_id) !== editionButton.dataset.editions);
                render(related, parentName);
            } catch (error) {
                status.textContent = error.message;
            } finally {
                setLoading(false);
            }
            return;
        }
        const requestButton = event.target.closest('[data-request]');
        if (!requestButton) return;
        const card = requestButton.closest('.request-result');
        requestButton.disabled = true;
        requestButton.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i> Submitting';
        try {
            const response = await fetch('/requests', {
                method: 'POST',
                headers: CSRFUtils.getHeaders({'Content-Type': 'application/json'}),
                body: JSON.stringify({
                    igdb_id: requestButton.dataset.request,
                    note: card.querySelector('textarea')?.value || '',
                    accept_any_edition: card.querySelector('.request-any-edition input')?.checked || false
                })
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || 'Request failed.');
            window.location.reload();
        } catch (error) {
            status.textContent = error.message;
            requestButton.disabled = false;
            requestButton.innerHTML = '<i class="fas fa-rotate-right"></i> Try again';
        }
    });

    document.querySelectorAll('[data-confirm-withdraw]').forEach(formElement => {
        formElement.addEventListener('submit', event => {
            const gameName = formElement.dataset.confirmWithdraw || 'this request';
            if (!window.confirm(`Withdraw your request for ${gameName}? You can request it again later.`)) {
                event.preventDefault();
            }
        });
    });
});
