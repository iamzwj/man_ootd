const $=s=>document.querySelector(s);
let state={authenticated:false,profile:{photos:[],views:{}},jobs:[]},pendingReference=null,pendingAction=null,busy=false,polling=false,activeTab='profile',authBusy=false,resendUntil=0;
const labels={front:'正面',side:'侧面',back:'背面',face:'面部特写'};
const terminal=new Set(['succeeded','failed','partial','uncertain']);
const activeSlot=(job,slot)=>!terminal.has(job.status)&&!slot.asset&&!['failed','uncertain'].includes(slot.status);
const visibleSlot=(job,slot)=>!!slot.asset||activeSlot(job,slot);
const hasActiveSlots=job=>job.slots.some(slot=>activeSlot(job,slot));
function createWorkProgress(){
 const tracked=new Map();let dismissed=false;
 function update(job){
  const previous=tracked.get(job.id),total=Math.max(previous?.total||0,job.slots.length);
  const success=job.slots.filter(s=>s.asset).length,unknown=job.slots.filter(s=>!s.asset&&s.status==='uncertain').length;
  const pending=hasActiveSlots(job);
  const failed=pending?job.slots.filter(s=>!s.asset&&s.status==='failed').length:Math.max(0,total-success-unknown);
  tracked.set(job.id,{total,success,unknown,pending,failed});
 }
 function track(job){
  if(!job||!['same','random'].includes(job.kind))return;
  if(!tracked.has(job.id)){
   if(![...tracked.values()].some(j=>j.pending))tracked.clear();
   dismissed=false;
  }
  update(job);
 }
 return {
  track,
  observe(jobs){
   const current=new Map(jobs.filter(j=>['same','random'].includes(j.kind)).map(j=>[j.id,j]));
   for(const job of current.values())if(hasActiveSlots(job))track(job);
   for(const [id,previous] of tracked){
    const job=current.get(id);
    if(job&&(previous.pending||previous.unknown||!terminal.has(job.status)))update(job);
    else tracked.set(id,{...previous,pending:false,unknown:0,failed:previous.total-previous.success});
   }
  },
  snapshot(){
   if(!tracked.size||dismissed)return null;
   const entries=[...tracked.values()];
   const sum=key=>entries.reduce((total,j)=>total+j[key],0);
   const total=sum('total'),success=sum('success'),failed=sum('failed'),unknown=sum('unknown');
   const pending=entries.some(j=>j.pending);
   return {total,success,failed,unknown,done:success+failed,pending,status:pending?'running':unknown?'uncertain':failed?(success?'partial':'failed'):'succeeded'};
  },
  dismiss(){if(![...tracked.values()].some(j=>j.pending))dismissed=true},
  reset(){tracked.clear();dismissed=false}
 };
}
const workProgress=createWorkProgress();
let generationSubmitting=false,generationError='',progressOwner=null;
function renderGenerationNotice(){
 const card=$('#generationNotice');if(!card)return;
 const owner=state.authenticated?(state.user?.email||'current-account'):null;
 if(owner!==progressOwner){workProgress.reset();generationError='';progressOwner=owner}
 if(!state.authenticated){card.hidden=true;$('#worksRunningBadge').hidden=true;document.body.classList.remove('has-generation-notice');return}
 workProgress.observe(state.jobs);
 const progress=workProgress.snapshot();
 const running=state.jobs.filter(j=>['same','random'].includes(j.kind)&&hasActiveSlots(j)).length;
 const badge=$('#worksRunningBadge');badge.textContent=running?String(running):'';badge.hidden=!running;
 card.hidden=!progress?.pending&&!generationSubmitting&&!generationError;
 document.body.classList.toggle('has-generation-notice',!card.hidden);
 if(card.hidden)return;
 const error=!!generationError,status=error?'failed':generationSubmitting?'submitting':progress.status;
 card.dataset.status=status;
 $('#generationNoticeTitle').textContent=error?'未能开始生成':status==='submitting'?'正在提交生成任务':'生成中（'+progress.done+'/'+progress.total+'）';
 $('#generationNoticeDescription').textContent=error?generationError:status==='submitting'?'稍候片刻，提交后可继续浏览灵感':progress.success+' 张已生成 · 可继续浏览灵感';
 $('#generationNoticeClose').hidden=!error;
 const bar=$('#generationNoticeProgress');bar.hidden=error||status==='submitting'||!progress?.pending;
 bar.setAttribute('aria-valuemax',String(progress?.total||1));bar.setAttribute('aria-valuenow',String(progress?.done||0));
 $('#generationNoticeFill').style.width=(progress?100*progress.done/progress.total:0)+'%';
 $('#generationNoticeView').textContent='查看作品';
}
let selectingWorks=false,deletingWorks=false,selectedWorks=new Set();
const workKey=(j,s)=>JSON.stringify([j.id,s.key]);
function renderWorkSelection(){
 const count=selectedWorks.size;
 $('#worksSelect').hidden=!state.authenticated||!state.jobs.some(j=>['same','random'].includes(j.kind)&&j.slots.some(s=>s.asset));
 $('#worksSelect').textContent=selectingWorks?'取消选择':'选择删除';$('#worksSelect').disabled=deletingWorks;
 $('#worksSelect').setAttribute('aria-pressed',String(selectingWorks));
 $('#worksSelection').hidden=!selectingWorks;$('#worksSelectionCount').textContent='已选择 '+count+' 张';
 $('#worksDelete').textContent=deletingWorks?'正在删除…':'删除（'+count+'）';$('#worksDelete').disabled=!count||deletingWorks;
 for(const button of document.querySelectorAll('.work-select')){const chosen=selectedWorks.has(button.dataset.key);button.setAttribute('aria-pressed',String(chosen));button.setAttribute('aria-label',(chosen?'取消选择':'选择')+'作品');button.classList.toggle('selected',chosen);button.textContent=chosen?'✓':'';button.disabled=deletingWorks;button.closest('.work-result').classList.toggle('is-selected',chosen)}
}
async function deleteSelectedWorks(){
 if(deletingWorks||!selectedWorks.size)return;
 const items=[...selectedWorks].map(key=>{const [id,slot]=JSON.parse(key);return {id,slot}});
 if(!confirm('删除选中的 '+items.length+' 张作品？此操作无法恢复。'))return;
 deletingWorks=true;message('');renderWorkSelection();
 try{await api('/works/delete',{items});selectedWorks.clear();selectingWorks=false;await refresh(true);message('已删除 '+items.length+' 张作品')}
 catch(error){message(error.message)}finally{deletingWorks=false;renderWorkSelection()}
}
function node(tag,text,cls){const n=document.createElement(tag);if(text)n.textContent=text;if(cls)n.className=cls;return n}
function message(text){if($('#worksMessage')){$('#worksMessage').textContent=text;$('#worksMessage').hidden=!text}$('#personalMessage').textContent=text;$('#personalMessage').hidden=!text}
async function api(path='',data){const r=await fetch('/api/personal'+path,{method:data?'POST':'GET',headers:data?{'Content-Type':'application/json'}:{},body:data?JSON.stringify(data):undefined,cache:'no-store'});const result=await r.json();if(!r.ok)throw Error(result.error||'请求失败，请重试');return result}
function image(url,alt,preview=false){const img=node('img');img.src=url;img.alt=alt;img.loading='lazy';if(preview){img.className='previewable';img.tabIndex=0;img.setAttribute('role','button');img.setAttribute('aria-label','预览 '+alt);img.title='点击查看大图';img.onclick=()=>previewImage(url,alt);img.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();previewImage(url,alt)}}}return img}
function previewImage(url,alt){const dialog=$('#personalPreview'),img=$('#personalPreviewImage'),status=$('#personalPreviewStatus');status.hidden=false;status.textContent='正在打开图片…';img.onload=()=>{status.hidden=true};img.onerror=()=>{status.hidden=false;status.textContent='图片暂时无法加载，请关闭后重试'};img.alt=alt;img.src=url;if(!dialog.open)dialog.showModal()}
function panes(){const logged=!!state.authenticated;$('#loginPane').hidden=logged;$('#personalTabs').hidden=!logged;$('#accountBar').hidden=!logged;$('#creditRule').hidden=!logged;$('#profilePane').hidden=!logged||activeTab!=='profile';$('#historyPane').hidden=!logged||activeTab!=='history';$('#profileTab').setAttribute('aria-selected',String(activeTab==='profile'));$('#historyTab').setAttribute('aria-selected',String(activeTab==='history'));$('#personalDialog').classList.toggle('login-only',!logged)}
function open(tab='profile'){activeTab=tab;const d=$('#personalDialog');panes();if(!d.open)d.showModal()}
let renderedState,renderedBusy;
function render(){
 renderedState=JSON.stringify(state);renderedBusy=busy;
 if(!state.authenticated&&$('#personalPreview')?.open)$('#personalPreview').close();panes();$('#accountEmail').textContent=state.user?.email||'';const credits=state.credits;$('#accountCredits').textContent=credits?'今日积分 '+credits.remaining+' / '+credits.limit:'';$('#accountCredits').title='每日北京时间 0 点恢复至 '+(credits?.limit??10)+' 积分';$('#creditRule').textContent='每日北京时间 0 点恢复至 '+(credits?.limit??10)+' 积分，不累积。1 积分生成 1 张图：形象库 4 分，做同款或随机生成 2 分。失败图片自动退分，状态未确认的图片暂时冻结积分。';
 const p=state.profile;$('#uploadCount').textContent=p.photos.length+'/12';$('#identityPhotos').replaceChildren(...p.photos.map((u,i)=>{const item=node('figure',null,'identity-photo');item.append(image(u,'原始照片 '+(i+1)));const remove=node('button','×','remove-photo');remove.type='button';remove.title='删除这张参考照片';remove.setAttribute('aria-label','删除原始照片 '+(i+1));remove.disabled=busy;remove.onclick=()=>action(()=>api('/photo/remove',{photo:u}));item.append(remove);const primary=u===(p.identityPhoto||p.photos[0]);const choose=node('button',primary?'面部参考 ✓':'用作面部参考','identity-primary');choose.disabled=busy||primary;choose.setAttribute('aria-label',(primary?'当前面部参考：':'设为面部参考：')+'原始照片 '+(i+1));choose.onclick=()=>action(()=>api('/photo/identity',{photo:u}));item.append(choose);return item}));
 $('#profileSummary').textContent=p.summary?.description||'上传清晰的正面、侧面及全身照，整理出你的个人形象。';
 $('#accessories').textContent=p.summary?'常见配饰：'+(p.summary.accessories?.join('、')||'未识别到固定配饰'):'';
 $('#identityViews').replaceChildren(...Object.entries(labels).map(([k,label])=>{const item=node('figure');if(p.views?.[k])item.append(image(p.views[k],label+' AI 形象参考',true));else item.append(node('div','待整理','view-placeholder'));item.append(node('figcaption',label));if(p.views?.[k]){const download=node('a','下载','view-download');download.href=p.views[k];download.download='ootd-'+k+'.jpg';item.append(download)}const generating=state.jobs.some(j=>!terminal.has(j.status)&&['profile','view'].includes(j.kind)&&j.slots.some(s=>s.key===k&&!s.asset));const redo=node('button',generating?'正在生成…':'重新生成 · 1 积分','secondary');redo.disabled=busy||!p.summary||state.jobs.some(j=>!terminal.has(j.status)&&['profile','view'].includes(j.kind));redo.onclick=()=>action(()=>api('/generate',{kind:'view',view:k,requestKey:crypto.randomUUID()}));item.append(redo);return item}));
 const schemes=state.jobs.filter(j=>terminal.has(j.status)&&['profile','view','face'].includes(j.kind)&&Object.keys(j.schemeViews||Object.fromEntries(j.slots.filter(s=>s.asset).map(s=>[s.key,s.asset]))).length===4);const chooser=$('#schemeChooser');chooser.replaceChildren();if(schemes.length){chooser.append(node('span','形象方案'));const select=node('select');select.setAttribute('aria-label','选择形象方案');for(const [i,j] of schemes.entries()){const option=node('option','方案 '+(schemes.length-i));option.value=j.id;option.selected=p.selectedScheme===j.id||(!p.selectedScheme&&i===0);select.append(option)}select.disabled=busy;select.onchange=()=>action(()=>api('/scheme/select',{id:select.value}));const wrap=node('span',null,'select-wrap');wrap.append(select);chooser.append(wrap)}
 $('#viewNote').hidden=!p.summary;$('#viewNote').textContent='做同款与随机生成使用当前方案的正面、侧面、背面和面部特写，长相细节以面部特写为主，眼镜与耳饰按方案保留。'+(p.summary?.missingViews?.length?'原片未覆盖 '+p.summary.missingViews.join('、')+'，相应视角为 AI 推测补全。':'请检查四张形象是否准确，再用于生成作品。');
 const running=state.jobs.filter(j=>!terminal.has(j.status));$('#jobsBadge').textContent=running.length?String(running.length):'';$('#profileBuild').disabled=busy||!p.photos.length||running.some(j=>['profile','face','view'].includes(j.kind));$('#profileBuild').textContent=running.some(j=>['profile','face','view'].includes(j.kind))?'正在整理形象…':p.summary?'重新整理形象库 · 4 积分':'整理形象库 · 4 积分';$('#deleteIdentity').disabled=busy||running.length>0;
 $('#personalButtonLabel').textContent=state.authenticated?(Object.keys(p.views||{}).length===4?'形象设置 ✓':'形象设置'):'登录 / 形象设置';
 const visibleJobs=state.jobs.filter(j=>j.slots.some(s=>visibleSlot(j,s)));
 const list=$('#personalJobs');list.replaceChildren();if(!visibleJobs.length)list.append(node('p','还没有生成记录。选择喜欢的照片做同款，或点击随机生成。','personal-muted'));
 for(const j of visibleJobs){const card=node('article',null,'generation-job');const head=node('div',null,'job-heading');head.append(node('h3',j.kind==='profile'?'形象库参考':j.kind==='view'?'重新生成 · '+(labels[j.slots[0]?.key]||'视图'):j.kind==='face'?'面部特写':j.kind==='random'?'随机灵感':'做同款'));
  const done=j.slots.filter(s=>s.asset).length;head.append(node('span',terminal.has(j.status)?j.status==='succeeded'?'已完成':done?'部分完成':'未完成':j.stage+' · '+done+'/'+j.slots.length,'personal-muted'));card.append(head);
  if(j.identityViews){const identity=node('div',null,'generation-identity');identity.append(node('p',j.identityMethod==='scheme-four-v1'?'本次使用选定方案的正面、侧面、背面与面部特写':j.realIdentityPhoto?'本次面部使用真实原照，方案提供外观参考':'本次使用的形象','personal-muted'));const thumbs=node('div');if(j.realIdentityPhoto)thumbs.append(image(j.realIdentityPhoto,'真实正面原照',true));for(const [key,url] of Object.entries(j.identityViews).filter(([key])=>!j.realIdentityPhoto||key==='front'))thumbs.append(image(url,labels[key]+' · 本次使用的形象',true));identity.append(thumbs);card.append(identity)}
  if(j.reference){const ref=node('div',null,'generation-reference');ref.append(image(j.reference.asset,'场景参考'),node('span','参考 · '+j.reference.title));card.append(ref)}
  const slots=node('div',null,'generation-slots'+(j.kind==='profile'?' four':['face','view'].includes(j.kind)?' single':''));
  for(const s of j.slots.filter(s=>visibleSlot(j,s))){const box=node('figure');if(s.asset){box.append(image(s.asset,s.label,true));const a=node('a','下载 '+s.label);a.href=s.asset;a.download='ootd-'+j.id+'-'+s.key+'.jpg';box.append(a);}else{box.append(node('div',s.status==='failed'?'生成失败':s.status==='uncertain'?'提交状态待确认':terminal.has(j.status)?'未生成':s.status==='running'?(s.phase==='checking_face'?'正在检查特写取景…':s.phase==='checking_accessories'?'正在核对配饰…':'正在生成…'):'等待中','result-placeholder'));box.append(node('figcaption',s.label))}if(s.error)box.append(node('p',s.error,'personal-error'));slots.append(box)}card.append(slots);
  if(j.error)card.append(node('p',j.error,'personal-error'));
  if(['failed','partial'].includes(j.status)){const retry=node('button','重试未完成部分','secondary');retry.onclick=async()=>{retry.disabled=true;try{await api('/retry',{id:j.id});await refresh()}catch(e){message(e.message)}finally{retry.disabled=false}};card.append(retry)}
  list.append(card)
 }
 renderWorks();
 renderGenerationNotice();
 $('#personalService').textContent=state.configured?state.imageModel+' · '+state.reasonModel+' · GRsai':'生图服务暂未配置';
}
function showWorks(){ $('#worksPane').hidden=false;$('#inspirationPane').hidden=true;$('#showWorks').classList.add('active');$('#showInspiration').classList.remove('active');$('#showWorks').setAttribute('aria-pressed','true');$('#showInspiration').setAttribute('aria-pressed','false');$('#personalDialog').close();window.scrollTo({top:0,behavior:'instant'}) }
function showInspiration(){ $('#worksPane').hidden=true;$('#inspirationPane').hidden=false;$('#showWorks').classList.remove('active');$('#showInspiration').classList.add('active');$('#showWorks').setAttribute('aria-pressed','false');$('#showInspiration').setAttribute('aria-pressed','true');window.dispatchEvent(new Event('ootd:inspiration-open')) }
let worksRenderKey;
function renderWorks(){
 const list=$('#worksJobs');if(!list)return;
 const outputJobs=state.jobs.filter(j=>['same','random'].includes(j.kind));
 const available=new Set(outputJobs.flatMap(j=>j.slots.filter(s=>s.asset).map(s=>workKey(j,s))));
 selectedWorks=new Set([...selectedWorks].filter(key=>available.has(key)));
 if(!state.authenticated||!available.size){selectingWorks=false;selectedWorks.clear()}
 const key=JSON.stringify([state.authenticated,state.user?.email,selectingWorks,outputJobs.map(j=>[j.id,j.slots.filter(s=>visibleSlot(j,s)).map(s=>[s.key,s.label,s.asset||null])]).filter(([,slots])=>slots.length)]);
 if(key===worksRenderKey){renderWorkSelection();return}
 worksRenderKey=key;
 list.replaceChildren();let count=0;
 for(const j of outputJobs){for(const s of j.slots.filter(s=>visibleSlot(j,s))){
  const card=node('article',null,'work-result');
  if(s.asset){
   count++;card.append(image(s.asset,'我的作品 · '+s.label,!selectingWorks));
   if(selectingWorks){
    const choose=node('button',null,'work-select');choose.type='button';choose.dataset.key=workKey(j,s);
    choose.onclick=()=>{if(deletingWorks)return;const key=choose.dataset.key;selectedWorks.has(key)?selectedWorks.delete(key):selectedWorks.add(key);renderWorkSelection()};
    card.querySelector('img').onclick=()=>choose.click();card.append(choose);
   }else{
    const download=node('a','下载照片','work-download');download.href=s.asset;download.download='ootd-'+j.id+'-'+s.key+'.jpg';card.append(download);
   }
  }else{
   card.append(node('div','正在生成…','work-pending'));
   const details=node('button','查看进度','secondary');details.onclick=()=>open('history');card.append(details);
  }
  list.append(card);
 }}
 $('#worksCount').textContent=count?String(count):'';$('#worksEmpty').hidden=list.childElementCount>0;
 $('#worksEmpty p').textContent=state.authenticated?'生成的照片会保存在这里':'登录后，在这里查看你生成的照片';$('#worksExplore').textContent=state.authenticated?'找张灵感，做我的同款':'邮箱登录';$('#worksExplore').onclick=()=>state.authenticated?showInspiration():open();
 renderWorkSelection();
}
async function refresh(force=false){if(polling){await polling;if(!force)return}polling=(async()=>{try{state=await api();if(renderedBusy!==busy||renderedState!==JSON.stringify(state))render()}catch(e){if($('#personalDialog').open)message(e.message)}finally{polling=false}})();return polling}
async function action(fn){if(busy)return;busy=true;message('');render();try{await fn()}catch(e){message(e.message)}finally{busy=false;await refresh()}}
async function compressed(file){if(!['image/jpeg','image/png','image/webp'].includes(file.type))throw Error('请选择 JPG、PNG 或 WebP 照片');if(file.size>12_000_000)throw Error('单张照片不能超过 12 MB');const bmp=await createImageBitmap(file,{imageOrientation:'from-image'});if(Math.min(bmp.width,bmp.height)<160){bmp.close();throw Error('照片短边至少需要 160 像素')}const ratio=Math.min(1,1600/Math.max(bmp.width,bmp.height));const canvas=document.createElement('canvas');canvas.width=Math.round(bmp.width*ratio);canvas.height=Math.round(bmp.height*ratio);canvas.getContext('2d').drawImage(bmp,0,0,canvas.width,canvas.height);bmp.close();return canvas.toDataURL('image/jpeg',.9)}
async function generate(kind,reference){
 if(busy){message('正在保存形象选择，请稍候再生成。');return}await refresh();if(!state.authenticated){pendingAction={kind,reference};open();message('邮箱登录后即可建立形象库和生成个人照片。');return}if(Object.keys(state.profile.views||{}).length<4){pendingReference=reference;open();message('先上传照片并完成形象库整理，然后就能做同款。');return}
 if((state.credits?.remaining??0)<2){generationError='积分不足：本次需要 2 积分，今日剩余 '+(state.credits?.remaining??0)+' 积分。';renderGenerationNotice();return}
 generationError='';generationSubmitting=true;renderGenerationNotice();
 await action(async()=>{const payload={kind,schemeId:state.profile.selectedScheme??null,requestKey:crypto.randomUUID()};if(kind==='random')payload.referenceIds=[...document.querySelectorAll('#grid .card')].map(n=>n.dataset.id).slice(0,500);else payload.referenceId=reference.id;
  try{const result=await api('/generate',payload);generationSubmitting=false;state.jobs=[result.job,...state.jobs.filter(j=>j.id!==result.job.id)];workProgress.track(result.job);renderWorks();if($('#personalDialog').open)$('#personalDialog').close();renderGenerationNotice()}
  catch(error){generationSubmitting=false;generationError=error.message;renderGenerationNotice();throw error}
 });generationSubmitting=false;renderGenerationNotice();
}
export function initPersonal(){
 const badge=node('span',null,'works-running-badge');badge.id='worksRunningBadge';badge.hidden=true;$('#showWorks').append(badge);
 const notice=node('aside',null,'generation-notice');notice.id='generationNotice';notice.hidden=true;notice.setAttribute('aria-label','图片生成进度');
 notice.innerHTML='<div class="generation-notice-icon" aria-hidden="true"></div><div class="generation-notice-content"><div id="generationNoticeStatus" role="status" aria-live="polite" aria-atomic="true"><h2 id="generationNoticeTitle"></h2><p id="generationNoticeDescription"></p></div><div id="generationNoticeProgress" class="generation-notice-progress" role="progressbar" aria-label="图片生成进度" aria-valuemin="0"><span id="generationNoticeFill"></span></div><button id="generationNoticeView" type="button">查看进度 <span aria-hidden="true">↗</span></button></div><button id="generationNoticeClose" class="generation-notice-close" type="button" aria-label="关闭生成提示">×</button>';
 document.body.append(notice);
 $('#generationNoticeClose').onclick=()=>{generationError='';workProgress.dismiss();renderGenerationNotice()};
 $('#generationNoticeView').onclick=()=>{generationError='';showWorks();renderGenerationNotice()};
 const actions=node('div',null,'works-actions');$('#worksIdentity').before(actions);actions.append($('#worksIdentity'));
 const select=node('button','选择删除','secondary');select.id='worksSelect';select.type='button';select.hidden=true;actions.prepend(select);
 const selection=node('div',null,'works-selection');selection.id='worksSelection';selection.hidden=true;
 const count=node('span');count.id='worksSelectionCount';count.setAttribute('role','status');
 const remove=node('button','删除（0）','personal-delete');remove.id='worksDelete';remove.type='button';remove.onclick=deleteSelectedWorks;
 selection.append(count,remove);$('#worksJobs').before(selection);
 select.onclick=()=>{if(deletingWorks)return;selectingWorks=!selectingWorks;selectedWorks.clear();renderWorks()};
 const dialog=node('dialog',null,'personal-dialog');dialog.id='personalDialog';dialog.innerHTML=`<div class="personal-heading"><div id="personalTabs" role="tablist" aria-label="个人照片"><button id="profileTab" role="tab" aria-selected="true">我的形象</button><button id="historyTab" role="tab" aria-selected="false">生成记录 <span id="jobsBadge"></span></button></div><button id="closePersonal" aria-label="关闭">×</button></div><p id="personalMessage" class="personal-error" role="status" hidden></p><section id="loginPane"><h2>邮箱验证码登录</h2><p class="personal-muted">登录后保存个人形象，生成属于你的氛围照片。</p><form id="emailLoginForm"><label for="loginEmail">邮箱</label><input id="loginEmail" type="email" name="email" autocomplete="email" maxlength="254" placeholder="输入你的邮箱" required><label for="loginCode">验证码</label><div class="email-code-row"><input id="loginCode" type="text" name="code" inputmode="numeric" pattern="[0-9]{6}" maxlength="6" autocomplete="one-time-code" placeholder="6 位验证码" required><button id="sendEmailCode" type="button" class="secondary">获取验证码</button></div><button id="verifyEmail" type="submit" class="primary">登录</button></form><p class="personal-muted login-note">首次验证自动创建账户。验证码 10 分钟有效。</p></section><div id="accountBar" class="account-bar" hidden><span id="accountEmail"></span><span id="accountCredits" title="每日北京时间 0 点恢复至 10 积分"></span><button id="logoutEmail" type="button">退出登录</button></div><p id="creditRule" class="personal-muted credit-rule"></p><section id="profilePane"><div class="upload-heading"><h2>个人形象库</h2><span id="uploadCount">0/12</span></div><p class="personal-muted">上传你本人的清晰照片。选择一张清晰的本人正面原照作为面部参考。其他角度、全身照和配饰实物照也可一起上传。</p><label class="identity-upload">＋ 添加照片<input id="identityUpload" type="file" accept="image/jpeg,image/png,image/webp" multiple></label><div id="identityPhotos" class="identity-photos"></div><p id="profileSummary"></p><p id="accessories" class="personal-muted"></p><div id="schemeChooser" class="scheme-chooser"></div><div id="identityViews" class="identity-views"></div><p id="viewNote" class="personal-muted" hidden></p><div class="identity-actions"><button id="profileBuild" class="primary">整理形象库</button><button id="continueSame" class="secondary" hidden>用这张参考做同款</button><button id="deleteIdentity" class="personal-delete">删除我的全部照片与记录</button></div><p class="personal-privacy">原片和结果私密保存在你的邮箱账户下，其他设备登录同一邮箱即可访问。照片会发送到 GRsai 用于分析和生成。整理形象库生成 4 张参考；做同款、随机生成每次生成 2 张。请勿将验证码或账户交给他人。</p></section><section id="historyPane" hidden><div id="personalJobs"></div></section><p id="personalService" class="personal-service"></p>`;document.body.append(dialog);
 const preview=node('dialog',null,'personal-preview');preview.id='personalPreview';preview.setAttribute('aria-label','生成图片预览');preview.innerHTML='<button id="closePersonalPreview" aria-label="关闭图片预览">×</button><p id="personalPreviewStatus" role="status"></p><img id="personalPreviewImage" alt="">';document.body.append(preview);$('#closePersonalPreview').onclick=()=>preview.close();preview.addEventListener('click',e=>{if(e.target===preview)preview.close()});preview.addEventListener('close',()=>{$('#personalPreviewImage').removeAttribute('src')});dialog.addEventListener('close',()=>{if(preview.open)preview.close()});
 $('#sendEmailCode').onclick=async()=>{const email=$('#loginEmail');if(!email.reportValidity()||authBusy||Date.now()<resendUntil)return;authBusy=true;$('#sendEmailCode').disabled=true;message('正在发送验证码…');try{const result=await api('/auth/send',{email:email.value});resendUntil=Date.now()+result.retryAfter*1000;message('验证码已发送，请检查收件箱及垃圾邮件。')}catch(e){message(e.message)}finally{authBusy=false;updateResend()}};
 $('#emailLoginForm').onsubmit=async e=>{e.preventDefault();if(authBusy)return;authBusy=true;$('#verifyEmail').disabled=true;message('正在验证…');try{await api('/auth/verify',{email:$('#loginEmail').value,code:$('#loginCode').value});$('#loginCode').value='';await refresh();open();message('登录成功');if(pendingAction&&Object.keys(state.profile.views||{}).length===4){const next=pendingAction;pendingAction=null;await generate(next.kind,next.reference)}}catch(error){message(error.message)}finally{authBusy=false;$('#verifyEmail').disabled=false}};
 $('#logoutEmail').onclick=()=>action(async()=>{await api('/auth/logout',{});state={authenticated:false,profile:{photos:[],views:{}},jobs:[]};pendingAction=null;$('#loginCode').value='';message('已退出登录')});
 function updateResend(){const seconds=Math.max(0,Math.ceil((resendUntil-Date.now())/1000));$('#sendEmailCode').disabled=authBusy||seconds>0;$('#sendEmailCode').textContent=seconds?seconds+' 秒后重发':'获取验证码'}setInterval(updateResend,1000);
 $('#showWorks').onclick=()=>{showWorks();refresh()};$('#savedButton').addEventListener('click',showInspiration);$('#showInspiration').onclick=showInspiration;$('#worksIdentity').onclick=()=>{open();refresh()};
 $('#personalButton').onclick=()=>{open();refresh()};$('#randomGenerate').onclick=()=>generate('random');$('#closePersonal').onclick=()=>dialog.close();$('#profileTab').onclick=()=>open();$('#historyTab').onclick=()=>open('history');
 $('#identityUpload').onchange=()=>action(async()=>{const files=[...$('#identityUpload').files];if(!files.length)return;if(files.length+state.profile.photos.length>12)throw Error('最多上传 12 张照片');message('正在处理和上传照片…');const photos=[];for(const f of files)photos.push(await compressed(f));await api('/upload',{photos});$('#identityUpload').value='';message('照片已保存，点击整理形象库开始分析。')});
 $('#profileBuild').onclick=()=>action(async()=>{await api('/generate',{kind:'profile',requestKey:crypto.randomUUID()});open('history')});
 $('#continueSame').onclick=()=>{if(pendingReference)generate('same',pendingReference)};
 $('#deleteIdentity').onclick=()=>{if(confirm('删除原始照片、形象参考及所有生成记录？此操作无法恢复。'))action(()=>api('/delete',{}))};
 window.addEventListener('ootd:make-same',e=>{pendingReference=e.detail;$('#continueSame').hidden=false;generate('same',e.detail)});
 dialog.addEventListener('click',e=>{if(e.target===dialog){const r=dialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)dialog.close()}});
 refresh();setInterval(()=>{if(dialog.open||state.jobs.some(j=>!terminal.has(j.status)))refresh()},5000)
}
