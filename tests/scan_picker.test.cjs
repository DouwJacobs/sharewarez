// Run with node --test tests/scan_picker.test.cjs. No server or browser needed.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function picker() {
    class Element {
        constructor(markup = '') { this.markup = markup; this.children = []; this.attrs = {}; this.events = {}; }
        prop(key, value) { this.attrs[key] = value; return this; }
        attr(key, value) { this.attrs[key] = value; return this; }
        val(value) { if (value === undefined) return this.value; this.value = value; return this; }
        text(value) { this.label = value; return this; }
        empty() { this.children = []; return this; }
        append(child) { this.children.push(child); return this; }
        addClass(value) { this.className = value; return this; }
        removeClass() { return this; }
        remove() { return this; }
        on(event, callback) { this.events[event] = callback; return this; }
        trigger(event) { this.events[event]?.(); return this; }
        closest() { return form; }
        find() { return mode; }
    }
    const elements = new Map();
    const form = new Element();
    const mode = new Element().val('folders');
    const requests = [];
    const $ = selector => {
        if (selector.startsWith('<')) return new Element(selector);
        if (!elements.has(selector)) elements.set(selector, new Element());
        return elements.get(selector);
    };
    $.ajax = request => requests.push(request);
    const context = vm.createContext({$, document: {addEventListener() {}}, fileIcons: {default: 'fa-file'}});
    const source = fs.readFileSync(path.join(__dirname, '../sharewarez/setup/default_theme/js/admin_manage_scanjobs.js'), 'utf8');
    vm.runInContext(source.replace(/^import .*;\n/, ''), context);
    vm.runInContext("setupFolderBrowse('#browse', '#contents', '#spinner', '#up', '#input')", context);
    return {elements, requests, $, mode, setupSecond() {
        vm.runInContext("setupFolderBrowse('#browse2', '#contents2', '#spinner2', '#up2', '#input2')", context);
    }};
}

const result = (currentPath, items = []) => ({currentPath, items, skippedItems: 0, hasErrors: false});

test('late success and late error cannot overwrite the latest selection', () => {
    const p = picker();
    p.$('#browse').trigger('click');
    p.$('#browse').trigger('click');
    p.requests[1].success(result('new/'));
    p.requests[0].success(result('old/'));
    p.requests[0].error({responseJSON: {error: 'old error'}});
    assert.equal(p.$('#input').val(), 'new/');
    assert.equal(p.$('#contents').children.length, 2);
    assert.equal(p.$('#spinner').attrs.hidden, true);
});

test('failed navigation preserves draft, prior controls and cursor', () => {
    const p = picker();
    p.$('#browse').trigger('click');
    p.requests[0].success(result('parent/', [{name: 'child', isDir: true}]));
    const child = p.$('#contents').children[1];
    child.trigger('click');
    p.requests[1].error({responseJSON: {error: 'Denied'}});
    assert.equal(p.$('#input').val(), 'parent/');
    assert.equal(p.$('#contents').children[1], child);
    p.$('#up').trigger('click');
    assert.equal(p.requests[2].data.path, '');
});

test('root submits dot; filenames are text; file selection requires Files mode', () => {
    const p = picker();
    p.$('#browse').trigger('click');
    p.requests[0].success(result('', [{name: '<img onerror=alert(1)>.iso', isDir: false, size: 1}]));
    assert.equal(p.$('#input').val(), '.');
    const file = p.$('#contents').children[1];
    assert.equal(file.children[1].label, '<img onerror=alert(1)>.iso');
    assert.equal(file.markup, '<button type="button" class="btn btn-secondary">');
    file.trigger('click');
    assert.equal(p.$('#input').val(), '.');
    p.mode.val('files');
    file.trigger('click');
    assert.equal(p.$('#input').val(), '<img onerror=alert(1)>.iso');
});

test('two pickers have independent request generations', () => {
    const p = picker();
    p.setupSecond();
    p.$('#browse').trigger('click');
    p.$('#browse2').trigger('click');
    p.requests[1].success(result('second/'));
    p.requests[0].success(result('first/'));
    assert.equal(p.$('#input').val(), 'first/');
    assert.equal(p.$('#input2').val(), 'second/');
});
