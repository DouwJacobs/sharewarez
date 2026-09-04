document.addEventListener('DOMContentLoaded', () => {
    const rows = [...document.querySelectorAll('tr[data-download-id]')];
    if (!rows.length) return;

    const activeStatuses = new Set(['pending', 'processing']);
    let delay = 3000;
    let timer = null;
    let transferDelay = 2000;
    let transferTimer = null;
    let transferRefreshRunning = false;

    const renderStatus = (row, status) => {
        const cell = row.querySelector('.status-cell');
        if (!cell) return;
        const normalized = status.toLowerCase().replaceAll(' ', '-');
        let badge = cell.querySelector('.download-status');
        if (!badge) {
            badge = document.createElement('span');
            cell.prepend(badge);
        }
        badge.className = `download-status download-status--${normalized}`;
        badge.innerHTML = `<span class="download-status-dot" aria-hidden="true"></span>${status.replaceAll('_', ' ').replace(/\b\w/g, char => char.toUpperCase())}`;
        row.dataset.downloadStatus = status;
        
        const actionsCell = row.querySelector('.actions-cell');
        if (actionsCell && status === 'available') {
            const isTransferActive = row.dataset.transferActive === 'true';
            if (!isTransferActive) {
                actionsCell.querySelectorAll('.btn-downloading').forEach(el => el.remove());
                if (!actionsCell.querySelector('a[href*="download_zip"]')) {
                    const id = row.dataset.downloadId;
                    const downloadBtn = document.createElement('a');
                    downloadBtn.href = `/download_zip/${id}`;
                    downloadBtn.className = 'btn btn-primary btn-sm';
                    downloadBtn.innerHTML = '<i class="fas fa-download" aria-hidden="true"></i> Download';
                    actionsCell.prepend(downloadBtn);
                }
            }
        }
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
                if (!row) return;
                if (item.status !== row.dataset.downloadStatus) {
                    window.location.reload();
                    return;
                }
                const progress = row.querySelector('.download-archive-progress');
                if (progress && item.archive?.progress != null) {
                    const bar = progress.querySelector('span > span');
                    if (bar) bar.style.width = `${item.archive.progress}%`;
                    progress.lastChild.textContent = ` ${item.archive.progress}% prepared`;
                }
            });
            delay = 3000;
        } catch (error) {
            console.error(error);
            delay = Math.min(delay * 2, 30000);
        }
        timer = window.setTimeout(refresh, delay);
    };

    const updateTransferUI = (row, transfer) => {
        const id = row.dataset.downloadId;
        const statusCell = row.querySelector('.status-cell');
        const actionsCell = row.querySelector('.actions-cell');
        const wasActive = row.dataset.transferActive === 'true';
        const isActive = Boolean(transfer);
        row.dataset.transferActive = isActive ? 'true' : 'false';

        if (isActive) {
            if (statusCell) {
                let badge = statusCell.querySelector('.download-status');
                if (!badge) {
                    badge = document.createElement('span');
                    statusCell.prepend(badge);
                }
                badge.className = 'download-status download-status--downloading';
                badge.innerHTML = '<span class="download-status-dot" aria-hidden="true"></span>Downloading';

                let detail = statusCell.querySelector('.download-transfer-detail');
                if (!detail) {
                    detail = document.createElement('small');
                    detail.className = 'download-transfer-detail';
                    statusCell.appendChild(detail);
                }
                const expected = transfer.expected_bytes_label ? ` of ${transfer.expected_bytes_label}` : '';
                detail.textContent = `${transfer.bytes_sent_label || '0 B'} streamed${expected}`;
            }

            if (actionsCell) {
                actionsCell.querySelectorAll('a[href*="download_zip"]').forEach(el => el.remove());
                const existingDeleteBtn = actionsCell.querySelector('form[action*="delete_download"]');
                if (existingDeleteBtn) existingDeleteBtn.style.display = 'none';

                let downloadingBtn = actionsCell.querySelector('.btn-downloading');
                if (!downloadingBtn) {
                    downloadingBtn = document.createElement('span');
                    downloadingBtn.className = 'btn btn-secondary btn-sm disabled btn-downloading';
                    downloadingBtn.setAttribute('aria-disabled', 'true');
                    downloadingBtn.innerHTML = '<i class="fas fa-circle-notch fa-spin" aria-hidden="true"></i> Downloading';
                    actionsCell.prepend(downloadingBtn);
                }
            }
        } else if (wasActive || actionsCell?.querySelector('.btn-downloading')) {
            const currentStatus = row.dataset.downloadStatus || 'available';
            if (statusCell) {
                const detail = statusCell.querySelector('.download-transfer-detail');
                if (detail) detail.remove();
                renderStatus(row, currentStatus);
            }
            if (actionsCell) {
                actionsCell.querySelectorAll('.btn-downloading').forEach(btn => btn.remove());
                const deleteForm = actionsCell.querySelector('form[action*="delete_download"]');
                if (deleteForm) deleteForm.style.display = '';

                if (currentStatus === 'available' && !actionsCell.querySelector('a[href*="download_zip"]')) {
                    const downloadBtn = document.createElement('a');
                    downloadBtn.href = `/download_zip/${id}`;
                    downloadBtn.className = 'btn btn-primary btn-sm';
                    downloadBtn.innerHTML = '<i class="fas fa-download" aria-hidden="true"></i> Download';
                    actionsCell.prepend(downloadBtn);
                }
            }
        }
    };

    const refreshTransfers = async () => {
        if (transferRefreshRunning || document.hidden) return;
        transferRefreshRunning = true;
        try {
            const response = await fetch('/downloads/active-transfers', {
                credentials: 'same-origin', cache: 'no-store',
            });
            if (!response.ok) throw new Error('Transfer refresh failed');
            const data = await response.json();
            const transfers = data.transfers || [];
            const activeMap = new Map(
                transfers.map(item => [String(item.download_request_id), item])
            );
            rows.forEach(row => {
                const id = row.dataset.downloadId;
                const transfer = activeMap.get(id);
                updateTransferUI(row, transfer);
            });
            transferDelay = transfers.length ? 2000 : 10000;
        } catch (_error) {
            // A transient polling failure should not interrupt the page.
            transferDelay = Math.min(transferDelay * 2, 30000);
        } finally {
            transferRefreshRunning = false;
            window.clearTimeout(transferTimer);
            if (!document.hidden) {
                transferTimer = window.setTimeout(refreshTransfers, transferDelay);
            }
        }
    };

    document.addEventListener('visibilitychange', () => {
        if (document.hidden) {
            window.clearTimeout(timer);
            window.clearTimeout(transferTimer);
        } else {
            refresh();
            refreshTransfers();
        }
    });
    refresh();
    refreshTransfers();
});
