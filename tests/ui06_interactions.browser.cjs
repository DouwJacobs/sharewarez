// Run only against the disposable populated UI-06 preview described in docs.
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = process.env.UI_AUDIT_BASE_URL;
assert(base, 'Supply the disposable UI_AUDIT_BASE_URL');
const light = fs.readFileSync(path.join(__dirname, 'ui06_matrix.browser.cjs'), 'utf8').match(/const light=`([^`]+)`/)[1];
(async () => {
 const browser = await chromium.launch({channel:'chrome',headless:true}); let checks=0;
 try {
  const page=await browser.newPage({serviceWorkers:'block',viewport:{width:390,height:844}});
  await page.goto(base+'/_preview/session'); const m=await(await page.request.get(base+'/_preview/manifest')).json();
  // Intercept every game mutation; role/view changes affect only the preview.
  await page.route('**/*',r=>r.request().method()==='POST'?r.fulfill({json:{success:false,message:'Simulated failure'}}):r.continue());
  for(const role of ['admin','member']) for(const theme of ['default','Ember','light']) {
   await page.goto(base+'/_preview/session?role='+role+'&theme='+(theme==='light'?'default':theme));
   for(const route of ['/library','/favorites','/game_details/'+m.game]) {
    await page.goto(base+route);await page.waitForTimeout(400);
    if(theme==='light')await page.addStyleTag({content:light});
    const trigger=page.locator('[id^="menuButton-"]').first();await trigger.press('Enter');
    const menu=page.locator('.popup-menu:visible');await menu.waitFor();
    assert.equal(await menu.locator('.delete-game').count(),role==='admin'?1:0);
    assert.equal(await menu.locator('a.menu-button').count(),1);
    await menu.locator('.menu-button').first().press('Tab');
    assert(await menu.evaluate(e=>e.contains(document.activeElement)));
    await page.keyboard.press('Escape');assert.equal(await trigger.getAttribute('aria-expanded'),'false');
    assert(await trigger.evaluate(e=>e===document.activeElement));checks++;
   }
  }
  await page.goto(base+'/_preview/session?role=admin&theme=default');
  await page.goto(base+'/edit_game_images/'+m.game);await page.waitForTimeout(500);
  assert(await page.locator('#image-editor-list img').evaluateAll(xs=>xs.length>=2&&xs.every(x=>x.complete&&x.naturalWidth>0)));
  await page.route('**/refresh_game_images/**',r=>r.fulfill({status:200,json:{status:'info'}}));
  await page.route('**/check_image_refresh_progress/**',r=>r.fulfill({status:200,json:{
   status:'in_progress',phase:'downloading',message:'Downloading the complete queued image set…',
   progress:82,total:10,processed:4,downloaded:3,failed:1,
  }}));
  await page.locator('#refresh-editor-images').click();
  await page.waitForFunction(()=>document.querySelector('#image-refresh-track')?.getAttribute('aria-valuenow')==='82');
  assert.equal(await page.locator('#image-refresh-phase').textContent(),'Downloading images');
  assert.equal(await page.locator('#image-refresh-percent').textContent(),'82%');
  assert.equal(await page.locator('#image-refresh-counts').textContent(),'4 of 10 queued images processed · 3 downloaded · 1 failed');
  assert.equal(await page.locator('#image-refresh-fill').evaluate(e=>e.style.width),'82%');checks++;
  await page.route('**/upload_image/**',r=>r.fulfill({status:400,json:{error:'Simulated upload failure with a detailed explanation. '.repeat(12)}}));
  const file={name:'test.png',mimeType:'image/png',buffer:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jR1kAAAAASUVORK5CYII=','base64')};
  await page.locator('#file-input').setInputFiles(file);await page.locator('#upload-button').click();
  const modal=page.locator('#errorModal');await modal.waitFor({state:'visible'});await page.waitForTimeout(400);
  assert(await modal.locator('.modal-content').evaluate(e=>{const r=e.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth&&r.top>=0&&r.bottom<=innerHeight}));
  await modal.getByRole('button',{name:'Close',exact:true}).last().press('Tab');assert(await modal.evaluate(e=>e.contains(document.activeElement)));
  await page.keyboard.press('Shift+Tab');assert(await modal.getByRole('button',{name:'Close',exact:true}).last().evaluate(e=>e===document.activeElement));
  await page.keyboard.press('Escape');await modal.waitFor({state:'hidden'});checks++;
  await page.emulateMedia({reducedMotion:'reduce'});await page.goto(base+'/game_edit/'+m.game);
  assert(await page.locator('#content').evaluate(e=>parseFloat(getComputedStyle(e).animationDuration)<=0.001));
  await page.locator('.game-edit-actions--bottom').scrollIntoViewIfNeeded();
  assert(await page.locator('.game-edit-actions--bottom').evaluate(e=>e.getBoundingClientRect().bottom<=innerHeight-60));checks++;
  await page.goto(base+'/admin/manage_invites');
  assert(await page.locator('.table-responsive').evaluate(e=>e.scrollWidth>e.clientWidth&&getComputedStyle(e).overflowX==='auto'));
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));checks++;
  await page.goto(base+'/library?genre=UI06NoSuchGenre&filters=1');
  assert.equal(await page.locator('.game-card').count(),0);checks++;
  await page.goto(base+'/library?filters=clear');
  await page.route('**/library/game-actions/**',async r=>{await new Promise(resolve=>setTimeout(resolve,400));await r.fulfill({status:500,body:'Simulated menu failure'});});
  const loadingTrigger=page.locator('[id^="menuButton-"]').first();await loadingTrigger.click();
  assert.equal(await loadingTrigger.getAttribute('aria-busy'),'true');await page.waitForTimeout(650);
  assert.equal(await loadingTrigger.getAttribute('aria-busy'),null);assert.equal(await loadingTrigger.getAttribute('aria-expanded'),'false');checks++;
  for(const theme of ['default','Ember','light']) {
   await page.goto(base+'/_preview/session?role=admin&theme='+(theme==='light'?'default':theme));await page.goto(base+'/game_edit/'+m.game);
   if(theme==='light')await page.addStyleTag({content:light});await page.waitForTimeout(400);
   const contrast=await page.locator('.btn-primary').first().evaluate(e=>{
    const c=getComputedStyle(e), canvas=document.createElement('canvas'),ctx=canvas.getContext('2d');
    const rgb=value=>{ctx.clearRect(0,0,1,1);ctx.fillStyle=value;ctx.fillRect(0,0,1,1);return [...ctx.getImageData(0,0,1,1).data].slice(0,3)};
    const lum=a=>a.map(v=>v/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((a,v,i)=>a+v*[.2126,.7152,.0722][i],0);
    const fg=lum(rgb(c.color));const colors=c.backgroundImage.match(/color\(srgb [^)]+\)|rgba?\([^)]+\)/g)||[c.backgroundColor];
    return Math.min(...colors.map(value=>{const bg=lum(rgb(value));return(Math.max(fg,bg)+.05)/(Math.min(fg,bg)+.05)}));
   });assert(contrast>=4.5,theme+' primary contrast '+contrast);checks++;
   if(theme==='light')assert.equal(await page.locator('.btn-secondary').first().evaluate(e=>getComputedStyle(e).color),'rgb(23, 32, 43)');
  }
  console.log(`${checks} UI-06 interaction/contrast scenarios passed`);
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
