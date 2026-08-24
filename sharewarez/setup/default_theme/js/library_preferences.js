document.addEventListener('DOMContentLoaded', () => {
    const container = document.getElementById('gamesContainer');
    const savedViews = document.querySelector('.library-saved-views');
    const csrfToken = () => CSRFUtils.getToken();
    const save = async payload => {
        const response = await fetch('/api/preferences/library', {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrfToken()},
            body: JSON.stringify(payload),
        });
        const body = await response.json();
        if (!response.ok) throw new Error(body.error || 'Unable to save Library preference.');
        return body;
    };

    document.querySelectorAll('[data-library-view]').forEach(button => button.addEventListener('click', async () => {
        const view = button.dataset.libraryView;
        container.classList.remove('library-view-grid', 'library-view-compact', 'library-view-list');
        container.classList.add(`library-view-${view}`);
        document.querySelectorAll('[data-library-view]').forEach(item => {
            const active = item === button;
            item.classList.toggle('active', active);
            item.setAttribute('aria-pressed', String(active));
        });
        try { await save({action: 'set_view', view}); } catch (error) { console.error(error); }
    }));

    document.querySelector('[data-save-library-view]')?.addEventListener('submit', async event => {
        event.preventDefault();
        const input = event.currentTarget.querySelector('input');
        const button = event.currentTarget.querySelector('button');
        button.disabled = true;
        try {
            await save({action: 'save_view', name: input.value, query: window.location.search});
            window.location.reload();
        } catch (error) {
            input.setCustomValidity(error.message);
            input.reportValidity();
            button.disabled = false;
        }
    });

    document.querySelectorAll('[data-delete-library-view]').forEach(button => button.addEventListener('click', async () => {
        button.disabled = true;
        try { await save({action: 'delete_view', name: button.dataset.deleteLibraryView}); window.location.reload(); }
        catch (error) { button.disabled = false; console.error(error); }
    }));

    const closeSavedViews = () => savedViews?.removeAttribute('open');
    document.querySelector('[data-close-saved-views]')?.addEventListener('click', closeSavedViews);
    document.addEventListener('click', event => {
        if (savedViews?.open && !savedViews.contains(event.target)) closeSavedViews();
    });
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape' && savedViews?.open) {
            closeSavedViews();
            savedViews.querySelector('summary')?.focus();
        }
    });
});
