// Requires the isolated UI-06 populated preview manifest; see docs/UI06_VERIFICATION.md.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs=require('node:fs');
const base=process.env.UI_AUDIT_BASE_URL, out=process.env.UI_AUDIT_SCREENSHOTS; if (!base || !out) throw new Error('Supply a disposable UI_AUDIT_BASE_URL and UI_AUDIT_SCREENSHOTS directory');fs.mkdirSync(out,{recursive:true});
const light=`:root {--theme-text-primary:#17202b;--theme-text-secondary:#384454;--theme-card-top:#ffffff;--theme-card-bottom:#edf1f7;--theme-panel-bg:#f4f6fa;--theme-card-background:#f4f6fa;--theme-input-bg:#ffffff;--theme-border-color:#8995a5;--theme-accent:#254ca0;--theme-accent-color:#254ca0;--theme-accent-soft-rgb:37,76,160;--theme-color-scheme:light;--status-danger-color:#a61930;--semantic-danger:#a61930;--theme-accent-rgb:37,76,160;--theme-sidebar-top:#edf1f7;--theme-sidebar-bottom:#e1e6ef;--container-dark-primary:#f4f6fa;--modal-bg:#f4f6fa;--text-white:#17202b;--text-color:#17202b;--text-muted:#384454;--input-text-color:#17202b;--input-bg:#fff;--btn-secondary:#e1e6ef;} body{background:#e8edf5!important;color:#17202b}`;
(async()=>{const b=await chromium.launch({channel:'chrome',headless:true});const rows=[];try{
 const c=await b.newContext({serviceWorkers:'block'});const p=await c.newPage();await p.goto(base+'/_preview/session');const m=await(await p.request.get(base+'/_preview/manifest')).json();
 const admin=['/library?view=grid','/library?view=compact','/library?view=list','/favorites','/game_details/'+m.game,'/game_edit/'+m.game,'/edit_game_images/'+m.game,'/admin/game-requests/'+m.request,'/admin/issues/'+m.issue,'/admin/collections','/admin/collections/'+m.collection+'/edit','/library?collection=ui06-curated','/admin/manage_invites','/user/invites'];
 const member=['/library?view=grid','/library?view=compact','/library?view=list','/favorites','/game_details/'+m.game,'/requests','/issues/'+m.issue,'/library?collection=ui06-curated','/user/invites'];
 for(const role of ['admin','member'])for(const theme of ['default','Ember','light'])for(const width of [1440,390]){
  await p.setViewportSize({width,height:width===390?844:1000});await p.goto(base+'/_preview/session?role='+role+'&theme='+(theme==='light'?'default':theme));
  for(const [i,path]of(role==='admin'?admin:member).entries()){
   const errors=[];const onerror=e=>errors.push(e.message);p.on('pageerror',onerror);
   const r=await p.goto(base+path);await p.waitForTimeout(400);if(path.includes('view=')) {const view=path.split('view=')[1];await p.getByRole('button',{name:view[0].toUpperCase()+view.slice(1)+' view',exact:true}).click();} if(theme==='light')await p.addStyleTag({content:light});await p.waitForTimeout(350);
   const data=await p.evaluate(()=>{const visible=x=>x.getClientRects().length&&getComputedStyle(x).visibility!=='hidden';const overflow=[...document.querySelectorAll('#content *')].filter(x=>visible(x)&&x.getBoundingClientRect().right>innerWidth+2&&!x.closest('.popup-menu,.status-dropdown,.dropdown-menu')).slice(0,6).map(x=>({tag:x.tagName,cls:x.className,right:x.getBoundingClientRect().right}));return{title:document.title,overflow:document.documentElement.scrollWidth>innerWidth+1,offenders:overflow,small:[...document.querySelectorAll('.btn')].filter(x=>visible(x)&&!x.disabled&&x.getBoundingClientRect().height<(innerWidth<769?43:41)).map(x=>({text:x.textContent.trim(),height:x.getBoundingClientRect().height})).slice(0,8),images:document.querySelectorAll('.image-card,img').length,accent:getComputedStyle(document.documentElement).getPropertyValue('--theme-accent-rgb')}});
   const row={role,theme,width,path,status:r.status(),...data,errors};rows.push(row);
   await p.screenshot({path:out+'/'+role+'-'+theme+'-'+width+'-'+i+'.png',fullPage:true});p.off('pageerror',onerror);
   if(row.status!==200||row.overflow||row.small.length||errors.length)console.log(JSON.stringify(row));
  }
 }
 fs.writeFileSync(out+'/matrix.json',JSON.stringify(rows,null,2));console.log('Completed '+rows.length+' route/theme/viewport checks');if(rows.some(r=>r.status!==200||r.overflow||r.small.length||r.errors.length))throw new Error('UI matrix failed; inspect matrix.json');
}finally{await b.close()}})().catch(e=>{console.error(e);process.exitCode=1});
