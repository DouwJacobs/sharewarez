document.addEventListener('DOMContentLoaded', () => {
    const palette = document.getElementById('globalSearch');
    const input = document.getElementById('globalSearchInput');
    const results = document.getElementById('globalSearchResults');
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
    const open = () => { palette.hidden = false; document.body.classList.add('global-search-open'); input.focus(); input.select(); };
    const close = () => { palette.hidden = true; document.body.classList.remove('global-search-open'); activeIndex = -1; };

    document.querySelectorAll('[data-global-search-open]').forEach(button => button.addEventListener('click', open));
    document.querySelectorAll('[data-global-search-close]').forEach(button => button.addEventListener('click', close));
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
        else if (event.key === 'Enter' && items()[activeIndex]) { window.location.assign(items()[activeIndex].href); }
    });

    input.addEventListener('input', () => {
        clearTimeout(timer);
        const query = input.value.trim();
        activeIndex = -1;
        if (query.length < 2) { results.innerHTML = '<p class="global-search-hint">Type at least two characters to search.</p>'; return; }
        timer = setTimeout(async () => {
            if (controller) controller.abort();
            controller = new AbortController();
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
});
