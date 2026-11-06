/* Reconcile only the current bounded query; terminal outcomes share server HTML. */
(() => {
    'use strict';
    const region = document.getElementById('deliveryResults');
    if (!region) return;
    const ui = window.DownloadLive;
    const query = Object.fromEntries(new URLSearchParams(window.location.search));
    query.view = region.dataset.view;
    const url = `/admin/download-delivery/status?${new URLSearchParams(query)}`;
    let pending = null, lastHTML = region.innerHTML;
    const connection = document.getElementById('activeTransferConnection');
    const render = data => {
        // Keep active form input, selection, modal and bulk selections intact.
        if (!data.html || document.hidden || region.contains(document.activeElement)
            || document.querySelector('.modal.show')
            || region.querySelector('.download-row-select:checked')) return;
        const noun = region.dataset.view === 'activity' ? 'attempt' : 'link';
        ui.text(document.querySelector('.downloads-page-header .ui-page-count'), `${data.total} ${noun}${data.total === 1 ? '' : 's'}`);
        const selection = window.getSelection();
        if (selection && !selection.isCollapsed && selection.anchorNode && region.contains(selection.anchorNode)) return;
        if (data.html !== lastHTML) {
            // The fragment is same-origin Jinja HTML with all user fields escaped.
            region.innerHTML = data.html;
            lastHTML = data.html;
            document.dispatchEvent(new Event('delivery-updated'));
        }
    };
    const refresh = () => {
        if (pending || document.hidden) return;
        pending = new AbortController();
        const timer = setTimeout(() => pending?.abort(), 10000);
        ui.json(url, pending.signal).then(render).catch(() => {
            ui.text(connection, 'Refresh interrupted · retrying');
        }).finally(() => { clearTimeout(timer); pending = null; });
    };
    ui.connect({view: query.view, query, render: data => data.html ? render(data) : refresh(),
        status: text => ui.text(connection, text), poll: signal => ui.json(url, signal)});
    document.addEventListener('visibilitychange', () => { if (document.hidden) pending?.abort(); });
    window.addEventListener('pagehide', () => pending?.abort());
})();
