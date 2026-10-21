"""On-demand public-image discovery. Stores URLs in bounded RAM; never stores image files."""
import concurrent.futures as cf
import hashlib, html, json, os, re, threading, time
from pathlib import Path
import mimetypes
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
CACHE=OrderedDict();LOCK=threading.Lock();GATE=threading.BoundedSemaphore(4)

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
  n=cursor*2+k;cat=cats[n%len(cats)];variant=(n//len(cats))%4;page=n//(len(cats)*4)
  jobs.append((channel,cat,TOPICS[channel][cat][variant],page))
 return jobs

def query(job):
 ch,cat,q,page=job;cachekey=(q,page)
 with LOCK:
  hit=CACHE.get(cachekey)
  if hit and time.monotonic()-hit[0]<180:return hit[1],True
 params=urlencode({'q':q+' site:pinterest.com','first':page*35,'count':35},quote_via=quote)
 url='https://www.bing.com/images/async?'+params
 request=Request(url,headers={'User-Agent':'Mozilla/5.0','Accept-Language':'en-US,en;q=0.8'})
 try:
  with urlopen(request,timeout=9) as r:
   if r.status!=200:raise OSError('upstream unavailable')
   raw=r.read(4_000_001)
   if len(raw)>4_000_000:raise OSError('response too large')
  text=raw.decode('utf-8','replace')
  if re.search(r'captcha|Our systems have detected unusual traffic',text,re.I):raise OSError('source unavailable')
  result=parse_images(text,ch,cat)
  with LOCK:
   CACHE[cachekey]=(time.monotonic(),result);CACHE.move_to_end(cachekey)
   while len(CACHE)>128:CACHE.popitem(last=False)
  return result,True
 except Exception:return [],False

FLICKR_SCENES={'酒吧夜色':['bar','nightlife','pub','night'],'城市街拍':['street','urban','city','streetphotography'],'海边日落':['beach','sea','seaside','ocean'],'咖啡馆':['cafe','coffee','coffeeshop','café'],'公园绿地':['park','forest','garden','nature'],'天台屋顶':['rooftop','terrace','roof','skyline'],'室内光影':['window','indoor','indoors','windowlight'],'旅行途中':['travel','train','journey','traveler']}
FLICKR_STYLES={'简约干净':['minimalist','casual','minimalism','outfit'],'日系 Cityboy':['cityboy','japanesefashion','streetfashion','japan'],'韩系休闲':['koreanfashion','korea','casual','outfit'],'街头潮流':['streetwear','streetstyle','urbanfashion','ootd'],'复古美式':['vintage','denim','americana','vintagefashion'],'运动休闲':['sportswear','sporty','tracksuit','athleisure'],'轻户外':['gorpcore','outdoor','hiking','outdoorfashion']}
def flickr(job,cursor):
 ch,cat,_,page=job
 tags=(FLICKR_SCENES if ch=='photo' else FLICKR_STYLES)[cat]
 target=tags[cursor%len(tags)]
 person=['man','male','youngman','asianman'][(cursor//len(tags))%4]
 query_tags=[target,person]
 if ch=='outfit':query_tags.append('fashion')
 if cursor>=16:query_tags.append(['portrait','candid','film','lifestyle','summer','sunset','photography','35mm'][(cursor//16-1)%8])
 url='https://www.flickr.com/services/feeds/photos_public.gne?'+urlencode({'format':'json','nojsoncallback':1,'tags':','.join(query_tags),'tagmode':'all'},quote_via=quote)
 try:
  with urlopen(Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=9) as r:data=json.loads(r.read(2_000_000))
  result=[]
  for row in data.get('items',[]):
   text=' '.join([row.get('title',''),row.get('tags',''),row.get('description','')]);image=row.get('media',{}).get('m','');page_url=row.get('link','')
   if BAD.search(text) or re.search(r'\b(?:female|woman|girl|elderly|oldman|generated|midjourney|stablediffusion)\b',text,re.I):continue
   if not image.startswith('https://live.staticflickr.com/') or not page_url.startswith('https://www.flickr.com/photos/'):continue
   # Keep the published preview URL. Higher-resolution URLs are not guessed.
   uid=identity(image);result.append({'id':uid,'imageKey':uid,'image':re.sub(r'_m(\.[a-z]+)$',r'_b\1',image),'originalImage':image,'thumbnail':image,'url':page_url,'source':'Flickr','originalTitle':row.get('title',''),'title':cat+' · '+('日常搭配' if ch=='outfit' else '生活摄影'),'channel':ch,'category':cat,'tags':row.get('tags','').split()[:20],'collectedAt':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())})
  return result,True
 except Exception:return [],False

def discover(channel,category,cursor):
 jobs=plan(channel,category,cursor);tasks=[POOL.submit(query,j) for j in jobs]+[POOL.submit(flickr,j,cursor) for j in jobs];done,_=cf.wait(tasks,timeout=11)
 result={};successful=0
 for f in done:
  batch,ok=f.result();successful+=int(ok)
  for p in batch:result[p['id']]=p
 return {'items':list(result.values()),'nextCursor':cursor+1,'hasMore':True,'sourceAvailable':successful>0,'mode':'live','checkedAt':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}

class Handler(BaseHTTPRequestHandler):
 def send(self,status,data):
  body=json.dumps(data,ensure_ascii=False,separators=(',',':')).encode();self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
 def do_GET(self):
  u=urlparse(self.path)
  if u.path=='/api/health':return self.send(200,{'ok':True,'mode':'live','imageStorage':False})
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
