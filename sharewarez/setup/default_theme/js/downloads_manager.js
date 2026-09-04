document.addEventListener('DOMContentLoaded', () => {
    'use strict';
    const ui = window.DownloadLive, views = new Map();
    const connection = document.getElementById('downloadConnection');
    const labels = {pending:'Queued', processing:'Preparing', available:'Ready', failed:'Failed',
        cancelled:'Cancelled', expired:'Expired', removed:'Removed'};
    const make = (tag, cls, parent) => {
        const node = document.createElement(tag); node.className = cls; parent.append(node); return node;
    };
    const labelWithin = (node, tag = 'span') => {
        const initial = [...node.childNodes].filter(child => child.nodeType === 3);
        const label = make(tag, '', node);
        label.textContent = initial.map(child => child.textContent).join('').trim();
        initial.forEach(child => child.remove()); return label;
    };
    document.querySelectorAll('tr[data-download-id]').forEach(row => {
        const cell = row.querySelector('.status-cell'), badge = cell.querySelector('.download-status');
        const delivery = cell.querySelector('.download-delivery-badge');
        let progress = cell.querySelector('.download-archive-progress');
        if (!progress) {
            progress = make('span', 'download-archive-progress', cell);
            make('span', '', make('span', '', progress)); progress.hidden = true;
        }
        progress.removeAttribute('aria-live'); progress.removeAttribute('role');
        const failures = [...cell.querySelectorAll('.download-failure-reason')];
        failures.slice(1).forEach(node => { node.hidden = true; });
        views.set(row.dataset.downloadId, {row, cell, badge, badgeLabel:labelWithin(badge),
            delivery, deliveryLabel:labelWithin(delivery), progress, progressLabel:labelWithin(progress,'small'),
            failure:failures[0] || make('small','download-failure-reason',cell),
            detail:cell.querySelector('.download-transfer-detail') || make('small','download-transfer-detail',cell),
            expiry:cell.querySelector('.download-expiry') || make('small','download-expiry',cell)});
    });
    if (!views.size) { ui.text(connection, 'No download links to monitor'); return; }
    const action = (view, name, visible) => {
        const node = view.row.querySelector('[data-action="' + name + '"]');
        if (!node) return;
        if (!visible && node.contains(document.activeElement)) view.cell.focus({preventScroll:true});
        node.hidden = !visible;
    };
    const render = data => {
        if (!Array.isArray(data.downloads) || !Array.isArray(data.transfers)) throw new Error('Invalid snapshot');
        const downloads = new Map(data.downloads.map(item => [String(item.id),item]));
        const transfers = new Map(data.transfers.map(item => [String(item.download_request_id),item]));
        const counts = {};
        views.forEach((view,id) => {
            const item = downloads.get(id) || {status:'removed'}, transfer = transfers.get(id);
            const status = item.status, active = Boolean(transfer);
            const pending = ['pending','processing'].includes(status), retry = ['failed','cancelled','expired'].includes(status);
            const preparing = ['queued','building'].includes(item.archive?.state);
            const label = active ? 'Downloading' : labels[status] || status;
            counts[label] = (counts[label] || 0) + 1;
            view.row.dataset.downloadStatus = status; view.row.dataset.transferActive = String(active);
            view.badge.className = 'ui-status download-status download-status--' + label.toLowerCase();
            ui.text(view.badgeLabel,label);
            const resumable = (item.delivery_kind === 'direct' && view.row.dataset.directResumable === 'true')
                || (item.delivery_kind === 'cached_archive' && item.archive?.state === 'ready');
            ui.text(view.deliveryLabel,preparing ? 'Preparing' : resumable ? 'Resumable' : 'Streaming · restart required');
            view.delivery.className = 'download-delivery-badge download-delivery-badge--' + (preparing ? 'preparing' : resumable ? 'resumable' : 'streaming');
            view.delivery.querySelector('i').className = 'fas ' + (preparing ? 'fa-box-open' : resumable ? 'fa-rotate' : 'fa-triangle-exclamation');
            view.delivery.hidden = status === 'removed'; view.progress.hidden = !preparing;
            const percent = item.archive?.progress || 0;
            view.progress.firstElementChild.firstElementChild.style.width = percent + '%';
            ui.text(view.progressLabel,percent + '% prepared');
            const failure = status === 'expired' ? 'This download link expired. Retry to create a fresh link.'
                : item.archive?.failure_message || (status === 'failed' ? 'The request could not be completed. Retry to validate the source.' : '');
            view.failure.hidden = !failure; ui.text(view.failure,failure);
            view.detail.hidden = !active;
            if (active) ui.text(view.detail,(transfer.bytes_sent_label || '0 B') + ' streamed' + (transfer.expected_bytes_label ? ' of ' + transfer.expected_bytes_label : ''));
            view.expiry.hidden = active || status !== 'available' || !item.expires_at;
            if (item.expires_at) {
                const date = new Date(item.expires_at);
                ui.text(view.expiry,'Available until ' + date.toLocaleString());
                view.expiry.classList.toggle('is-urgent',date - Date.now() < 86400000);
            }
            if (item.size_label) ui.text(view.row.querySelector('.download-size'),item.size_label);
            action(view,'download',!active && status === 'available'); action(view,'downloading',active);
            action(view,'cancel',!active && pending); action(view,'retry',!active && retry);
            action(view,'fallback',!active && (pending || retry) && item.fallback_available);
            action(view,'delete',!active && status !== 'removed');
        });
        const summary = document.querySelector('.download-state-summary');
        if (summary) {
            for (const label of [...Object.values(labels),'Downloading']) {
                let node = [...summary.children].find(child => child.dataset.stateLabel === label);
                if (!node) {
                    node = document.createElement('span'); node.dataset.stateLabel = label;
                    node.append(document.createElement('strong'),document.createTextNode(label));
                    summary.insertBefore(node,summary.querySelector('a'));
                }
                node.hidden = !counts[label]; ui.text(node.querySelector('strong'),counts[label] || 0);
            }
            [...summary.children].filter(node => node.tagName === 'SPAN' && !node.dataset.stateLabel)
                .forEach(node => { node.hidden = true; });
        }
    };
    const ids = [...views.keys()];
    ui.connect({view:'downloads',ids,render,status:message => ui.text(connection,message),
        poll:async signal => {
            const [downloads,transfers] = await Promise.all([
                ui.json('/api/downloads/status?ids=' + ids.join(','),signal),
                ui.json('/downloads/active-transfers',signal)]);
            return {...downloads,...transfers};
        }});
});
