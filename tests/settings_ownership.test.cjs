const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = file => fs.readFileSync(path.join(__dirname, '../sharewarez/setup/default_theme/js', file), 'utf8');
function node(extra = {}) {
    const listeners = {}, classes = new Set();
    return {dataset:{}, hidden:false, listeners,
        classList:{toggle(name, on) { if (on) classes.add(name); else classes.delete(name); }, contains:name => classes.has(name)},
        addEventListener(name, handler) { listeners[name] = handler; }, setAttribute() {}, ...extra};
}
function input(id, type, value) {
    let text = String(value);
    return node({id, type, checked:!!value, get value() { return text; }, set value(value) { text = String(value); }});
}
function settingsHarness() {
    const fields = {siteUrl:input('siteUrl','url','https://old.test'),
        downloadBandwidthLimitMbps:input('downloadBandwidthLimitMbps','number',5),
        downloadQueueWaitSeconds:input('downloadQueueWaitSeconds','number',7)};
    // Define DOM-like string setters (object spread would otherwise copy values).
    for (const field of Object.values(fields)) {
        let text = String(field.value);
        Object.defineProperty(field,'value',{get:() => text,set:value => { text = String(value); }});
    }
    const groups = {general:[fields.siteUrl],downloads:[fields.downloadBandwidthLimitMbps,fields.downloadQueueWaitSeconds]};
    const panels = Object.entries(groups).map(([section, controls]) => node({dataset:{settingsPanel:section},querySelectorAll:() => controls}));
    const buttons = Object.keys(groups).map(section => node({dataset:{settingsTarget:section}}));
    const submit = node(), status = node({style:{}}), calls = [];
    const form = node({querySelector:() => submit,querySelectorAll:selector => selector.includes('data-settings-panel') ? panels : selector.includes('data-settings-target') ? buttons : []});
    let current = new URL('http://localhost/admin/settings?section=downloads'), ready;
    const window = {get location() {return current;},addEventListener() {}};
    const elements = {...fields,settingsForm:form,settingsSavedNotification:status,currentSettings:{textContent:JSON.stringify({siteUrl:'https://old.test',downloadBandwidthLimitMbps:5,downloadQueueWaitSeconds:7})}};
    const h = {fields,calls,status,form,submit,respond:async () => ({ok:true,json:async () => ({message:'Saved'})}),
        click:section => buttons.find(button => button.dataset.settingsTarget === section).listeners.click(),
        save:() => form.listeners.submit({preventDefault(){}})};
    vm.runInNewContext(source('admin_manage_server_settings.js'), {window,URL,history:{pushState(a,b,url){current=new URL(url,current);}},
        document:{addEventListener(name,handler){ready=handler;},getElementById:id => elements[id],querySelector:() => ({dataset:{initialSettingsSection:'general'}})},
        CSRFUtils:{getHeaders:headers => headers},fetch:async (url, options) => {calls.push(JSON.parse(options.body));return h.respond();}});
    ready(); return h;
}
test('a stale Downloads form sends only changed own keys and preserves numeric zero', async () => {
    const h = settingsHarness();
    assert.equal(h.fields.siteUrl.disabled,true);
    assert.equal(h.fields.downloadBandwidthLimitMbps.disabled,false);
    h.fields.siteUrl.value = 'https://unsaved-other-category.test';
    h.fields.downloadBandwidthLimitMbps.value = '0';
    await h.save();
    assert.deepEqual(h.calls,[{section:'downloads',settings:{downloadBandwidthLimitMbps:0}}]);
    await h.save(); assert.equal(h.calls.length,1);
    h.click('general'); await h.save();
    assert.deepEqual(h.calls[1],{section:'general',settings:{siteUrl:'https://unsaved-other-category.test'}});
});
test('failed saves retain the pending patch for retry', async () => {
    const h = settingsHarness();h.fields.downloadQueueWaitSeconds.value='0';
    h.respond=async () => ({ok:false,json:async () => ({error:'Try again'})});
    await h.save();assert.equal(h.status.textContent,'Try again');
    h.respond=async () => ({ok:true,json:async () => ({message:'Saved'})});
    await h.save();assert.deepEqual(h.calls[0],h.calls[1]);assert.equal(h.submit.disabled,false);
});
test('edits made during a save remain unsaved and duplicate submissions are suppressed', async () => {
    const h = settingsHarness();let release;
    h.respond=() => new Promise(resolve => {release=resolve;});
    h.fields.downloadBandwidthLimitMbps.value='2';
    const pending=h.save();await h.save();assert.equal(h.calls.length,1);
    h.fields.downloadBandwidthLimitMbps.value='3';
    release({ok:true,json:async () => ({message:'Saved'})});await pending;
    h.respond=async () => ({ok:true,json:async () => ({message:'Saved'})});
    await h.save();assert.deepEqual(h.calls[1].settings,{downloadBandwidthLimitMbps:3});
});
function tabsHarness(hash, flash='') {
    let ready, active;
    const listeners={}, history=[], location={hash};
    const buttons=['email','webhooks','igdb','discord','future'].map(name => node({getAttribute:() => '#'+name}));
    const context={window:{location,addEventListener:(name,handler) => {listeners[name]=handler;}},
        history:{replaceState(a,b,hash){location.hash=hash;},pushState(a,b,hash){history.push(hash);location.hash=hash;}},
        document:{addEventListener(name,handler){ready=handler;},querySelectorAll:() => buttons,querySelector:() => ({dataset:{initialIntegrationTab:flash}})},
        bootstrap:{Tab:{getOrCreateInstance:button => ({show(){active=button.getAttribute();button.listeners['shown.bs.tab']({target:button});}})}}};
    vm.runInNewContext(source('integrations_tabs.js'),context);ready();
    return {history,location,get active(){return active;},navigate(hash){location.hash=hash;listeners.hashchange();}};
}
test('every actual integration control, including Webhooks, survives bookmark restoration', () => {
    for (const name of ['email','webhooks','igdb','discord','future']) assert.equal(tabsHarness('#'+name).active,'#'+name);
});
test('legacy fragments, flash routing and history use one tab controller', () => {
    assert.equal(tabsHarness('#smtp').active,'#email');assert.equal(tabsHarness('#metadata').active,'#igdb');
    assert.equal(tabsHarness('', '#discord').active,'#discord');assert.equal(tabsHarness('#webhooks','#discord').active,'#webhooks');
    const h=tabsHarness('#webhooks');h.navigate('#discord');h.navigate('#webhooks');
    assert.equal(h.active,'#webhooks');assert.deepEqual(h.history,[]);
});
