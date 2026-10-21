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

