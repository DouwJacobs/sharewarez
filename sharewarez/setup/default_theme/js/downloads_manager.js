document.addEventListener('DOMContentLoaded', () => {
    const rows = [...document.querySelectorAll('tr[data-download-id]')];
    if (!rows.length) return;

    const activeStatuses = new Set(['pending', 'processing']);
    let delay = 3000;
    let timer = null;

    const renderStatus = (row, status) => {
        const cell = row.querySelector('.status-cell');
        if (!cell) return;
        const normalized = status.toLowerCase().replaceAll(' ', '-');
        cell.innerHTML = `<span class="download-status download-status--${normalized}"><span class="download-status-dot" aria-hidden="true"></span>${status.replaceAll('_', ' ').replace(/\b\w/g, char => char.toUpperCase())}</span>`;
        row.dataset.downloadStatus = status;
        if (status === 'available' && !row.querySelector('.actions-cell a[href*="download_zip"]')) window.location.reload();
    };

    const refresh = async () => {
        const activeRows = rows.filter(row => activeStatuses.has(row.dataset.downloadStatus || row.querySelector('.download-status')?.textContent.trim().toLowerCase()));
        if (!activeRows.length) return;
        const ids = activeRows.map(row => row.dataset.downloadId).join(',');
        try {
            const response = await fetch(`/api/downloads/status?ids=${encodeURIComponent(ids)}`);
            if (!response.ok) throw new Error('Status refresh failed');
            const data = await response.json();
            data.downloads.forEach(item => {
                const row = document.querySelector(`tr[data-download-id="${item.id}"]`);
                if (row) renderStatus(row, item.status);
            });
            delay = 3000;
        } catch (error) {
            console.error(error);
            delay = Math.min(delay * 2, 30000);
        }
        timer = window.setTimeout(refresh, delay);
    };

    document.addEventListener('visibilitychange', () => {
        if (document.hidden && timer) window.clearTimeout(timer);
        else if (!document.hidden) refresh();
    });
    refresh();
});
