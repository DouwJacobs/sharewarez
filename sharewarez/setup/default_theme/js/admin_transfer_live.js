(() => {
    'use strict';
    const list = document.getElementById('activeTransferList');
    if (!list) return;
    const ui = window.DownloadLive, rows = new Map();
    const empty = list.querySelector('.active-transfer-empty');
    const count = document.getElementById('activeTransferCount');
    const connection = document.getElementById('activeTransferConnection');
    const make = (tag, className) => {
        const node = document.createElement(tag); node.className = className; return node;
    };
    const clock = item => {
        const elapsed = Math.max(0, (Date.now() - item.received) / 1000);
        ui.text(item.meta, `${item.summary} · ${ui.duration(item.data.elapsed_seconds + elapsed)}`);
        const stale = Date.now() - Date.parse(item.data.last_activity_at) >= 8000;
        const current = stale ? 0 : item.data.current_speed;
        const eta = !stale && current > 0 && item.data.eta_seconds != null
            ? ` · ETA ${ui.duration(Math.max(0, item.data.eta_seconds - elapsed))}` : '';
        ui.text(item.speed, `Current ${ui.speed(current)} · Avg ${ui.speed(item.data.average_speed)}${eta}`);
    };
    const render = data => {
        if (!Array.isArray(data.transfers)) throw new Error('Invalid transfer snapshot');
        const present = new Set();
        ui.text(count, `${data.transfers.length}${data.transfers_truncated ? '+' : ''} active`);
        empty.hidden = data.transfers.length > 0;
        for (const transfer of data.transfers) {
            const id = String(transfer.id); present.add(id);
            let item = rows.get(id);
            if (!item) {
                item = {node: make('article', 'active-transfer-item'), title: make('strong', ''),
                    meta: make('span', 'active-transfer-meta'), speed: make('span', 'active-transfer-speed'),
                    progress: make('div', 'active-transfer-progress'), bar: make('span', ''),
                    label: make('span', 'active-transfer-progress-label')};
                item.node.dataset.transferId = id;
                const details = make('div', 'active-transfer-details');
                details.append(item.title, item.meta, item.speed);
                const group = make('div', 'active-transfer-progress-group');
                item.progress.append(item.bar); group.append(item.label, item.progress);
                item.node.append(details, group); list.append(item.node); rows.set(id, item);
            }
            item.data = transfer; item.received = Date.now();
            const expected = transfer.expected_bytes_label ? ` of ${transfer.expected_bytes_label}` : '';
            item.summary = `${transfer.username} · ${transfer.bytes_sent_label}${expected} streamed`;
            ui.text(item.title, transfer.filename);
            const progress = transfer.progress == null ? null : Math.max(0, Math.min(100, transfer.progress));
            item.progress.classList.toggle('is-indeterminate', progress == null);
            item.bar.style.width = progress == null ? '' : `${progress}%`;
            ui.text(item.label, progress == null ? 'Streaming' : `${progress.toFixed(1)}%`);
            clock(item);
        }
        for (const [id, item] of rows) {
            if (!present.has(id)) { item.node.remove(); rows.delete(id); }
        }
    };
    ui.connect({view: 'activity', render, status: text => ui.text(connection, text),
        poll: signal => ui.json('/admin/active-transfers', signal)});
    setInterval(() => {
        if (!document.hidden) rows.forEach(clock);
    }, 1000);
})();
