"""On-demand public-image discovery. Stores URLs in bounded RAM; never stores image files."""
import concurrent.futures as cf
import hashlib, html, json, os, re, threading, time, subprocess
from pathlib import Path
import mimetypes
import visual_filter
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse, quote
from urllib.request import Request, urlopen

TOPICS={
'outfit':{
 '简约干净':['minimal men outfit street','clean Asian menswear outfit','Korean simple men outfit','minimalist men casual outfit'],
 '日系 Cityboy':['cityboy outfit men','Japanese cityboy outfit','日系 男生 穿搭','Japanese men casual street outfit'],
 '韩系休闲':['korean men outfit','Korean boy casual outfit','韩系 男生 穿搭','Korean men summer outfit'],
 '街头潮流':['Asian men streetwear outfit','young men oversized streetwear','男生 街头 穿搭','men street style outfit'],
 '复古美式':['Asian men vintage outfit','men vintage americana outfit','男生 美式复古 穿搭','men vintage denim outfit'],
 '运动休闲':['men sporty casual outfit','Korean men track jacket outfit','男生 运动休闲 穿搭','men sportswear street outfit'],
 '轻户外':['gorpcore men outfit','Asian men outdoor outfit','男生 轻户外 穿搭','Japanese men hiking outfit']},
'photo':{
 '酒吧夜色':['man bar portrait photography','Korean boy bar aesthetic','男生 酒吧 氛围感 摄影','man cafe bar night photography'],
 '城市街拍':['man street candid photography','Korean boy street night portrait','男生 街拍 氛围感 摄影','Asian man city film photography'],
 '海边日落':['man beach portrait photography','Korean boy beach photography','男生 海边 氛围感 摄影','Asian man seaside sunset film'],
 '咖啡馆':['man cafe photography','Korean boy coffee aesthetic','男生 咖啡馆 氛围感 摄影','Asian man cafe candid portrait'],
 '公园绿地':['man park portrait photography','Korean boy park picnic','男生 公园 氛围感 摄影','Asian man forest film portrait'],
 '天台屋顶':['man rooftop portrait photography','Korean boy rooftop aesthetic','男生 天台 摄影','young man rooftop sunset portrait'],
 '室内光影':['man window light portrait','Korean boy indoor photography','男生 室内 光影 摄影','Asian man bedroom film portrait'],
 '旅行途中':['man travel candid photography','Korean boy train travel','男生 旅行 胶片 摄影','Asian man travel street photography']}}
BAD=re.compile(r'\b(?:beard|bearded|women|woman|girls?|nude|shirtless|collage|drawing|illustration|cartoon|prompt|midjourney|gemini|AI.generated|AI art|AI photo|stock photo|stock image|mature|older|haircut|hairstyle|grammar|alphabet|hangul|learning|language|recipe|wallpaper|lyrics)\b|大叔|中年|女装|女头|拼图|宫格|提示词|AI生成',re.I)
MALE=re.compile(r'\b(?:men|man|mens|male|boy|boys|menswear|cityboy|gorpcore)\b|男|メンズ|男性|남자|남성',re.I)
STYLE=re.compile(r'\b(?:outfit|outfits|streetwear|menswear|casual|cityboy|gorpcore|fashion|clothing)\b|穿搭|コーデ|스타일',re.I)
SCENES={'酒吧夜色':r'bar|night|drink|酒吧','城市街拍':r'street|urban|city|街','海边日落':r'beach|sea|ocean|summer|海','咖啡馆':r'cafe|café|coffee|咖啡','公园绿地':r'park|picnic|forest|garden|公园','天台屋顶':r'rooftop|roof|天台|屋顶','室内光影':r'window|indoor|bedroom|room|窗|室内','旅行途中':r'travel|train|journey|trip|旅行'}
POOL=cf.ThreadPoolExecutor(max_workers=6)
CACHE=OrderedDict();LOCK=threading.Lock();GATE=threading.BoundedSemaphore(2)
VISUAL_POOL=cf.ThreadPoolExecutor(max_workers=4)

def read_public(url):
 result=subprocess.run(['curl','--http1.1','--fail','--silent','--show-error','--connect-timeout','3','--max-time','5','--retry','1','--retry-delay','0','--retry-all-errors','-H','Accept-Region: jp','-H','Accept-Language: ja',url],capture_output=True,timeout=11,check=True)
 if len(result.stdout)>4_000_000:raise ValueError('response too large')
 return result.stdout

def read_image(url):
 result=subprocess.run(['curl','--http1.1','--fail','--silent','--show-error','--connect-timeout','2','--max-time','3','--max-filesize','4000000',url],capture_output=True,timeout=4,check=True)
 if len(result.stdout)>4_000_000:raise ValueError('image too large')
 return result.stdout

def source(url):
 try:
  u=urlparse(url);h=u.hostname or ''
  if u.scheme!='https':return None
  if re.fullmatch(r'(?:[a-z]{2,3}\.)?pinterest\.(?:com|co\.uk|jp|fr|de|ca|es|it|com\.au|com\.mx)',h):return 'Pinterest' if '/pin/' in u.path else None
  for host,label in [('instagram.com','Instagram'),('xiaohongshu.com','小红书'),('wear.jp','WEAR'),('musinsa.com','MUSINSA'),('uniqlo.com','StyleHint'),('beams.co.jp','BEAMS'),('lemon8-app.com','Lemon8'),('dappei.com','Dappei')]:
   if h==host or h.endswith('.'+host):
    if label=='Instagram' and not u.path.startswith('/p/'):return None
    if label=='MUSINSA' and not u.path.startswith('/snap/'):return None
    if label=='StyleHint' and 'styling' not in u.path:return None
    if label=='BEAMS' and '/styling/' not in u.path:return None
    if label=='WEAR' and not re.search(r'/\d+/$',u.path):return None
    return label
 except ValueError:pass
 return None

def identity(url):
 u=urlparse(url);p=u.path
 if (u.hostname or '').endswith('pinimg.com'):
  m=re.search(r'/([a-f0-9]{32})\.',p)
  if m:return m[1]
 return hashlib.sha256((u.netloc+p).encode()).hexdigest()[:32]

def parse_images(text,channel,category):
 found={}
 for raw in re.findall(r'\bm="([^"]+)"',text):
  try:d=json.loads(html.unescape(raw))
  except (ValueError,TypeError):continue
  title=html.unescape(d.get('t') or d.get('desc') or '').replace('\ue000','').replace('\ue001','')
  page=d.get('purl','');image=d.get('murl','');label=source(page)
  if not label or not image.startswith('https://') or BAD.search(title) or not MALE.search(title):continue
  if channel=='outfit' and not STYLE.search(title):continue
  if channel=='photo' and not re.search(SCENES[category],title,re.I):continue
  # Prefer individual photographs, not broad boards, shopping pages, or video.
  if re.search(r'/reel/|/video/|/ideas/',page):continue
  uid=identity(image);thumb=d.get('turl','')
  if not re.match(r'^https://(?:tse?\d|ts\d)\.mm\.bing\.net/',thumb):thumb=''
  found[uid]={'id':uid,'imageKey':uid,'image':image,'originalImage':image,'thumbnail':thumb,'url':page,'source':label,'originalTitle':title[:350],'title':category+' · '+('日常搭配' if channel=='outfit' else '生活摄影'),'channel':channel,'category':category,'tags':[],'collectedAt':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}
 return list(found.values())

def plan(channel,category,cursor):
 cats=list(TOPICS[channel]) if category=='全部' else [category]
 jobs=[]
 for k in range(2):
  n=cursor*2+k;cat=cats[n%len(cats)];variant=(n//len(cats))%4;page=cursor//2
  jobs.append((channel,cat,TOPICS[channel][cat][variant],page))
 return jobs

DUITANG_QUERIES={
'简约干净':['男生简约穿搭','男生日常穿搭','男生干净穿搭','简约男装'],
'日系 Cityboy':['日系男生穿搭','cityboy男生','日系男装','日系穿搭男'],
'韩系休闲':['韩系男生穿搭','韩国男生穿搭','韩系男装','男生休闲穿搭'],
'街头潮流':['男生街头穿搭','男生潮流穿搭','街头男装','男生宽松穿搭'],
'复古美式':['男生复古穿搭','美式复古男生','阿美咔叽男','男生牛仔穿搭'],
'运动休闲':['男生运动穿搭','男生运动休闲','男生卫衣穿搭','运动风男生'],
'轻户外':['男生户外穿搭','山系穿搭男','男生冲锋衣穿搭','机能风男生'],
'酒吧夜色':['男生酒吧拍照','男生夜晚氛围感','男生酒吧','男生夜景摄影'],
'城市街拍':['男生街拍氛围感','男生街头摄影','男生夜景街拍','男生街拍'],
'海边日落':['男生海边氛围感','男生海边摄影','男生海边日落','男生海边'],
'咖啡馆':['男生咖啡馆拍照','男生咖啡店氛围感','男生咖啡馆','男生咖啡店'],
'公园绿地':['男生公园拍照','男生草地摄影','男生树林氛围感','男生公园'],
'天台屋顶':['男生天台拍照','男生天台氛围感','男生屋顶摄影','男生天台'],
'室内光影':['男生室内光影','男生窗边摄影','男生室内氛围感','男生房间摄影'],
'旅行途中':['男生旅行摄影','男生旅行氛围感','男生车窗摄影','男生旅行拍照']}
# Search relevance is not evidence of the subject. Unknown captions fail closed.
EXCLUDE_SUBJECT=re.compile(r'女|卡通|动漫|动画|漫画|二次元|插画|手绘|绘画|绘本|同人|乙游|游戏|建模|渲染|虚拟|纸片|男头|头像|情侣|情头|壁纸|表情包|Q版|正太|少年感插图|(?<![A-Za-z])AI(?![A-Za-z])|大胡子|胡须|胡子|老年|大叔|中年|beard|anime|cartoon|illustration|drawing|render|female|woman|women|girl|avatar',re.I)
REAL_PHOTO=re.compile(r'真人|实拍|摄影|写真|街拍|自拍|胶片|拍照|拍摄|生活照|日常照|人像|photograph|portrait|street.?snap|real.?photo',re.I)
PERSON_MALE=re.compile(r'男生|男士|男性|男孩|男模|男装|男友|男人|menswear|\b(?:men|man|male|boy)\b',re.I)
def eligible_person(row,channel,category):
 caption=str(row.get('msg') or '')
 album=row.get('album') or {}
 tags=row.get('tags') or []
 text=caption+' '+json.dumps(tags,ensure_ascii=False)+' '+str(album.get('name',''))
 if BAD.search(text) or EXCLUDE_SUBJECT.search(text):return False
 # Require affirmative male and real-photography evidence from the original post,
 # never from our search query or a generated category label.
 if not PERSON_MALE.search(caption) and not visual_filter.ready():return False
 if not REAL_PHOTO.search(text) and not visual_filter.ready():return False
 if channel=='outfit' and not STYLE.search(caption):return False
 if channel=='photo' and not re.search(SCENES[category],text,re.I):return False
 return True

def count_value(row,key):
 value=row.get(key)
 if isinstance(value,bool):return None
 try:
  n=int(value)
  return n if n>=0 else None
 except (TypeError,ValueError,OverflowError):return None

def engagement(row):
 return {'likes':count_value(row,'like_count'),'favorites':count_value(row,'favorite_count'),'views':count_value(row,'view_count')}

def heat_value(item):
 m=item.get('engagement') or {}
 return max(m.get('likes') or 0,m.get('favorites') or 0,(m.get('views') or 0)/100)

def has_heat(item):
 return heat_value(item)>=100 or bool(item.get('ranking'))

def duitang(job,cursor):
 ch,cat,_,page=job
 # The cursor advances query variants and the provider's genuine start offset.
 # Query and page are already determined by the shared pagination plan.
 variant=TOPICS[ch][cat].index(job[2])
 search=DUITANG_QUERIES[cat][variant]
 params=urlencode({'kw':search,'type':'feed','start':page*36,'limit':36,'include_fields':'like_count,favorite_count,source_link'},quote_via=quote)
 url='https://www.duitang.com/napi/blog/list/by_search/?'+params
 cachekey=('duitang-engagement',cat,variant,page)
 with LOCK:
  hit=CACHE.get(cachekey)
  if hit and time.monotonic()-hit[0]<120:return hit[1],True
 try:
  raw=json.loads(read_public(url))
  if raw.get('status')!=1:return [],False
  rows=raw.get('data',{}).get('object_list',[]);result=[]
  for row in rows:
   p=row.get('photo') or {};image=p.get('path','');msg=row.get('msg','');w=p.get('width',0);h=p.get('height',0)
   if row.get('short_video') or row.get('buyable') or p.get('aigc_label',-1)>0 or not eligible_person(row,ch,cat):continue
   if not image.startswith('https://') or not re.fullmatch(r'(?:[a-z0-9-]+\.)*(?:dtstatic\.com|duitang\.com)',urlparse(image).hostname or ''):continue
   if not w or not h or min(w,h)<280 or w/h>1.7 or w/h<.48:continue
   uid=identity(image);result.append({'id':uid,'imageKey':uid,'image':image,'originalImage':image,'url':'https://www.duitang.com/blog/?id='+str(row['id']),'source':'堆糖','engagement':engagement(row),'originalTitle':msg[:350],'title':cat+' · '+('日常搭配' if ch=='outfit' else '生活摄影'),'channel':ch,'category':cat,'tags':[],'width':w,'height':h,'collectedAt':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())})
  if visual_filter.ready():
   candidates=sorted(result,key=heat_value,reverse=True)[:12]
   checks=list(VISUAL_POOL.map(lambda p:visual_filter.accept(p['image'],read_image),candidates))
   result=[{**p,'visualChecked':True} for p,ok in zip(candidates,checks) if ok]
  with LOCK:
   CACHE[cachekey]=(time.monotonic(),result);CACHE.move_to_end(cachekey)
   while len(CACHE)>128:CACHE.popitem(last=False)
  return result,True
 except Exception:return [],False

STYLEHINT_STYLES={
 '日系 Cityboy':r'シティボーイ|cityboy|オーバーサイズ|ワイド|レイヤード',
 '韩系休闲':r'韓国|韓流|korean',
 '街头潮流':r'ストリート|street|スウェット|カーゴ',
 '复古美式':r'ヴィンテージ|ビンテージ|アメカジ|デニム|vintage',
 '运动休闲':r'スポーツ|スポーティ|トラック|ジャージ|sport',
 '轻户外':r'アウトドア|ハイキング|登山|ゴープ|outdoor',
 '简约干净':r'シンプル|きれいめ|ベーシック|ミニマル|simple|minimal'}
STYLEHINT_SCENES={'酒吧夜色':r'バー|夜景|night|bar','城市街拍':r'街|ストリート|street|city','海边日落':r'海辺|ビーチ|夕日|beach|sunset','咖啡馆':r'カフェ|珈琲|cafe|coffee','公园绿地':r'公園|森林|park|forest','天台屋顶':r'屋上|rooftop','室内光影':r'室内|窓辺|window|indoor','旅行途中':r'旅行|旅先|電車|travel|train'}

def stylehint_category(caption,channel):
 patterns=STYLEHINT_STYLES if channel=='outfit' else STYLEHINT_SCENES
 return next((cat for cat,pattern in patterns.items() if re.search(pattern,caption,re.I)), '简约干净' if channel=='outfit' else None)

def stylehint(channel,category,cursor):
 # A real public men's daily ranking; page and rank are supplied by StyleHint.
 cachekey=('stylehint',channel,category,cursor)
 with LOCK:
  hit=CACHE.get(cachekey)
  if hit and time.monotonic()-hit[0]<120:return hit[1],True
 try:
  params=urlencode({'result_limit':36,'page':cursor+1,'option_gender':1,'ranking_manner':'daily_ranking','option_recency':1})
  data=json.loads(read_public('https://www.stylehint.com/v2/jp/outfit?'+params))
  if not isinstance(data.get('outfit_list'),list):return [],False
  result=[]
  for row in data['outfit_list']:
   caption=str(row.get('caption') or '');cat=stylehint_category(caption,channel)
   image=row.get('source_image_url') or '';outfit_id=count_value(row,'id_outfit');rank=count_value(row,'ranking_number')
   if not cat or category!='全部' and category!=cat or not outfit_id or not rank:continue
   if urlparse(image).scheme!='https' or urlparse(image).hostname!='api.stylehint.com':continue
   if BAD.search(caption) or EXCLUDE_SUBJECT.search(caption):continue
   uid=identity(image)
   result.append({'id':uid,'imageKey':uid,'image':image,'originalImage':image,'url':'https://www.stylehint.com/jp/ja/outfit/'+str(outfit_id),'source':'StyleHint','ranking':{'name':'男装日榜','position':rank},'engagement':{'likes':None,'favorites':count_value(row,'star_count'),'views':None},'originalTitle':caption[:1000],'title':cat+' · '+('日常搭配' if channel=='outfit' else '生活摄影'),'channel':channel,'category':cat,'tags':[],'collectedAt':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())})
  # Never bypass the same subject screening used for Duitang.
  candidates=result[:12]
  checks=list(VISUAL_POOL.map(lambda p:visual_filter.accept(p['image'],read_image),candidates))
  result=[{**p,'visualChecked':True} for p,ok in zip(candidates,checks) if ok]
  with LOCK:
   CACHE[cachekey]=(time.monotonic(),result);CACHE.move_to_end(cachekey)
   while len(CACHE)>128:CACHE.popitem(last=False)
  return result,True
 except Exception:return [],False

def discover(channel,category,cursor):
 jobs=plan(channel,category,cursor)
 tasks={POOL.submit(duitang,j,cursor):'堆糖' for j in jobs}
 tasks[POOL.submit(stylehint,channel,category,cursor)]='StyleHint'
 done,pending=cf.wait(tasks,timeout=30)
 for f in pending:f.cancel()
 result={};statuses={'堆糖':False,'StyleHint':False}
 for f in done:
  try:batch,ok=f.result()
  except Exception:continue
  statuses[tasks[f]]|=ok
  for p in batch:result[p['id']]=p
 rows=sorted(result.values(),key=lambda p:(bool(p.get('ranking')),heat_value(p)),reverse=True)
 return {'items':rows,'nextCursor':cursor+1,'hasMore':True,'sourceAvailable':any(statuses.values()),'sources':[{'name':name,'available':ok} for name,ok in statuses.items()],'mode':'live','checkedAt':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}

class Handler(BaseHTTPRequestHandler):
 def send(self,status,data):
  body=json.dumps(data,ensure_ascii=False,separators=(',',':')).encode();self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
 def do_GET(self):
  u=urlparse(self.path)
  if u.path=='/api/health':return self.send(200,{'ok':True,'mode':'live','imageStorage':False,'visualScreening':visual_filter.ready(),'version':'multi-source-heat-v1','providers':['堆糖','StyleHint']})
  if u.path!='/api/discover':
   name='index.html' if u.path=='/' else u.path.lstrip('/')
   if name not in {'index.html','app.js','style.css','feed-utils.js','sw.js'}:return self.send(404,{'error':'not_found'})
   body=(Path(__file__).resolve().parent/name).read_bytes();self.send_response(200);self.send_header('Content-Type',mimetypes.guess_type(name)[0] or 'application/octet-stream');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body);return
  q=parse_qs(u.query);channel=q.get('channel',['outfit'])[0];category=q.get('category',['全部'])[0]
  try:cursor=int(q.get('cursor',['0'])[0])
  except ValueError:return self.send(400,{'error':'invalid_cursor'})
  if channel not in TOPICS or category!='全部' and category not in TOPICS[channel] or not 0<=cursor<=100000:return self.send(400,{'error':'invalid_filter'})
  if not GATE.acquire(blocking=False):return self.send(429,{'error':'busy','retryAfter':3})
  try:
   data=discover(channel,category,cursor);self.send(200 if data['sourceAvailable'] else 503,data)
  except (BrokenPipeError,ConnectionResetError):pass
  finally:GATE.release()
 def log_message(self,fmt,*args):print(fmt%args,flush=True)

if __name__=='__main__':ThreadingHTTPServer(('127.0.0.1',int(os.getenv('PORT','8794'))),Handler).serve_forever()
