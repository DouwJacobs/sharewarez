/* Save only changed keys owned by the visible section. */
document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('settingsForm');
    const current = JSON.parse(document.getElementById('currentSettings').textContent);
    const panels = Array.from(form.querySelectorAll('[data-settings-panel]'));
    const buttons = Array.from(form.querySelectorAll('[data-settings-target]'));
    const mobileItems = ['discover', 'library', 'requests', 'downloads', 'favorites'];
    const slots = Array.from(form.querySelectorAll('.mobile-nav-slot'));
    for (const [key, value] of Object.entries(current)) {
        const input = document.getElementById(key);
        if (!input) continue;
        if (input.type === 'checkbox') input.checked = value;
        else input.value = value;
    }
    slots.forEach((select, index) => { select.value = (current.mobileNavOrder || mobileItems)[index]; });
    function navOptions() {
        const selected = slots.map(select => select.value);
        slots.forEach(select => Array.from(select.options).forEach(option => {
            option.disabled = option.value !== select.value && selected.includes(option.value);
        }));
    }
    slots.forEach(select => select.addEventListener('change', navOptions));
    navOptions();
    function values(panel, validate = false) {
        const result = {};
        for (const input of panel.querySelectorAll('input[id], select[id]')) {
            if (input.classList.contains('mobile-nav-slot')) continue;
            if (input.type === 'checkbox') result[input.id] = input.checked;
            else if (input.type === 'number') {
                const valid = input.value.trim() && Number.isFinite(Number(input.value));
                if (validate && !valid) throw new Error('Enter a valid number.');
                result[input.id] = valid ? Number(input.value) : input.value;
            } else result[input.id] = input.value;
        }
        if (panel.dataset.settingsPanel === 'interface') {
            const selected = slots.map(select => select.value);
            if (validate && new Set(selected).size !== selected.length) throw new Error('Choose a different destination for each mobile position.');
            result.mobileNavOrder = selected.concat(mobileItems.filter(item => !selected.includes(item)));
        }
        if (panel.dataset.settingsPanel === 'notifications') {
            result.notificationPolicy = Object.fromEntries(Array.from(panel.querySelectorAll('[data-notification-event]')).map(row => [
                row.dataset.notificationEvent,
                Object.fromEntries(Array.from(row.querySelectorAll('[data-notification-channel]')).map(input => [input.dataset.notificationChannel, input.checked]))
            ]));
        }
        return result;
    }
    const baseline = new Map(panels.map(panel => [panel.dataset.settingsPanel, values(panel)]));
    let active = null, pending = false;
    const status = document.getElementById('settingsSavedNotification');
    function report(message, failed = false) {
        status.textContent = message;
        status.classList.toggle('alert-danger', failed);
        status.classList.toggle('alert-success', !failed);
        status.style.display = 'block';
    }
    function activate(section, push = false) {
        const selected = panels.find(panel => panel.dataset.settingsPanel === section) || panels[0];
        active = selected.dataset.settingsPanel;
        for (const panel of panels) {
            panel.hidden = panel !== selected;
            // Native validation belongs to the visible category too.
            panel.querySelectorAll('input, select, textarea').forEach(input => { input.disabled = panel !== selected; });
            panel.classList.toggle('is-active', panel === selected);
        }
        for (const button of buttons) {
            const chosen = button.dataset.settingsTarget === active;
            button.classList.toggle('is-active', chosen);
            button.setAttribute('aria-selected', String(chosen));
        }
        if (push) {
            const url = new URL(window.location.href);
            url.searchParams.set('section', active);
            url.hash = '';
            history.pushState(null, '', url);
        }
    }
    buttons.forEach(button => button.addEventListener('click', () => activate(button.dataset.settingsTarget, true)));
    const navigate = () => activate(new URL(window.location.href).searchParams.get('section') || window.location.hash.slice(1) || document.querySelector('.server-settings-page').dataset.initialSettingsSection);
    window.addEventListener('popstate', navigate);
    window.addEventListener('hashchange', navigate);
    navigate();
    form.addEventListener('submit', async event => {
        event.preventDefault();
        if (pending) return;
        const section = active, panel = panels.find(item => item.dataset.settingsPanel === section);
        let changes;
        try {
            const snapshot = values(panel, true), previous = baseline.get(section);
            changes = Object.fromEntries(Object.entries(snapshot).filter(([key, value]) => JSON.stringify(value) !== JSON.stringify(previous[key])));
        } catch (error) { report(error.message, true); return; }
        if (!Object.keys(changes).length) { report('No changes in this category.'); return; }
        pending = true;
        const submit = form.querySelector('[type=submit]');
        submit.disabled = true;
        try {
            const response = await fetch('/admin/settings', {
                method: 'POST', headers: CSRFUtils.getHeaders({'Content-Type': 'application/json'}),
                body: JSON.stringify({section, settings: changes})
            });
            const result = await response.json();
            if (!response.ok) throw new Error((result.errors || []).join(' ') || result.error || 'Could not save settings.');
            // Preserve edits made while the request was in flight as unsaved changes.
            baseline.set(section, {...baseline.get(section), ...changes});
            report(result.message);
        } catch (error) { report(error.message, true); }
        finally { pending = false; submit.disabled = false; }
    });
});
