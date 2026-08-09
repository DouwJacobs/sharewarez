document.addEventListener('DOMContentLoaded', () => {
    const palette = document.getElementById('globalSearch');
    const input = document.getElementById('globalSearchInput');
    const results = document.getElementById('globalSearchResults');
    const saveButton = document.getElementById('globalSearchSave');
    if (!palette || !input || !results) return;

    let controller = null;
    let timer = null;
    let activeIndex = -1;

    const items = () => [...results.querySelectorAll('[role="option"]')];
    const setActive = index => {
        const options = items();
        if (!options.length) return;
        activeIndex = (index + options.length) % options.length;
        options.forEach((item, i) => item.classList.toggle('active', i === activeIndex));
        options[activeIndex].scrollIntoView({block: 'nearest'});
    };
    const renderSuggestions = suggestions => {
        results.replaceChildren();
        if (!suggestions.length) {
            results.hidden = true;
            return;
        }
        results.hidden = false;
        const heading = document.createElement('p');
        heading.className = 'global-search-section-label';
        heading.textContent = 'Saved searches';
        results.append(heading);
        suggestions.forEach(query => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'global-search-suggestion';
            button.setAttribute('role', 'option');
            button.innerHTML = '<i class="fas fa-clock-rotate-left" aria-hidden="true"></i><span></span>';
            button.querySelector('span').textContent = query;
            button.addEventListener('click', () => { input.value = query; input.dispatchEvent(new Event('input')); input.focus(); });
            results.append(button);
        });
    };
    const loadSuggestions = async () => {
        try {
            const response = await fetch('/api/global-search?q=');
            if (response.ok) renderSuggestions((await response.json()).suggestions || []);
        } catch (_) { renderSuggestions([]); }
    };
    const open = () => {
        palette.hidden = false;
        const anchor = document.querySelector('.content-global-search');
        if (anchor && window.matchMedia('(min-width: 769px)').matches) {
            const rect = anchor.getBoundingClientRect();
            palette.style.setProperty('--search-anchor-left', `${rect.left}px`);
            palette.style.setProperty('--search-anchor-top', `${rect.top}px`);
            palette.style.setProperty('--search-anchor-width', `${rect.width}px`);
        }
        document.body.classList.add('global-search-open'); input.focus(); input.select();
        if (input.value.trim().length < 2) loadSuggestions();
    };
    const close = () => { palette.hidden = true; document.body.classList.remove('global-search-open'); activeIndex = -1; };

    document.querySelectorAll('[data-global-search-open]').forEach(button => button.addEventListener('click', open));
    document.querySelectorAll('[data-global-search-close]').forEach(button => button.addEventListener('click', close));
    document.addEventListener('pointerdown', event => {
        if (!palette.hidden && !event.target.closest('.global-search-dialog') && !event.target.closest('[data-global-search-inline]')) close();
    });
    document.querySelectorAll('[data-global-search-inline]').forEach(inlineInput => {
        inlineInput.addEventListener('focus', () => { input.value = inlineInput.value; open(); if (input.value.length >= 2) input.dispatchEvent(new Event('input')); });
        inlineInput.addEventListener('input', () => { input.value = inlineInput.value; open(); input.dispatchEvent(new Event('input')); });
    });
    document.addEventListener('keydown', event => {
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); palette.hidden ? open() : close(); }
        else if (!palette.hidden && event.key === 'Escape') close();
    });

    input.addEventListener('keydown', event => {
        if (event.key === 'ArrowDown') { event.preventDefault(); setActive(activeIndex + 1); }
        else if (event.key === 'ArrowUp') { event.preventDefault(); setActive(activeIndex - 1); }
        else if (event.key === 'Enter' && items()[activeIndex]) { items()[activeIndex].click(); }
    });

    input.addEventListener('input', () => {
        clearTimeout(timer);
        const query = input.value.trim();
        if (saveButton) saveButton.hidden = query.length < 2;
        activeIndex = -1;
        if (query.length < 2) { loadSuggestions(); return; }
        timer = setTimeout(async () => {
            if (controller) controller.abort();
            controller = new AbortController();
            results.hidden = false;
            results.innerHTML = '<p class="global-search-hint">Searching…</p>';
            try {
                const response = await fetch(`/api/global-search?q=${encodeURIComponent(query)}`, {signal: controller.signal});
                if (!response.ok) throw new Error('Search request failed');
                const data = await response.json();
                results.replaceChildren();
                if (!data.results.length) { results.innerHTML = '<p class="global-search-hint">No matching results.</p>'; return; }
                data.results.forEach(result => {
                    const link = document.createElement('a');
                    link.href = result.url;
                    link.className = 'global-search-result';
                    link.setAttribute('role', 'option');
                    const icon = document.createElement('i');
                    icon.className = `fas ${result.icon}`;
                    icon.setAttribute('aria-hidden', 'true');
                    const copy = document.createElement('span');
                    const title = document.createElement('strong');
                    title.textContent = result.title;
                    const subtitle = document.createElement('small');
                    subtitle.textContent = `${result.type} · ${result.subtitle}`;
                    copy.append(title, subtitle);
                    link.append(icon, copy);
                    results.append(link);
                });
            } catch (error) {
                if (error.name !== 'AbortError') results.innerHTML = '<p class="global-search-hint">Search is temporarily unavailable.</p>';
            }
        }, 180);
    });

    saveButton?.addEventListener('click', async () => {
        const query = input.value.trim();
        if (query.length < 2) return;
        const token = document.querySelector('meta[name="csrf-token"]')?.content || '';
        const response = await fetch('/api/global-search/saved', {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'X-CSRFToken': token},
            body: JSON.stringify({query}),
        });
        if (response.ok) {
            saveButton.innerHTML = '<i class="fas fa-bookmark" aria-hidden="true"></i>';
            saveButton.setAttribute('aria-label', 'Search saved');
        }
    });
});
