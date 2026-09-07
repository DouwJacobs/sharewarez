const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../sharewarez/setup/default_theme/js/favorites_manager.js'), 'utf8');
function button() {
    const classes = new Set();
    return {
        dataset: {gameUuid: 'game-1', gameName: 'Example game', isFavorite: 'true'},
        attrs: {}, disabled: false,
        classList: {add: x => classes.add(x), remove: x => classes.delete(x), contains: x => classes.has(x), toggle: (x, on) => on ? classes.add(x) : classes.delete(x)},
        setAttribute(k, v) { this.attrs[k] = v; },
        removeAttribute(k) { delete this.attrs[k]; },
        addEventListener(_, fn) { this.click = () => fn({preventDefault() {}, stopPropagation() {}}); }
    };
}
async function exercise(route, fail = false) {
    const buttons = [button(), button()];
    let start, resolve, calls = 0;
    const notifications = [];
    const response = new Promise(r => {resolve = r;});
    vm.runInNewContext(source, {
        document: {addEventListener: (_, fn) => {start = fn;}, querySelectorAll: () => buttons, getElementById: () => null},
        window: {location: {pathname: route}},
        CSRFUtils: {getToken: () => 'test', getHeaders: h => h},
        MutationObserver: class {observe() {}},
        console: {log() {}, error() {}, warn() {}},
        $: {notify: (...args) => notifications.push(args)},
        fetch: () => {calls++; return response;}
    });
    start();
    const pending = buttons[0].click();
    assert.equal(buttons[0].disabled, true);
    assert.equal(buttons[1].disabled, true, 'all visible favorite controls share pending state');
    assert.equal(buttons[1].attrs['aria-busy'], 'true');
    await buttons[1].click();
    assert.equal(calls, 1, 'duplicate controls cannot submit twice while pending');
    resolve({ok: !fail, statusText: 'Unavailable', json: async () => ({is_favorite: false})});
    await pending;
    for (const b of buttons) {
        assert.equal(b.dataset.isFavorite, fail ? 'true' : 'false');
        assert.equal(b.attrs['aria-pressed'], fail ? 'true' : 'false');
    }
    assert.equal(buttons[0].disabled, false);
    assert.equal(buttons[0].attrs['aria-busy'], undefined);
    assert.equal(buttons[1].disabled, false);
    assert.equal(buttons[1].attrs['aria-busy'], undefined);
    assert.equal(notifications.at(-1)[1], fail ? 'error' : 'success');
}
(async () => {
    for (const route of ['/library', '/favorites', '/game_details/game-1']) {
        await exercise(route);
        await exercise(route, true);
    }
    console.log('Favorite behavior: 6 cases passed');
})().catch(error => {console.error(error); process.exitCode = 1;});
