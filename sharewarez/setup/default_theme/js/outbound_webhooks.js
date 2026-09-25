document.addEventListener('DOMContentLoaded', () => {
    const root = document.querySelector('.webhook-workspace');
    if (!root) return;
    const editor = root.querySelector('[data-webhook-editor]');
    const id = root.querySelector('[data-webhook-id]');
    const name = root.querySelector('[data-webhook-name]');
    const url = root.querySelector('[data-webhook-url]');
    const enabled = root.querySelector('[data-webhook-enabled]');
    const checks = Array.from(root.querySelectorAll('[data-webhook-event]'));
    const csrf = document.querySelector('meta[name="csrf-token"]')?.content;

    const request = async (path, payload = {}) => {
        const response = await fetch(path, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf}, body: JSON.stringify(payload)});
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Webhook operation failed.');
        return data;
    };
    const open = record => {
        id.value = record?.dataset.id || '';
        name.value = record?.dataset.name || '';
        url.value = '';
        enabled.checked = record ? record.dataset.enabled === 'true' : true;
        const events = record ? JSON.parse(record.dataset.events || '[]') : [];
        checks.forEach(check => { check.checked = events.includes(check.value); });
        editor.hidden = false;
        name.focus();
    };
    const showSecret = value => {
        const panel = root.querySelector('[data-webhook-secret]');
        panel.querySelector('[data-webhook-secret-value]').textContent = value;
        panel.hidden = false;
        panel.scrollIntoView({block: 'nearest'});
    };
    root.querySelector('[data-webhook-new]').addEventListener('click', () => open(null));
    root.querySelector('[data-webhook-cancel]').addEventListener('click', () => { editor.hidden = true; });
    root.querySelector('[data-webhook-save]').addEventListener('click', async () => {
        try {
            const payload = {name: name.value, url: url.value, enabled: enabled.checked, events: checks.filter(item => item.checked).map(item => item.value)};
            const data = await request(id.value ? `/admin/integrations/webhooks/${id.value}` : '/admin/integrations/webhooks', payload);
            if (data.secret) showSecret(data.secret);
            if (!data.secret || id.value) window.location.reload();
        } catch (error) { window.showNotification?.(error.message, 'error') || alert(error.message); }
    });
    root.querySelectorAll('[data-webhook-record]').forEach(record => {
        record.querySelector('[data-webhook-edit]').addEventListener('click', () => open(record));
        record.querySelector('[data-webhook-test]').addEventListener('click', async () => { try { await request(`/admin/integrations/webhooks/${record.dataset.id}/test`); window.location.reload(); } catch (error) { alert(error.message); } });
        record.querySelector('[data-webhook-rotate]').addEventListener('click', async () => { try { const data = await request(`/admin/integrations/webhooks/${record.dataset.id}/rotate-secret`); showSecret(data.secret); } catch (error) { alert(error.message); } });
        record.querySelector('[data-webhook-delete]').addEventListener('click', async () => { if (!confirm(`Delete ${record.dataset.name}?`)) return; try { await request(`/admin/integrations/webhooks/${record.dataset.id}/delete`); window.location.reload(); } catch (error) { alert(error.message); } });
    });
    root.querySelectorAll('[data-webhook-retry]').forEach(button => button.addEventListener('click', async () => { try { await request(`/admin/integrations/webhook-deliveries/${button.dataset.webhookRetry}/retry`); window.location.reload(); } catch (error) { alert(error.message); } }));
});
