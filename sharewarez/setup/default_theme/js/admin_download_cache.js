document.addEventListener('DOMContentLoaded', () => {
    'use strict';
    const ui = window.DownloadLive, rows = new Map();
    const connection = document.getElementById('cacheConnection');
    let initialCount = null;
    const bytes = value => {
        let size = Math.max(0, Number(value) || 0), unit = 0;
        const units = ['B','KiB','MiB','GiB','TiB'];
        while (size >= 1024 && unit < units.length - 1) { size /= 1024; unit++; }
        return size.toFixed(unit ? 1 : 0) + ' ' + units[unit];
    };
    document.querySelectorAll('[data-archive-id]').forEach(row => {
        const badge = row.querySelector('.download-status');
        const texts = [...badge.childNodes].filter(node => node.nodeType === 3);
        const label = document.createElement('span');
        label.textContent = texts.map(node => node.textContent).join('').trim();
        texts.forEach(node => node.remove()); badge.append(label);
        rows.set(row.dataset.archiveId,{row,badge,label});
    });
    const control = (view, name, visible, disabled = false) => {
        const form = view.row.querySelector('[data-cache-action="' + name + '"]');
        const button = form.querySelector('button');
        if ((!visible || disabled) && form.contains(document.activeElement)) {
            view.row.querySelector('.cache-state-cell').focus({preventScroll:true});
        }
        form.hidden = !visible; button.disabled = disabled;
        button.setAttribute('aria-disabled',String(disabled));
        return form;
    };
    const render = payload => {
        if (!payload.summary || !Array.isArray(payload.archives)) throw new Error('Invalid archive snapshot');
        const data = payload.summary, counts = data.counts;
        for (const [id,value] of Object.entries({cacheUsed:bytes(data.used_bytes),cacheFree:bytes(data.free_bytes),
            cacheReclaimable:bytes(data.reclaimable_bytes),cacheReady:counts.ready + ' archive' + (counts.ready === 1 ? '' : 's'),
            cacheBuilding:counts.queued + counts.building,cacheFailed:counts.failed})) ui.text(document.getElementById(id),value);
        const health = document.querySelector('.cache-health');
        health.classList.toggle('cache-health--degraded',!data.healthy);
        ui.text(document.getElementById('cache-health-title'),data.healthy ? 'Cache ready' : 'Cache needs attention');
        ui.text(health.querySelector('.cache-section-heading h2 + p'),data.message);
        const total = Object.values(counts).reduce((sum,count) => sum + count,0);
        if (initialCount === null) initialCount = total;
        document.getElementById('cacheInventoryChanged').hidden = total === initialCount;
        const archives = new Map(payload.archives.map(item => [item.id,item]));
        rows.forEach((view,id) => {
            const item = archives.get(id), state = item?.state || 'removed';
            const busy = ['queued','building'].includes(state), present = Boolean(item);
            view.badge.className = 'ui-status download-status download-status--' + state;
            ui.text(view.label,state.charAt(0).toUpperCase() + state.slice(1));
            const find = selector => view.row.querySelector(selector);
            const failure = find('.cache-error'); failure.hidden = !item?.failure_message;
            ui.text(failure,item?.failure_message || '');
            find('.cache-row-progress').hidden = !busy;
            find('.cache-row-progress span').style.width = (item?.progress || 0) + '%';
            ui.text(find('.cache-progress-label'),busy
                ? (item.progress || 0) + '% · ' + bytes(item.bytes_written) + (item.progress_message ? ' · ' + item.progress_message : '') : '—');
            if (item) {
                ui.text(find('.cache-file-meta'),item.file_count + ' file' + (item.file_count === 1 ? '' : 's')
                    + (item.pinned ? ' · Pinned' : '') + (item.active_leases ? ' · ' + item.active_leases + ' active transfer(s)' : ''));
                ui.text(find('.cache-source-size'),bytes(item.source_bytes));
                ui.text(find('.cache-archive-size'),item.archive_bytes ? bytes(item.archive_bytes) : '—');
                ui.text(find('.cache-last-used'),item.last_accessed_at ? new Date(item.last_accessed_at).toLocaleString() : 'Never');
            }
            const pin = control(view,'pin',present);
            if (item) { pin.querySelector('input[name="pinned"]').value = String(!item.pinned); ui.text(pin.querySelector('button'),item.pinned ? 'Unpin' : 'Pin'); }
            const cancel = control(view,'cancel',busy,Boolean(item?.cancel_requested));
            ui.text(cancel.querySelector('button'),item?.cancel_requested ? 'Cancelling…' : 'Cancel');
            control(view,'retry',state === 'failed');
            control(view,'evict',present,busy || state === 'deleting' || Boolean(item?.active_leases));
        });
    };
    const ids = [...rows.keys()];
    ui.connect({view:'cache',ids,render,status:message => ui.text(connection,message),
        poll:signal => ui.json('/admin/download-cache/status?ids=' + ids.join(','),signal)});
});
