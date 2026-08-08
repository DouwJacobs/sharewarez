document.addEventListener('DOMContentLoaded', () => {
    const clearButton = document.getElementById('clearLogsBtn');
    const confirmButton = document.getElementById('confirmClearLogs');
    const modalElement = document.getElementById('clearLogsModal');
    const modal = modalElement && window.bootstrap ? new bootstrap.Modal(modalElement) : null;

    clearButton?.addEventListener('click', () => modal?.show());
    confirmButton?.addEventListener('click', async () => {
        const original = confirmButton.innerHTML;
        confirmButton.disabled = true;
        confirmButton.innerHTML = '<i class="fas fa-circle-notch fa-spin" aria-hidden="true"></i> Clearing…';
        try {
            const response = await fetch('/admin/api/system_logs/clear', {
                method: 'DELETE',
                headers: { 'X-CSRFToken': confirmButton.dataset.csrfToken },
            });
            const data = await response.json();
            if (!response.ok || !data.success) throw new Error(data.error || 'Unable to clear logs');
            window.location.assign('/admin/system_logs');
        } catch (error) {
            window.jQuery?.notify(error.message, 'error');
            confirmButton.disabled = false;
            confirmButton.innerHTML = original;
        }
    });

    document.querySelectorAll('[data-copy-log]').forEach((button) => {
        button.addEventListener('click', async () => {
            try {
                await navigator.clipboard.writeText(button.dataset.copyLog);
                const original = button.innerHTML;
                button.innerHTML = '<i class="fas fa-check" aria-hidden="true"></i> Copied';
                window.setTimeout(() => { button.innerHTML = original; }, 1400);
            } catch (_) {
                window.jQuery?.notify('Could not copy the event message.', 'error');
            }
        });
    });
});
