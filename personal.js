const $=s=>document.querySelector(s);
let state={profile:{photos:[],views:{}},jobs:[]},pendingReference=null,busy=false,polling=false;
const labels={front:'正面',side:'侧面',back:'背面',face:'面部特写'};
const terminal=new Set(['succeeded','failed','partial','uncertain']);
function node(tag,text,cls){const n=document.createElement(tag);if(text)n.textContent=text;if(cls)n.className=cls;return n}
function message(text){$('#personalMessage').textContent=text;$('#personalMessage').hidden=!text}
async function api(path='',data){const r=await fetch('/api/personal'+path,{method:data?'POST':'GET',headers:data?{'Content-Type':'application/json'}:{},body:data?JSON.stringify(data):undefined,cache:'no-store'});const result=await r.json();if(!r.ok)throw Error(result.error||'请求失败，请重试');return result}
function image(url,alt){const img=node('img');img.src=url;img.alt=alt;img.loading='lazy';return img}
function open(tab='profile'){const d=$('#personalDialog');if(!d.open)d.showModal();$('#profilePane').hidden=tab!=='profile';$('#historyPane').hidden=tab!=='history';$('#profileTab').setAttribute('aria-selected',String(tab==='profile'));$('#historyTab').setAttribute('aria-selected',String(tab==='history'))}
function render(){
 const p=state.profile;$('#uploadCount').textContent=p.photos.length+'/12';$('#identityPhotos').replaceChildren(...p.photos.map((u,i)=>image(u,'原始照片 '+(i+1))));
 $('#profileSummary').textContent=p.summary?.description||'上传清晰的正面、侧面及全身照，整理出你的个人形象。';
 $('#accessories').textContent=p.summary?'常见配饰：'+(p.summary.accessories?.join('、')||'未识别到固定配饰'):'';
 $('#identityViews').replaceChildren(...Object.entries(labels).map(([k,label])=>{const item=node('figure');if(p.views?.[k])item.append(image(p.views[k],label+' AI 形象参考'));else item.append(node('div','待整理','view-placeholder'));item.append(node('figcaption',label));return item}));
 $('#viewNote').hidden=!p.summary;$('#viewNote').textContent='以上为 AI 形象参考。'+(p.summary?.missingViews?.length?'原片未覆盖 '+p.summary.missingViews.join('、')+'，相应视角为推测补全。':'请检查相貌是否准确，再用于做同款。');
 const running=state.jobs.filter(j=>!terminal.has(j.status));$('#jobsBadge').textContent=running.length?String(running.length):'';$('#profileBuild').disabled=busy||!p.photos.length||running.some(j=>j.kind==='profile');$('#profileBuild').textContent=running.some(j=>j.kind==='profile')?'正在整理形象…':p.summary?'重新整理形象库':'整理形象库';$('#deleteIdentity').disabled=busy||running.length>0;
 $('#personalButtonLabel').textContent=Object.keys(p.views||{}).length===4?'我的形象 ✓':'我的形象';
 const list=$('#personalJobs');list.replaceChildren();if(!state.jobs.length)list.append(node('p','还没有生成记录。选择喜欢的照片做同款，或点击随机生成。','personal-muted'));
 for(const j of state.jobs){const card=node('article',null,'generation-job');const head=node('div',null,'job-heading');head.append(node('h3',j.kind==='profile'?'形象库参考':j.kind==='random'?'随机灵感':'做同款'));
  const done=j.slots.filter(s=>s.asset).length;head.append(node('span',terminal.has(j.status)?j.status==='succeeded'?'已完成':done?'部分完成':'未完成':j.stage+' · '+done+'/'+j.slots.length,'personal-muted'));card.append(head);
  if(j.reference){const ref=node('div',null,'generation-reference');ref.append(image(j.reference.asset,'场景参考'),node('span','参考 · '+j.reference.title));card.append(ref)}
  const slots=node('div',null,'generation-slots'+(j.kind==='profile'?' four':''));
  for(const s of j.slots){const box=node('figure');if(s.asset){box.append(image(s.asset,s.label));const a=node('a','下载 '+s.label);a.href=s.asset;a.download='ootd-'+j.id+'-'+s.key+'.jpg';box.append(a)}else{box.append(node('div',s.status==='failed'?'生成失败':s.status==='uncertain'?'提交状态待确认':terminal.has(j.status)?'未生成':s.status==='running'?'正在生成…':'等待中','result-placeholder'));box.append(node('figcaption',s.label))}if(s.error)box.append(node('p',s.error,'personal-error'));slots.append(box)}card.append(slots);
  if(j.error)card.append(node('p',j.error,'personal-error'));
  if(['failed','partial'].includes(j.status)){const retry=node('button','重试未完成部分','secondary');retry.onclick=async()=>{retry.disabled=true;try{await api('/retry',{id:j.id});await refresh()}catch(e){message(e.message)}finally{retry.disabled=false}};card.append(retry)}
  if(j.status==='uncertain')card.append(node('p','提交时连接中断。为避免重复计费，没有自动重发，请保留任务记录。','personal-error'));
  list.append(card)
 }
 $('#personalService').textContent=state.configured?'image 2.5 · Gemini 3.1 Pro · GRsai':'生图服务暂未配置';
}
async function refresh(){if(polling)return;polling=true;try{state=await api();render()}catch(e){if($('#personalDialog').open)message(e.message)}finally{polling=false}}
async function action(fn){if(busy)return;busy=true;message('');render();try{await fn()}catch(e){message(e.message)}finally{busy=false;await refresh()}}
async function compressed(file){if(!['image/jpeg','image/png','image/webp'].includes(file.type))throw Error('请选择 JPG、PNG 或 WebP 照片');if(file.size>12_000_000)throw Error('单张照片不能超过 12 MB');const bmp=await createImageBitmap(file,{imageOrientation:'from-image'});if(Math.min(bmp.width,bmp.height)<160){bmp.close();throw Error('照片短边至少需要 160 像素')}const ratio=Math.min(1,1600/Math.max(bmp.width,bmp.height));const canvas=document.createElement('canvas');canvas.width=Math.round(bmp.width*ratio);canvas.height=Math.round(bmp.height*ratio);canvas.getContext('2d').drawImage(bmp,0,0,canvas.width,canvas.height);bmp.close();return canvas.toDataURL('image/jpeg',.9)}
async function generate(kind,reference){
 await refresh();if(Object.keys(state.profile.views||{}).length<4){pendingReference=reference;open();message('先上传照片并完成形象库整理，然后就能做同款。');return}
 open('history');await action(async()=>{const payload={kind,requestKey:crypto.randomUUID()};if(kind==='random')payload.referenceIds=[...document.querySelectorAll('#grid .card')].map(n=>n.dataset.id).slice(0,500);else payload.referenceId=reference.id;await api('/generate',payload)})
}
export function initPersonal(){
 const dialog=node('dialog',null,'personal-dialog');dialog.id='personalDialog';dialog.innerHTML=`<div class="personal-heading"><div role="tablist" aria-label="个人照片"><button id="profileTab" role="tab" aria-selected="true">我的形象</button><button id="historyTab" role="tab" aria-selected="false">生成记录 <span id="jobsBadge"></span></button></div><button id="closePersonal" aria-label="关闭">×</button></div><p id="personalMessage" class="personal-error" role="status" hidden></p><section id="profilePane"><div class="upload-heading"><h2>个人形象库</h2><span id="uploadCount">0/12</span></div><p class="personal-muted">上传你本人的清晰照片。建议包含正面、侧面、背面及全身，常戴的配饰也一起拍入。</p><label class="identity-upload">＋ 添加照片<input id="identityUpload" type="file" accept="image/jpeg,image/png,image/webp" multiple></label><div id="identityPhotos" class="identity-photos"></div><p id="profileSummary"></p><p id="accessories" class="personal-muted"></p><div id="identityViews" class="identity-views"></div><p id="viewNote" class="personal-muted" hidden></p><div class="identity-actions"><button id="profileBuild" class="primary">整理形象库</button><button id="continueSame" class="secondary" hidden>用这张参考做同款</button><button id="deleteIdentity" class="personal-delete">删除我的全部照片与记录</button></div><p class="personal-privacy">原片和结果私密保存，仅当前浏览器身份可访问。照片会发送到 GRsai 用于分析和生成。整理形象库生成 4 张参考；做同款、随机生成每次生成 2 张。清除浏览器 Cookie 后将无法访问原形象库，请及时下载。</p></section><section id="historyPane" hidden><div id="personalJobs"></div></section><p id="personalService" class="personal-service"></p>`;document.body.append(dialog);
 $('#personalButton').onclick=()=>{open();refresh()};$('#randomGenerate').onclick=()=>generate('random');$('#closePersonal').onclick=()=>dialog.close();$('#profileTab').onclick=()=>open();$('#historyTab').onclick=()=>open('history');
 $('#identityUpload').onchange=()=>action(async()=>{const files=[...$('#identityUpload').files];if(!files.length)return;if(files.length+state.profile.photos.length>12)throw Error('最多上传 12 张照片');message('正在处理和上传照片…');const photos=[];for(const f of files)photos.push(await compressed(f));await api('/upload',{photos});$('#identityUpload').value='';message('照片已保存，点击整理形象库开始分析。')});
 $('#profileBuild').onclick=()=>action(async()=>{await api('/generate',{kind:'profile',requestKey:crypto.randomUUID()});open('history')});
 $('#continueSame').onclick=()=>{if(pendingReference)generate('same',pendingReference)};
 $('#deleteIdentity').onclick=()=>{if(confirm('删除原始照片、形象参考及所有生成记录？此操作无法恢复。'))action(()=>api('/delete',{}))};
 window.addEventListener('ootd:make-same',e=>{pendingReference=e.detail;$('#continueSame').hidden=false;generate('same',e.detail)});
 dialog.addEventListener('click',e=>{if(e.target===dialog){const r=dialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)dialog.close()}});
 refresh();setInterval(()=>{if(dialog.open||state.jobs.some(j=>!terminal.has(j.status)))refresh()},5000)
}
