export const CATEGORIES = {  
outfit: ['全部', '简约干净', '日系 Cityboy', '韩系休闲', '街头潮流', '复古美式', '运动休闲', '轻户外'],  
photo: ['全部', '酒吧夜色', '城市街拍', '海边日落', '咖啡馆', '公园绿地', '天台屋顶', '室内光影', '旅行途中']
};
export const NOTE = { 
'简约干净':'看配色与轮廓，留意基础款之间的比例。','日系 Cityboy':'宽松剪裁与叠穿层次，让日常搭配更自然。','韩系休闲':'简洁色彩、利落比例，轻松又有细节。','街头潮流':'留意廓形、配饰与鞋裤之间的关系。','复古美式':'丹宁、皮革与旧色调，搭出松弛的层次。','运动休闲':'运动单品融入日常，舒适也可以很好看。','轻户外':'功能外套与自然色系，适合城市和户外。', 
'酒吧夜色':'参考吧台、暖色点光源和环境反射；让人物自然停留在光线里。','城市街拍':'借橱窗、转角和街灯作背景，走动、回头比正对镜头更自然。','海边日落':'选择日落前后的柔光，保留天空与海面，用侧脸或背影带出空间。','咖啡馆':'靠窗坐下，借侧面自然光；喝咖啡、看窗外，让动作有生活感。','公园绿地':'树荫、草地和长椅都是背景，利用枝叶前景和斑驳光线。','天台屋顶':'靠近傍晚拍摄，利用栏杆、楼体和天空分层，选择安全开放的场地。','室内光影':'靠窗的侧光、镜面和日常物件，比复杂布景更容易拍出氛围。','旅行途中':'车窗、步道与路边小店，保留途中自然发生的瞬间。'
};
export function safeURL(value){try{const u=new URL(value);return u.protocol==='https:'?u.href:''}catch{return ''}}
export function normalizeItems(raw){const images=new Set();const ids=new Set();return (Array.isArray(raw)?raw:[]).filter(p=>p&&typeof p==='object').flatMap(p=>{const key=p.imageKey||safeURL(p.originalImage||p.image);const id=String(p.id||key);const channel=p.channel;if(!key||images.has(key)||ids.has(id)||!CATEGORIES[channel]||!CATEGORIES[channel].includes(p.category)||p.category==='全部'||!safeURL(p.url))return [];const image=typeof p.image==='string'&&/^images\/[a-f0-9]+\.jpg$/.test(p.image)?p.image:safeURL(p.image);if(!image)return [];images.add(key);ids.add(id);return [{...p,id,image,title:String(p.title||p.category),originalTitle:String(p.originalTitle||''),source:String(p.source||'来源'),tags:Array.isArray(p.tags)?p.tags.map(String):[]}];});}
export function filterItems(items,{channel,category='全部',source='all',query='',savedOnly=false,saved=new Set(),hidden=new Set()}){const q=query.trim().toLowerCase();return items.filter(p=>p.channel===channel&&!hidden.has(p.id)&&(!savedOnly||saved.has(p.id))&&(category==='全部'||p.category===category)&&(source==='all'||p.source===source)&&(!q||[p.title,p.originalTitle,p.category,p.source,...p.tags].join(' ').toLowerCase().includes(q)));}
export function orderItems(items,seen=new Set(),sort='discover',random=Math.random){const copy=items.slice();if(sort==='latest')return copy.sort((a,b)=>String(b.collectedAt||'').localeCompare(String(a.collectedAt||'')));for(let i=copy.length-1;i>0;i--){let j=Math.floor(random()*(i+1));[copy[i],copy[j]]=[copy[j],copy[i]];}return [...copy.filter(p=>!seen.has(p.id)),...copy.filter(p=>seen.has(p.id))];}

export function heatScore(p){const m=p.engagement||{};return Math.max(Number(m.likes)||0,Number(m.favorites)||0,(Number(m.views)||0)/100)}
export function isPopular(p){return heatScore(p)>=100||!!(p.ranking&&p.ranking.name&&Number(p.ranking.position)>0)}
export function heatText(p){const m=p.engagement||{},parts=[];if(p.ranking?.name&&Number(p.ranking.position)>0)parts.push(p.ranking.name+' #'+p.ranking.position);for(const [key,label] of [['likes','点赞'],['favorites','收藏'],['views','浏览']])if(Number.isSafeInteger(m[key])&&m[key]>=0)parts.push(m[key].toLocaleString('zh-CN')+' '+label);return parts.join(' · ')||'来源未提供热度数据'}
