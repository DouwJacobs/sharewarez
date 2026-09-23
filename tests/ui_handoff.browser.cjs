// Opt-in regression against a disposable authenticated preview. All POSTs are
// intercepted; provider responses are synthetic. No game mutation reaches Flask.
// UI_AUDIT_BASE_URL and UI_AUDIT_GAME_UUID are required. PLAYWRIGHT_MODULE may
// identify an installed Playwright module when it is outside Node's search path.
const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.UI_AUDIT_BASE_URL;
const uuid = process.env.UI_AUDIT_GAME_UUID;
assert(base && uuid, 'Use an explicitly disposable preview URL and game UUID');

(async () => {
    const browser = await chromium.launch({channel: 'chrome', headless: true});
    let checks = 0;
    try {
        const page = await browser.newPage({serviceWorkers: 'block', viewport: {width: 1440, height: 1000}});
        let posts = [];
        await page.route('**/*', route => {
            if (route.request().method() !== 'POST') return route.continue();
            posts.push(route.request().postData());
            return route.fulfill({status: 200, body: 'Intercepted test submission'});
        });
        await page.goto(base + '/_preview/session');
        const edit = async () => {
            await page.goto(base + '/game_edit/' + uuid);
            await page.waitForLoadState('networkidle');
            posts = [];
        };
        for (const action of ['save', 'save_and_refresh', 'enter']) {
            await edit();
            await page.locator('.game-edit-identification > summary').click();
            await page.locator('#igdb_id').fill('2000000421');
            await page.locator('#full_disk_path').fill('/tmp/browser-regression-game');
            await page.locator('#name').fill('Browser regression draft');
            if (action === 'enter') await page.locator('#name').press('Enter');
            else await page.locator('.game-edit-actions--top [value="' + action + '"]').click();
            await page.waitForURL(url => !url.pathname.includes('game_edit') || posts.length > 0);
            assert.equal(posts.length, 1);
            assert.equal(new URLSearchParams(posts[0]).get('action'), action === 'enter' ? 'save' : action);
            checks++;
        }
        await edit();
        await page.locator('#name').fill('');
        assert(await page.locator('.game-save-action').evaluateAll(xs => xs.every(x => x.disabled)));
        await page.locator('#name').press('Enter');
        assert.equal(posts.length, 0);
        checks++;

        await edit();
        await page.locator('.game-edit-identification > summary').click();
        await page.locator('#igdb_id').fill('2000000421');
        await page.locator('#full_disk_path').fill('/tmp/browser-regression-game');
        const submissions = await page.evaluate(() => {
            const states = [];
            const form = document.querySelector('.game_edit-form');
            document.addEventListener('submit', event => {
                states.push(event.defaultPrevented);
                event.preventDefault(); // Observe the handler without navigating.
            });
            form.requestSubmit();
            form.requestSubmit();
            return states;
        });
        assert.deepEqual(submissions, [false, true]);
        checks++;

        await edit();
        await page.route('**/api/search_igdb_by_name**', r => r.fulfill({json: {results: [{id: 123456, name: 'Provider replacement', summary: 'Provider text'}]}}));
        await page.route('**/api/get_cover_thumbnail**', r => r.fulfill({json: {error: 'No cover'}}));
        await page.getByRole('button', {name: 'Search IGDB by name'}).click();
        const result = page.locator('.search-result-item');
        await result.waitFor();
        assert.equal(await result.evaluate(x => x.tagName), 'BUTTON');
        await result.press('Enter');
        assert.equal(await page.locator('#name').inputValue(), 'Provider replacement');
        assert(await page.evaluate(() => {
            const event = new Event('beforeunload', {cancelable: true});
            window.dispatchEvent(event);
            return event.defaultPrevented;
        }));
        checks++;
        await page.getByRole('button', {name: 'Search IGDB by name'}).click();
        await result.waitFor();
        page.once('dialog', dialog => dialog.dismiss());
        await page.locator('#summary').fill('Keep my draft');
        await result.press('Space');
        assert.equal(await page.locator('#summary').inputValue(), 'Keep my draft');
        checks++;

        // Custom identity must protect a dirty draft and mark a clean form dirty.
        await edit();
        await page.locator('.game-edit-identification > summary').click();
        await page.locator('#add-non-existing-game').click();
        assert.equal(await page.locator('#igdb_id').inputValue(), '');
        assert.equal(await page.locator('#manual_identity').inputValue(), '1');
        assert(await page.evaluate(() => {
            const e = new Event('beforeunload', {cancelable: true});
            window.dispatchEvent(e); return e.defaultPrevented;
        }));
        checks++;

        await edit();
        await page.route('**/api/search_igdb_by_id**', r => r.fulfill({json: {name: 'Lookup replacement', summary: 'Lookup summary'}}));
        await page.locator('.game-edit-identification > summary').click();
        await page.locator('#igdb_id').fill('123456');
        page.once('dialog', dialog => dialog.dismiss());
        await page.locator('#search-igdb-btn').click();
        await page.waitForTimeout(600);
        assert.notEqual(await page.locator('#name').inputValue(), 'Lookup replacement');
        page.once('dialog', dialog => dialog.accept());
        await page.locator('#search-igdb-btn').click();
        await page.waitForTimeout(600);
        assert.equal(await page.locator('#name').inputValue(), 'Lookup replacement');
        checks++;

        // Model a server validation response without writing a record.
        await page.route('**/game_edit/' + uuid, async route => {
            const response = await route.fetch();
            let html = await response.text();
            assert.match(html, /<main[^>]*game-identify-page[^>]*>/);
            html = html.replace(/(<main[^>]*game-identify-page[^>]*>)/, '$1<div class="game-edit-error-summary"><a href="#igdb_id">Invalid ID</a></div><div class="field-error" id="igdb_id-errors">Invalid ID</div>');
            await route.fulfill({response, body: html});
        });
        await edit();
        assert(await page.locator('.game-edit-identification').evaluate(x => x.open), await page.evaluate(() => JSON.stringify({url: location.href, errors: document.querySelectorAll('.field-error').length, summary: document.querySelectorAll('.game-edit-error-summary').length, field: document.querySelector('#igdb_id').outerHTML})));
        assert(await page.locator('#igdb_id').evaluate(x => x === document.activeElement));
        assert.equal(await page.locator('#igdb_id').getAttribute('aria-invalid'), 'true');
        assert.match(await page.locator('#igdb_id').getAttribute('aria-describedby'), /igdb_id-errors/);
        checks++;

        const library = await browser.newPage({serviceWorkers: 'block'});
        await library.route('**/*', route => route.request().method() === 'POST'
            ? route.fulfill({json: {success: true}}) : route.continue());
        await library.goto(base + '/_preview/session');
        for (const width of [1440, 390, 320]) {
            await library.setViewportSize({width, height: width === 1440 ? 1000 : 844});
            await library.goto(base + '/library?view=list');
            await library.waitForLoadState('networkidle');
            await library.getByRole('button', {name: 'List view', exact: true}).click();
            const geometry = await library.evaluate(() => {
                const card = document.querySelector('.game-card');
                const a = card.querySelector('.button-glass-hamburger').getBoundingClientRect();
                const b = card.querySelector('.favorite-btn').getBoundingClientRect();
                return {overlap: Math.min(a.right, b.right) - Math.max(a.left, b.left),
                    overflow: document.documentElement.scrollWidth > innerWidth};
            });
            assert(geometry.overlap <= 0, JSON.stringify({width, ...geometry}));
            assert.equal(geometry.overflow, false);
            if (process.env.UI_AUDIT_SCREENSHOTS) {
                await library.screenshot({path: process.env.UI_AUDIT_SCREENSHOTS + '/list-' + width + '.png', fullPage: true});
            }
            checks++;
        }
        await library.route('**/library/game-actions/**', async route => {
            await new Promise(resolve => setTimeout(resolve, 500));
            await route.continue();
        });
        const trigger = library.locator('[id^="menuButton-"]').first();
        await trigger.click();
        await library.keyboard.press('Escape');
        await library.waitForTimeout(900);
        assert.equal(await trigger.getAttribute('aria-expanded'), 'false');
        assert.equal(await trigger.getAttribute('aria-busy'), null);
        assert.equal(await library.locator('.popup-menu').isVisible(), false);
        assert.equal(await trigger.getAttribute('aria-haspopup'), null);
        checks++;
        await trigger.click();
        await library.locator('.popup-menu').waitFor({state: 'visible'});
        await library.locator('.popup-menu .menu-button').first().press('Escape');
        assert.equal(await trigger.getAttribute('aria-expanded'), 'false');
        assert(await trigger.evaluate(x => x === document.activeElement));
        checks++;

        let removals = 0;
        await library.route('**/delete_game/**', async route => {
            removals++;
            await new Promise(resolve => setTimeout(resolve, 500));
            await route.fulfill({json: {success: false, message: 'Simulated failure'}});
        });
        await trigger.click();
        const remove = library.locator('.delete-game');
        await remove.dblclick();
        assert(await remove.isDisabled());
        assert.equal(await remove.getAttribute('aria-busy'), 'true');
        await library.waitForTimeout(800);
        assert.equal(removals, 1);
        assert.equal(await remove.isDisabled(), false);
        await remove.click();
        await library.waitForTimeout(800);
        assert.equal(removals, 2, 'Failure must allow an intentional retry');
        checks++;
        await library.route('**/api/get_libraries', r => r.fulfill({json: [{uuid: 'test-library', name: 'Test destination'}]}));
        let moves = 0;
        await library.route('**/api/move_game_to_library', async r => {
            moves++;
            await new Promise(resolve => setTimeout(resolve, 300));
            await r.fulfill({json: {success: false, message: 'Simulated move failure'}});
        });
        await library.locator('.move-library').click();
        const destination = library.getByRole('button', {name: 'Test destination', exact: true});
        await destination.waitFor();
        library.once('dialog', dialog => dialog.accept());
        await destination.press('Enter');
        assert(await destination.isDisabled());
        await library.waitForTimeout(500);
        assert.equal(moves, 1);
        assert.equal(await destination.isDisabled(), false);
        checks++;
        if (process.env.UI_AUDIT_SCREENSHOTS) {
            const visual = await browser.newPage({viewport: {width: 390, height: 844}});
            await visual.goto(base + '/_preview/session');
            await visual.goto(base + '/game_edit/' + uuid);
            await visual.waitForLoadState('networkidle');
            await visual.screenshot({path: process.env.UI_AUDIT_SCREENSHOTS + '/editor-390.png', fullPage: true});
            await visual.close();
        }
        console.log(`${checks} browser regression scenarios passed`);
    } finally {
        await browser.close();
    }
})().catch(error => { console.error(error); process.exitCode = 1; });
