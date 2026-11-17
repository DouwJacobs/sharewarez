// Run against a disposable authenticated preview, never a production instance.
const assert = require('node:assert/strict');
const path = require('node:path');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.UI_AUDIT_BASE_URL;
const sessionPath = process.env.UI_AUDIT_SESSION_PATH || '/_preview/session';
assert(base, 'Set UI_AUDIT_BASE_URL to a disposable preview');

(async () => {
    const browser = await chromium.launch({headless: true});
    try {
        for (const javaScriptEnabled of [true, false]) {
            const context = await browser.newContext({javaScriptEnabled, serviceWorkers: 'block'});
            const page = await context.newPage();
            for (const viewport of [{width: 1440, height: 1000}, {width: 390, height: 844}]) {
                await page.setViewportSize(viewport);
                await page.goto(base + sessionPath);
                await page.goto(base + '/admin/scan_management?active_tab=manual');
                await page.locator('#manualLibraryUuid').selectOption({index: 0});
                await page.locator('#manualFolderPath').fill('/tmp/manual-scan-browser-test');
                if (javaScriptEnabled && process.env.UI_AUDIT_SCREENSHOT_DIR) {
                    await page.screenshot({path: path.join(process.env.UI_AUDIT_SCREENSHOT_DIR,
                        `manual-scan-${viewport.width}.png`), fullPage: true});
                }
                await page.locator('#manualScanForm').evaluate(form => {
                    const result = document.createElement('iframe');
                    result.name = 'scanResult';
                    result.hidden = true;
                    document.body.appendChild(result);
                    form.target = result.name;
                });
                let postBody;
                await page.route('**/admin/scan_management?*', async route => {
                    if (route.request().method() !== 'POST') return route.continue();
                    postBody = route.request().postData();
                    await route.fulfill({status: 200, body: 'Submission captured'});
                });
                await Promise.all([
                    page.waitForResponse(response => response.request().method() === 'POST'),
                    page.locator('#manualScanSubmitBtn').click(),
                ]);
                if (javaScriptEnabled) {
                    assert(await page.locator('#manualScanSubmitBtn').isDisabled());
                    assert(await page.locator('#manualScanProgress').isVisible());
                    assert.equal(await page.locator('#manualScanForm').getAttribute('aria-busy'), 'true');
                }
                assert.deepEqual(new URLSearchParams(postBody).getAll('submit'), ['ManualScan']);
                await page.unroute('**/admin/scan_management?*');
                console.log(`Manual scan POST passed: ${viewport.width}px, JavaScript ${javaScriptEnabled}`);
            }
            await context.close();
        }
    } finally {
        await browser.close();
    }
})().catch(error => {console.error(error); process.exitCode = 1;});
