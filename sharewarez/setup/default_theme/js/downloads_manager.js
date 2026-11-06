document.addEventListener('DOMContentLoaded', () => {
    'use strict';
    const ui = window.DownloadLive, views = new Map();
    const connection = document.getElementById('downloadConnection');
    const make = (tag, cls, parent) => {
        const node = document.createElement(tag); node.className = cls; parent.append(node); return node;
    };
    document.querySelectorAll('tr[data-download-id]').forEach(row => {
        const cell = row.querySelector('.status-cell'), badge = cell.querySelector('.download-status');
        const label = make('span', '', badge);
        [...badge.childNodes].filter(node => node.nodeType === 3).forEach(node => {
            label.textContent += node.textContent.trim(); node.remove();
        });
        views.set(row.dataset.downloadId, {row, cell, badge, label,
            delivery:cell.querySelector('.download-delivery-badge'),
            progress:cell.querySelector('.download-archive-progress'),
            failure:cell.querySelector('.download-failure-reason'),
            detail:cell.querySelector('.download-transfer-detail'),
            latest:cell.querySelector('.download-latest-attempt'),
            recovery:cell.querySelector('.download-recovery-advice'),
            expiry:cell.querySelector('.download-expiry')});
    });
    if (!views.size) { ui.text(connection, 'No download links to monitor'); return; }
    const action = (view, name, visible) => {
        const node = view.row.querySelector('[data-action="' + name + '"]');
        if (!node) return;
        if (!visible && node.contains(document.activeElement)) view.cell.focus({preventScroll:true});
        node.hidden = !visible;
    };
    const render = data => {
        if (!Array.isArray(data.downloads)) throw new Error('Invalid snapshot');
        const downloads = new Map(data.downloads.map(item => [String(item.id),item]));
        const counts = {};
        views.forEach((view,id) => {
            const item = downloads.get(id) || {status:'removed',display_status:'Removed',allowed_actions:[],delivery_label:'Unavailable',delivery_class:'unavailable'};
            const actions = new Set(item.allowed_actions || []), transfer = item.active_transfer;
            const label = item.display_status, preparing = item.status === 'processing';
            counts[label] = (counts[label] || 0) + 1;
            view.row.dataset.downloadStatus = item.status;
            view.row.dataset.transferActive = String(Boolean(transfer));
            view.row.dataset.deliveryKind = item.delivery_kind || '';
            const normalized = label.toLowerCase().replaceAll(' ', '-');
            view.badge.className = 'ui-status ui-status--' + normalized + ' download-status download-status--' + normalized;
            ui.text(view.label,label);
            ui.text(view.delivery.querySelector('span'),item.delivery_label);
            view.delivery.className = 'download-delivery-badge download-delivery-badge--' + item.delivery_class;
            view.delivery.querySelector('i').className = 'fas ' + (item.delivery_class === 'resumable' ? 'fa-rotate' : item.delivery_class === 'preparing' ? 'fa-box-open' : 'fa-triangle-exclamation');
            view.delivery.hidden = item.status === 'removed' || item.delivery_label === item.display_status;
            view.progress.hidden = !preparing;
            const percent = item.archive_progress || 0;
            view.progress.firstElementChild.firstElementChild.style.width = percent + '%';
            ui.text(view.progress.querySelector('small'),percent + '% prepared');
            view.failure.hidden = !item.message; ui.text(view.failure,item.message || '');
            view.detail.hidden = !transfer;
            if (transfer) ui.text(view.detail,(transfer.bytes_sent_label || '0 B') + ' streamed' + (transfer.expected_bytes_label ? ' of ' + transfer.expected_bytes_label : ''));
            view.latest.hidden = Boolean(transfer) || !item.latest_attempt;
            if (item.latest_attempt) ui.text(view.latest,'Last attempt: ' + (item.latest_attempt.summary || item.latest_attempt.end_reason_label));
            view.recovery.hidden = !item.recovery_message; ui.text(view.recovery,item.recovery_message || '');
            view.expiry.hidden = item.status !== 'available' || !item.expires_at;
            ui.text(view.expiry,item.expiry_label || ''); view.expiry.classList.toggle('is-urgent',Boolean(item.expiring_soon));
            if (item.size_label) ui.text(view.row.querySelector('.download-size'),item.size_label);
            ui.text(view.row.querySelector('[data-retry-label]'),item.retry_label || 'Retry');
            for (const name of ['download','cancel','retry','fallback','delete']) action(view,name,actions.has(name));
        });
        const summary = document.querySelector('.download-state-summary');
        if (summary) {
            Object.keys(counts).forEach(label => {
                if (![...summary.children].some(child => child.dataset.stateLabel === label)) {
                    const node = document.createElement('span'); node.dataset.stateLabel = label;
                    node.append(document.createElement('strong'),document.createTextNode(label));
                    summary.insertBefore(node,summary.querySelector('a'));
                }
            });
            [...summary.querySelectorAll('[data-state-label]')].forEach(node => {
                node.hidden = !counts[node.dataset.stateLabel]; ui.text(node.querySelector('strong'),counts[node.dataset.stateLabel] || 0);
            });
        }
    };
    const ids = [...views.keys()];
    ui.connect({view:'downloads',ids,render,status:message => ui.text(connection,message),
        poll:signal => ui.json('/api/downloads/status?ids=' + ids.join(','),signal)});
});
