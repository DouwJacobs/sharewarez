const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function harness(options = {}) {
    const listeners = {}, attributes = {}, copied = [], calls = [];
    let feedback, requests = 0;
    const createElement = tag => ({tag, dataset: {}, children: [], listeners: {}, textContent: '',
        setAttribute(name, value) { this[name] = value; },
        append(...children) { this.children.push(...children); },
        replaceChildren(...children) { this.children = children; this.textContent = ''; },
        addEventListener(name, handler) { this.listeners[name] = handler; }});
    const copyArea = {querySelector: () => feedback, append: element => { feedback = element; }};
    const link = {dataset: {cardMagnetUrl: '/authenticated-source'}, href: '/details#sources',
        closest: () => ({querySelector: () => copyArea}),
        getAttribute: name => attributes[name], setAttribute: (name, value) => { attributes[name] = value; },
        removeAttribute: name => { delete attributes[name]; }};
    const window = {location: {href: '/library'}};
    const magnet = 'magnet:?xt=urn:btih:' + '1'.repeat(40);
    const context = {window, CSRFUtils: {getHeaders: () => ({'X-CSRFToken': 'test'})}, document: {createElement, addEventListener: (name, handler) => { listeners[name] = handler; }},
        navigator: {clipboard: {writeText: async value => { copied.push(value); }}}, AbortSignal,
        fetch: async (...args) => {
            requests++;
            calls.push(args);
            return options.fetch ? options.fetch(...args) : {ok: true, json: async () => ({magnet})};
        }};
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../sharewarez/setup/default_theme/js/library_sources.js'), 'utf8'), context);
    const click = (extra = {}) => listeners.click({button: 0, target: {closest: () => options.noAction ? null : link},
        preventDefault() {}, stopPropagation() {}, ...extra});
    return {click, window, magnet, copied, attributes, calls, feedback: () => feedback, requests: () => requests};
}

test('single magnet opens the authenticated source without adding a card prompt or copy button', async () => {
    const h = harness();
    await h.click();
    assert.equal(h.requests(), 1);
    assert.equal(h.calls[0][1].method, 'POST');
    assert.equal(h.calls[0][1].headers['X-CSRFToken'], 'test');
    assert.equal(h.window.location.href, h.magnet);
    assert.equal(h.attributes['aria-busy'], undefined);
    assert.equal(h.feedback(), undefined);
    assert.deepEqual(h.copied, []);
});

test('multi-source links and modified clicks keep native navigation', async () => {
    const ordinary = harness({noAction: true});
    await ordinary.click();
    assert.equal(ordinary.requests(), 0);
    const modified = harness();
    await modified.click({ctrlKey: true});
    assert.equal(modified.requests(), 0);
});

test('a failed source lookup is explained and can be retried', async () => {
    const h = harness({fetch: async () => ({ok: false})});
    await h.click();
    assert.match(h.feedback().textContent, /Source unavailable/);
    assert.equal(h.window.location.href, '/library');
    assert.equal(h.attributes['aria-busy'], undefined);
    await h.click();
    assert.equal(h.requests(), 2);
});

test('timeouts release the busy state instead of leaving a stuck badge', async () => {
    const h = harness({fetch: async () => { const error = new Error('timeout'); error.name = 'TimeoutError'; throw error; }});
    await h.click();
    assert.match(h.feedback().textContent, /timed out/);
    assert.equal(h.attributes['aria-busy'], undefined);
});

test('an unexpected protocol is never opened', async () => {
    const h = harness({fetch: async () => ({ok: true, json: async () => ({magnet: 'javascript:bad()'})})});
    await h.click();
    assert.equal(h.window.location.href, '/library');
    assert.match(h.feedback().textContent, /Source unavailable/);
});

test('repeated clicks share one in-flight lookup', async () => {
    let resolve;
    const h = harness({fetch: () => new Promise(done => { resolve = done; })});
    const first = h.click();
    await h.click();
    assert.equal(h.requests(), 1);
    resolve({ok: true, json: async () => ({magnet: h.magnet})});
    await first;
    assert.equal(h.window.location.href, h.magnet);
});
