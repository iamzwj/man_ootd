import {initPersonal} from './personal.js?v=nav-progress-1';
import {NOTE,normalizeItems,filterItems,heatText} from './feed-utils.js?v=11';
const $=s=>document.querySelector(s);const storage={get(k,f){try{return JSON.parse(localStorage.getItem(k))??f}catch{return f}},set(k,v){try{localStorage.setItem(k,JSON.stringify(v))}catch{}}};
const channel='photo',category='全部';
let items=[],queue=[],shown=0,savedOnly=false,busy=false,viewIndex=-1,epoch=0,emptyPages=0,hasMore=true,columns=[],heights=[],requestController;

const streamCache=new Map(Object.entries(storage.get('ootd-stream-cache-domestic-lifestyle-v8',{})));let activeStream=null,autoLoadEnabled=true,retryAt=0,nextAutoAt=0;
function cacheCurrent(){if(!activeStream||(!items.length&&!emptyPages))return;streamCache.set(activeStream,{items:items.slice(),emptyPages,hasMore,status:$('#feedStatus').textContent});const recent=[...streamCache.entries()].slice(-16).map(([k,v])=>[k,{...v,items:v.items.slice(-120)}]);storage.set('ootd-stream-cache-domestic-lifestyle-v8',Object.fromEntries(recent));}

let savedMap=new Map(storage.get('ootd-saved-items',[]).map(p=>[p.id,p]));const saved=new Set(savedMap.keys()),hidden=new Set(storage.get('ootd-hidden',[])),seen=new Set(storage.get('ootd-seen',[])),failed=new Set();let cursorMap=storage.get('ootd-cursors-domestic-lifestyle-v8',{}),toastTimer;
function toast(t){$('#toast').textContent=t;$('#toast').classList.add('visible');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').classList.remove('visible'),2500)}
function key(){return channel+':'+category+':all'}function persist(){storage.set('ootd-cursors-domestic-lifestyle-v8',cursorMap);storage.set('ootd-seen',[...seen].slice(-6000))}
const observer=new IntersectionObserver(es=>{for(const e of es)if(e.isIntersecting){seen.add(e.target.dataset.id);observer.unobserve(e.target)}persist()},{threshold:.4});
const columnCount=()=>innerWidth<=600?2:innerWidth<=900?3:innerWidth<=1200?4:innerWidth>=1800?6:5;
function initColumns(){const n=columnCount();$('#grid').replaceChildren();columns=Array.from({length:n},()=>{let c=document.createElement('div');c.className='masonry-column';$('#grid').append(c);return c});heights=Array(n).fill(0);$('#grid').style.setProperty('--columns',n)}
function put(card,p){let i=heights.indexOf(Math.min(...heights));columns[i].append(card);heights[i]+=(p.height||960)/(p.width||720)*(innerWidth*.92/columns.length)+65}
function chrome(){$('#contextHint').textContent='边滑边获取 / 照片缓存在当前设备';$('#savedCount').textContent=saved.size}
function card(p,index){let el=document.createElement('article');el.className='card';el.dataset.id=p.id;let ph=document.createElement('div');ph.className='photo';let img=document.createElement('img');img.src=p.image;img.alt=p.title+' · '+p.category;img.width=p.width||720;img.height=p.height||960;img.loading=index<6?'eager':'lazy';img.decoding='async';img.referrerPolicy='no-referrer';let tried=false;img.onload=scheduleFillViewport;img.onerror=()=>{if(p.thumbnail&&!tried){tried=true;img.src=p.thumbnail;return}failed.add(p.id);el.remove();scheduleFillViewport()};img.onclick=()=>openPhoto(index);let b=document.createElement('button');b.className='card-save'+(saved.has(p.id)?' saved':'');b.textContent=saved.has(p.id)?'♥':'♡';b.setAttribute('aria-label','收藏 '+p.title);b.setAttribute('aria-pressed',String(saved.has(p.id)));b.onclick=()=>toggleSave(p,b);let make=document.createElement('button');make.className='make-same';make.textContent='做同款 ↗';make.setAttribute('aria-label','用我的形象做同款，生成两张照片');make.onclick=e=>{e.stopPropagation();window.dispatchEvent(new CustomEvent('ootd:make-same',{detail:{id:p.id,title:p.title}}))};ph.append(img,make,b);let h=document.createElement('h3');h.className='card-title';h.textContent=p.title;h.onclick=()=>openPhoto(index);let meta=document.createElement('div');meta.className='card-meta';let hide=document.createElement('button');hide.className='hide-button';hide.textContent='×';hide.title='不感兴趣';hide.setAttribute('aria-label','隐藏 '+p.title);hide.onclick=()=>{hidden.add(p.id);storage.set('ootd-hidden',[...hidden]);el.remove();toast('已隐藏这张照片')};meta.append(hide);el.append(ph,h,meta);observer.observe(el);return el}
function selected(){return filterItems(savedOnly?[...savedMap.values()]:items,{channel,category,savedOnly,saved,hidden});}
function rebuild(){observer.disconnect();queue=selected();shown=0;initColumns();append();}
function append(){let stop=Math.min(shown+24,queue.length);for(let i=shown;i<stop;i++)if(!failed.has(queue[i].id))put(card(queue[i],i),queue[i]);shown=stop;$('#totalCount').textContent=(savedOnly?'收藏 ':'本次发现 ')+queue.length+' 张';$('#empty').hidden=queue.length>0||busy;$('#sentinel').hidden=savedOnly&&!queue.length;$('#loadMore').hidden=busy;$('#loadMore').textContent=savedOnly?'加载更多收藏':hasMore?'继续获取新照片':'检查新精选';$('#loadStatus').textContent=busy?'正在从来源获取下一批…':savedOnly?(shown<queue.length?'继续浏览收藏':'收藏已显示完'):(hasMore?'向下滑动，继续获取新的灵感':'当前来源暂无更多照片');if(savedOnly&&shown===queue.length)$('#loadMore').hidden=true;}
function toggleSave(p,b){if(saved.has(p.id)){saved.delete(p.id);savedMap.delete(p.id)}else{saved.add(p.id);savedMap.set(p.id,p)}storage.set('ootd-saved-items',[...savedMap.values()]);$('#savedCount').textContent=saved.size;if(b){b.textContent=saved.has(p.id)?'♥':'♡';b.classList.toggle('saved',saved.has(p.id));b.setAttribute('aria-pressed',String(saved.has(p.id)))}$('#detailSave').textContent=saved.has(p.id)?'♥ 已收藏':'♡ 收藏灵感';toast(saved.has(p.id)?'已收藏在当前设备':'已取消收藏');if(savedOnly&&!$('#viewer').open)rebuild()}
const photoViewer = $('#viewer');
let photoViewerScroll = null;

function showPhotoViewer() {
  if (photoViewer.open) return;
  photoViewerScroll = { left: window.scrollX, top: window.scrollY, behavior: 'instant' };
  photoViewer.scrollTop = 0;
  photoViewer.showModal();
  window.scrollTo(photoViewerScroll);
}

photoViewer.addEventListener('close', () => {
  if (savedOnly) rebuild();
  if (photoViewerScroll) {
    window.scrollTo(photoViewerScroll);
    photoViewerScroll = null;
  }
  scheduleFillViewport();
});

function openPhoto(i){if(i<0||i>=queue.length)return;viewIndex=i;let p=queue[i];$('#largeImage').src=p.image;$('#largeImage').onerror=()=>{if(p.thumbnail&&$('#largeImage').src!==p.thumbnail)$('#largeImage').src=p.thumbnail};$('#largeImage').alt=p.title;$('#detailTitle').textContent=p.title;$('#detailCategory').textContent=(channel==='outfit'?'穿搭灵感 / ':'氛围摄影 / ')+p.category;$('#detailNote').textContent=NOTE[p.category]||'';$('#detailSource').textContent=p.source+' · '+heatText(p);$('#originalTitle').textContent=p.originalTitle;$('#originalLink').href=p.url;$('#detailSave').textContent=saved.has(p.id)?'♥ 已收藏':'♡ 收藏灵感';$('#prevPhoto').disabled=i===0;$('#nextPhoto').disabled=i===queue.length-1;seen.add(p.id);persist();showPhotoViewer()}
async function loadNext(manual=false){if(busy||savedOnly||Date.now()<retryAt)return;if(!manual&&(!hasMore||Date.now()<nextAutoAt))return;const id=epoch,streamKey=key(),cursor=cursorMap[streamKey]||0;busy=true;$('#feedStatus').textContent='正在获取新照片…';append();requestController=new AbortController();const timeout=setTimeout(()=>requestController.abort(),36000);try{let response=await fetch('./api/discover',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({channel,category,cursor,source:'all',exclude:[...new Set([...hidden,...items.map(p=>p.id)])].slice(-6500)}),cache:'no-store',signal:requestController.signal});if(id!==epoch)return;
if(response.status===429){
  const data=await response.json().catch(()=>({}));
  if(id!==epoch)return;
  const seconds=Number(data?.retryAfter);
  retryAt=Date.now()+1000*(Number.isFinite(seconds)&&seconds>0?seconds:3);
  $('#feedStatus').textContent='加载请求较多 · 稍后自动重试';
  $('#loadStatus').textContent='请稍候，已加载的图片可以继续浏览';
  return;
}
let data=await response.json();if(id!==epoch)return;if(!response.ok||!data.sourceAvailable)throw Error('来源暂时不可用');const known=new Set(items.map(p=>p.id));const next=normalizeItems([...items,...(Array.isArray(data.items)?data.items:[])]).filter(p=>!known.has(p.id)&&!hidden.has(p.id));items.push(...next);cursorMap[streamKey]=data.nextCursor;hasMore=data.hasMore!==false;persist();emptyPages=next.length?0:emptyPages+1;let fresh=selected();let qids=new Set(queue.map(p=>p.id));queue.push(...fresh.filter(p=>!qids.has(p.id)));const available=(data.sources||[]).filter(s=>s.available).map(s=>s.name);$('#feedStatus').textContent=(data.photographerCount?'国内来源 · ':available.length?available.join(' + ')+' · ':'')+(next.length?'新增 '+next.length+' 张':'这一页暂无新图')+' · 持续发现';$('#updateDetail').textContent='最近请求：'+new Date().toLocaleTimeString('zh-CN')+'。图片从原始来源加载，服务器不保存图片文件。';busy=false;append();if(!next.length){$('#loadStatus').textContent='这轮暂无新图，正在换下一页搜索；也可点击立即重试';$('#loadMore').hidden=false;}}catch(e){if(id!==epoch)return;if(e.name!=='AbortError'||!requestController.signal.aborted||id===epoch){$('#feedStatus').textContent='来源连接暂不可用 · 可以继续重试';$('#loadStatus').textContent='当前图片仍可浏览，点击继续获取重试';emptyPages=3;}}finally{clearTimeout(timeout);if(id===epoch){busy=false;cacheCurrent();$('#loadMore').hidden=false;$('#empty').hidden=queue.length>0;nextAutoAt=Math.max(retryAt,Date.now()+(emptyPages?Math.min(10000,1000*emptyPages):150));setTimeout(()=>{if(id===epoch)fillViewport()},nextAutoAt-Date.now());}}}
let fillFrame=0;function scheduleFillViewport(){if(fillFrame)return;fillFrame=requestAnimationFrame(()=>{fillFrame=0;fillViewport()})}
function fillViewport(){if(!autoLoadEnabled||busy||document.hidden||$('#inspirationPane').hidden||$('#viewer').open)return;if($('#sentinel').getBoundingClientRect().top>innerHeight+700)return;if(shown<queue.length){append();setTimeout(fillViewport,150)}else if(!savedOnly)loadNext()}
function start(){cacheCurrent();epoch++;requestController?.abort();busy=false;emptyPages=0;hasMore=true;nextAutoAt=0;activeStream=savedOnly?null:key();const cached=activeStream&&streamCache.get(activeStream);items=cached?normalizeItems(cached.items):[];queue=[];shown=0;observer.disconnect();chrome();$('#emptyText').textContent=savedOnly?'收藏的照片会显示在这里。':'可以继续获取照片。';$('#emptyReset').hidden=savedOnly;if(savedOnly){autoLoadEnabled=false;rebuild();$('#feedStatus').textContent='当前设备收藏';return}if(cached){autoLoadEnabled=true;emptyPages=0;hasMore=cached.hasMore!==false;rebuild();setTimeout(fillViewport,150);$('#feedStatus').textContent=items.length?'已恢复本机缓存 · '+items.length+' 张':'暂无新照片 · 可继续获取';return}autoLoadEnabled=true;initColumns();$('#empty').hidden=true;if(Date.now()<retryAt)setTimeout(scheduleFillViewport,retryAt-Date.now());else loadNext(true)}
$('#emptyReset').onclick=()=>loadNext(true);$('#loadMore').onclick=()=>shown<queue.length?append():loadNext(true);new IntersectionObserver(es=>{if(es.some(e=>e.isIntersecting))scheduleFillViewport()},{rootMargin:'700px'}).observe($('#sentinel'));$('#detailSave').onclick=()=>toggleSave(queue[viewIndex]);$('#prevPhoto').onclick=()=>openPhoto(viewIndex-1);$('#nextPhoto').onclick=()=>openPhoto(viewIndex+1);document.addEventListener('keydown',e=>{if(!$('#viewer').open)return;if(e.key==='ArrowRight')openPhoto(viewIndex+1);if(e.key==='ArrowLeft')openPhoto(viewIndex-1)});document.querySelectorAll('dialog .dialog-close').forEach(b=>b.onclick=()=>b.closest('dialog').close());document.querySelectorAll('dialog').forEach(d=>d.onclick=e=>{if(e.target!==d)return;let r=d.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)d.close()});$('#aboutButton').onclick=()=>$('#about').showModal();$('#backTop').onclick=()=>window.scrollTo({top:0,behavior:'smooth'});window.addEventListener('scroll',()=>{$('#backTop').classList.toggle('visible',scrollY>900);autoLoadEnabled=true;scheduleFillViewport()},{passive:true});let resizeTimer;window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>{if(columnCount()===columns.length)return;const previous=shown;observer.disconnect();initColumns();for(let i=0;i<previous;i++)if(!failed.has(queue[i].id))put(card(queue[i],i),queue[i]);},180)});
window.addEventListener('pagehide',cacheCurrent);window.addEventListener('wheel',()=>{autoLoadEnabled=true;scheduleFillViewport()},{passive:true});window.addEventListener('touchmove',()=>{autoLoadEnabled=true;scheduleFillViewport()},{passive:true});
if('serviceWorker' in navigator)navigator.serviceWorker.register('./sw.js').catch(()=>{});
start();

document.addEventListener('visibilitychange',()=>{if(!document.hidden)scheduleFillViewport()});

initPersonal();

window.addEventListener('ootd:inspiration-open',event=>{
 const openSaved=event.detail==='saved';
 if(savedOnly!==openSaved){savedOnly=openSaved;start()}
 else scheduleFillViewport();
});
