"""Public image discovery with cached previews, deduplication and honest timestamps."""
import argparse, concurrent.futures as cf, hashlib, html, io, json, re, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlparse
import requests
from PIL import Image, ImageOps
ROOT=Path(__file__).resolve().parent.parent
TOPICS=[('outfit','简约干净','Asian men minimalist clean casual outfit Pinterest'),('outfit','日系 Cityboy','Japanese cityboy men outfit Pinterest'),('outfit','韩系休闲','Korean men casual outfit Pinterest'),('outfit','街头潮流','young Asian men streetwear outfit Pinterest'),('outfit','复古美式','young men vintage americana outfit Pinterest'),('outfit','运动休闲','Korean men sporty track jacket outfit Pinterest'),('outfit','轻户外','Asian men gorpcore outdoor outfit Pinterest'),('photo','酒吧夜色','Korean boy bar aesthetic photography Pinterest'),('photo','城市街拍','Korean boy street night photography Pinterest'),('photo','海边日落','Korean boy beach photography Pinterest'),('photo','咖啡馆','Korean boy cafe aesthetic photography Pinterest'),('photo','公园绿地','Korean boy park picnic photography Pinterest'),('photo','天台屋顶','Korean boy rooftop aesthetic Pinterest'),('photo','室内光影','Korean boy window light portrait Pinterest'),('photo','旅行途中','Korean boy train travel photography Pinterest')]
BLOCK=re.compile(r'\b(?:beard|bearded|women|woman|girls?|nude|shirtless|collage|collages|drawing|illustration|cartoon|prompt|midjourney|gemini|AI generated|AI-generated|AI art|AI photo|stock photo|stock image|wedding|mature|older)\b|拼图|大叔|中年|女装|女头|四宫格|九宫格',re.I)
MALE=re.compile(r'\b(?:men|man|mens|menswear|male|boy|boys|cityboy|gorpcore|yoonho|minhyun|outfit)\b|男|メンズ|男性|남자|남성',re.I)
def source(url):
 try:
  u=urlparse(url);h=u.hostname or ''
  if u.scheme!='https':return None
  if re.fullmatch(r'(?:[a-z]{2,3}\.)?pinterest\.(?:com|co\.uk|jp|fr|de|ca|es|it|com\.au|com\.mx)',h):return 'Pinterest' if '/pin/' in u.path else None
  for host,label in [('instagram.com','Instagram'),('xiaohongshu.com','小红书'),('wear.jp','WEAR'),('musinsa.com','MUSINSA'),('uniqlo.com','StyleHint'),('stylehint.com','StyleHint'),('beams.co.jp','BEAMS'),('lemon8-app.com','Lemon8'),('dappei.com','Dappei'),('klook.com','Klook'),('teamlab.art','teamLab'),('siamzone.com','Instagram 转载')]:
   if h==host or h.endswith('.'+host):
    if label=='MUSINSA' and '/snap/' not in u.path:return None
    if label=='StyleHint' and not any(v in u.path for v in ['styling','stylehint']):return None
    if label=='BEAMS' and '/styling/' not in u.path:return None
    if label=='Instagram' and not re.match(r'^/p/',u.path):return None
    if label=='WEAR' and not re.search(r'/\d+/$',u.path):return None
    return label
 except ValueError:pass
 return None

def get(url):
 r=requests.get(url,headers={'User-Agent':'Mozilla/5.0'},timeout=(8,18),stream=True);r.raise_for_status();chunks=[];size=0
 for chunk in r.iter_content(65536):
  size+=len(chunk)
  if size>6_000_000:r.close();raise ValueError('too large')
  chunks.append(chunk)
 r.close();return b''.join(chunks)
def key(url):
 u=urlparse(url)
 if (u.hostname or '').endswith('pinimg.com'):
  m=re.search(r'/([a-f0-9]{32})\.',u.path)
  if m:return 'pin:'+m[1]
 return u.netloc+u.path
def item(image,url,title,ch,cat):
 return {'id':hashlib.sha256(key(image).encode()).hexdigest()[:24],'imageKey':key(image),'originalImage':image,'url':url,'source':source(url),'originalTitle':title[:350],'title':cat+' · '+('日常搭配' if ch=='outfit' else '生活摄影'),'channel':ch,'category':cat,'tags':[]}
def parse(text,ch,cat):
 out=[]
 for raw in re.findall(r'\bm="([^"]+)"',text):
  try:d=json.loads(html.unescape(raw))
  except (ValueError,TypeError):continue
  title=html.unescape(d.get('t') or d.get('desc') or '').replace('\ue000','').replace('\ue001','');url=d.get('purl','');image=d.get('murl','')
  if not re.search(r'language|learning|hangul|alphabet|chart|grammar|recipe|tutorial|wallpaper|lyrics|haircut|hairstyle|runway|collection|suit',title,re.I) and source(url) and image.startswith('https://') and not BLOCK.search(title) and MALE.search(title) and (bool(re.search(r'outfit|streetwear|menswear|gorpcore|cityboy|casual|穿搭|コーデ|스타일',title,re.I)) if ch=='outfit' else bool(re.search({'酒吧夜色':r'bar|night|drink|酒吧','城市街拍':r'street|urban|city|街','海边日落':r'beach|sea|ocean|summer|海','咖啡馆':r'cafe|café|coffee|咖啡','公园绿地':r'park|picnic|forest|garden|公园','天台屋顶':r'rooftop|roof|天台|屋顶','室内光影':r'window|indoor|bedroom|room|窗|室内','旅行途中':r'travel|train|journey|trip|旅行'}[cat],title,re.I))):out.append(item(image,url,title,ch,cat))
 return out
def discover(topic,page):
 ch,cat,q=topic
 params={'q':q,'first':page*35,'count':35}
 try:
  found=parse(get('https://www.bing.com/images/async?'+urlencode(params)).decode('utf-8','replace'),ch,cat);print(cat,page,len(found),flush=True);return found
 except Exception as e:print(cat,type(e).__name__,flush=True);return []
def seed():
 out=[]
 for p in json.loads((ROOT/'seed-research.json').read_text()):
  q=p['q'];ch='photo' if any(x in q for x in ['photograph','portrait','氛围','aesthetic','cafe photography']) and 'outfit' not in q else 'outfit'
  if ch=='outfit':cat='轻户外' if 'gorpcore' in q else '日系 Cityboy' if 'cityboy' in q.lower() else '复古美式' if 'vintage' in q or 'denim' in q else '运动休闲' if '运动' in q or 'sporty' in q or 'track jacket' in q else '街头潮流' if 'streetwear' in q else '简约干净' if 'minimal' in q.lower() else '韩系休闲'
  else:cat=next((c for terms,c in [(['bar','酒吧'],'酒吧夜色'),(['beach','海边'],'海边日落'),(['cafe','coffee','咖啡'],'咖啡馆'),(['rooftop','天台'],'天台屋顶'),(['park','公园'],'公园绿地'),(['bedroom','indoor','window'],'室内光影'),(['travel'],'旅行途中')] if any(t in q for t in terms)),'城市街拍')
  if source(p['url']) and not BLOCK.search(p.get('description','')):out.append(item(p['image'],p['url'],p['title'],ch,cat))
 return out
def dhash(im):
 a=list(im.convert('L').resize((9,8)).getdata());return sum(1<<(r*8+c) for r in range(8) for c in range(8) if a[r*9+c]>a[r*9+c+1])
def cache(p,base=''):
 path=ROOT/'images'/f"{p['id']}.jpg"
 try:
  if path.exists():im=Image.open(path);im.load()
  else:
   if base and p.get('image','').startswith('images/'):
    try:blob=get(base.rstrip('/')+'/'+p['image'])
    except Exception:blob=get(p['originalImage'])
   else:blob=get(p['originalImage'])
   im=ImageOps.exif_transpose(Image.open(io.BytesIO(blob)));im.load()
  w,h=im.size
  if min(w,h)<280 or w/h>1.85 or w/h<.4:return None
  im=im.convert('RGB');im.thumbnail((1000,1400));p=dict(p,width=im.width,height=im.height,image='images/'+path.name,visualHash=f'{dhash(im):016x}')
  if not path.exists():
   tmp=path.with_suffix('.tmp');im.save(tmp,'JPEG',quality=85,optimize=True);tmp.replace(path)
  return p
 except Exception as e:print('preview unavailable',p['id'],type(e).__name__,flush=True);return None

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--discover',action='store_true');ap.add_argument('--previous-url',default='');ap.add_argument('--pages',type=int,default=2);ap.add_argument('--max-images',type=int,default=900);ap.add_argument('--workers',type=int,default=8);args=ap.parse_args()
 (ROOT/'images').mkdir(exist_ok=True);(ROOT/'data').mkdir(exist_ok=True);now=datetime.now(timezone.utc).isoformat();old={}
 if args.previous_url:
  try:old=json.loads(get(args.previous_url.rstrip('/')+'/data/feed.json'))
  except Exception:print('Live history unavailable; using repository cache.',flush=True)
 if not old and (ROOT/'data/feed.json').exists():old=json.loads((ROOT/'data/feed.json').read_text())
 old_by={p['id']:p for p in old.get('items',[])};candidates=[]
 if args.discover:
  pages=list(dict.fromkeys([0,1+int(time.time()/86400)%8]))[:args.pages]
  with cf.ThreadPoolExecutor(max_workers=3) as ex:
   for group in ex.map(lambda job:discover(*job),[(t,p) for t in TOPICS for p in pages]):candidates+=group
 candidates+=seed()+list(old_by.values());unique={};corrections=json.loads((ROOT/'data/corrections.json').read_text()) if (ROOT/'data/corrections.json').exists() else {};excluded=set(json.loads((ROOT/'data/excluded.json').read_text())) if (ROOT/'data/excluded.json').exists() else set()
 for p in candidates:
  k=key(p.get('originalImage',''))
  if not k or k in unique or p['id'] in excluded or BLOCK.search(p.get('originalTitle','')) or re.search(r'Language Learning|Hangul|haircut|hairstyle',p.get('originalTitle',''),re.I):continue
  p={**p,**corrections.get(p['id'],{})};prev=old_by.get(p['id'],{});unique[k]={**p,'collectedAt':prev.get('collectedAt',now),'image':prev.get('image',p.get('image',''))}
 buckets={}
 for p in unique.values():buckets.setdefault((p['channel'],p['category']),[]).append(p)
 ordered=[]
 while buckets and len(ordered)<args.max_images:
  for k in list(buckets):
   ordered.append(buckets[k].pop(0))
   if not buckets[k]:del buckets[k]
   if len(ordered)>=args.max_images:break
 kept=[];hashes=[]
 with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
  for p in ex.map(lambda p:cache(p,args.previous_url),ordered):
   if not p:continue
   vh=int(p['visualHash'],16)
   if any(bin(vh^h).count('1')<=3 for h in hashes):continue
   hashes.append(vh);kept.append(p)
 if len(kept)<12:raise RuntimeError('Too few verified previews; keeping published version unchanged')
 n=sum(p['id'] not in old_by for p in kept);updated=now if n else old.get('updatedAt',now)
 data={'schemaVersion':2,'updatedAt':updated,'checkedAt':now,'newCount':n,'items':kept}
 temp=ROOT/'data/feed.json.tmp';temp.write_text(json.dumps(data,ensure_ascii=False,separators=(',',':')));temp.replace(ROOT/'data/feed.json')
 active={Path(p['image']).name for p in kept}
 for file in (ROOT/'images').glob('*.jpg'):
  if file.name not in active:file.unlink()
 print(json.dumps({'images':len(kept),'new':n,'outfit':sum(p['channel']=='outfit' for p in kept),'photo':sum(p['channel']=='photo' for p in kept),'categories':{c:sum(p['category']==c for p in kept) for _,c,_ in TOPICS}},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
