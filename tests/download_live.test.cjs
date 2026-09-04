const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function harness() {
    const timers = new Map(), listeners = {}, sources = [], statuses = [], renders = [];
    let counter = 0, polling = 0;
    class EventSource {
        constructor(url) { this.url = url; this.handlers = {}; sources.push(this); }
        addEventListener(type, handler) { this.handlers[type] = handler; }
        close() { this.closed = true; }
        snapshot(data) { this.handlers.snapshot({data: JSON.stringify(data)}); }
    }
    const document = {hidden: false, addEventListener: (name, fn) => { listeners[name] = fn; },
        removeEventListener: name => { delete listeners[name]; }};
    const window = {EventSource, addEventListener() {}, removeEventListener() {}, getSelection: () => null};
    const context = {window, document, EventSource, URLSearchParams, AbortController,
        setTimeout: (fn, delay) => { const id = ++counter; timers.set(id, {fn, delay}); return id; },
        clearTimeout: id => timers.delete(id)};
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../sharewarez/setup/default_theme/js/download_live.js'), 'utf8'), context);
    const client = window.DownloadLive.connect({view: 'activity', poll: async () => { polling++; return {transfers: []}; },
        render: data => renders.push(data), status: value => statuses.push(value)});
    return {timers, sources, statuses, renders, document, listeners, client, ui: window.DownloadLive,
        polling: () => polling, async tick(delay) {
            const entry = [...timers].find(([, value]) => value.delay === delay);
            assert.ok(entry, `Expected timer ${delay}`); timers.delete(entry[0]); entry[1].fn();
            await new Promise(setImmediate);
        }};
}

test('healthy SSE renders snapshots without polling', () => {
    const h = harness();
    h.sources[0].snapshot({transfers: [{id: 1}]});
    assert.equal(h.renders.length, 1);
    assert.equal(h.polling(), 0);
    assert.equal(h.statuses.at(-1), 'Live updates connected');
    h.client.close(); assert.equal(h.timers.size, 0);
});

test('SSE failure falls back, then reconnects to fresh snapshots', async () => {
    const h = harness(); h.sources[0].onerror();
    await new Promise(setImmediate);
    assert.equal(h.polling(), 1); assert.equal(h.sources[0].closed, true);
    await h.tick(2000); assert.equal(h.polling(), 2);
    await h.tick(30000);
    h.sources[1].snapshot({transfers: [{id: 2}]});
    assert.equal(h.renders.at(-1).transfers[0].id, 2);
    assert.equal([...h.timers.values()].some(timer => timer.delay === 2000), false);
    h.client.close();
});

test('hidden page closes stream and suppresses stale callbacks', () => {
    const h = harness(); h.document.hidden = true; h.listeners.visibilitychange();
    h.sources[0].snapshot({transfers: [{id: 99}]});
    assert.equal(h.renders.length, 0); assert.equal(h.timers.size, 0);
    h.document.hidden = false; h.listeners.visibilitychange();
    assert.equal(h.sources.length, 2); h.client.close();
});

test('buffered or stalled stream switches to polling', async () => {
    const h = harness(); await h.tick(5000); assert.equal(h.polling(), 1); h.client.close();
    const live = harness(); live.sources[0].snapshot({transfers: []});
    await live.tick(25000); assert.equal(live.polling(), 1); live.client.close();
});

test('revoked access stops reconnects and polling', () => {
    const h = harness(); h.sources[0].handlers['access-revoked']();
    assert.equal(h.timers.size, 0); assert.equal(h.polling(), 0);
    h.document.hidden = false; h.listeners.visibilitychange();
    assert.equal(h.sources.length, 1); h.client.close();
});

test('duration and speed distinguish unknown from stalled', () => {
    const h = harness();
    assert.equal(h.ui.duration(1036), '17m 16s');
    assert.equal(h.ui.speed(null), '—');
    assert.equal(h.ui.speed(0), '0 B/s');
    assert.equal(h.ui.speed(1048576), '1.0 MiB/s'); h.client.close();
});
