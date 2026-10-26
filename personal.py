"""Private appearance libraries and durable GRsai photography jobs."""
from contextlib import contextmanager
from datetime import datetime,timedelta,timezone
import base64, concurrent.futures, hashlib, io, json, os, secrets, sqlite3, threading, time
from pathlib import Path
from http.cookies import SimpleCookie
from urllib.request import Request, urlopen, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError
from urllib.parse import urlparse, quote
from PIL import Image, ImageOps
import email_auth

IMAGE_MODEL='gpt-image-2'
REASON_MODEL='gpt-5.6-terra'
ROOT=Path(os.getenv('OOTD_PERSONAL_PATH',str(Path.home()/'.local/share/ootd-personal')))
WORKERS=concurrent.futures.ThreadPoolExecutor(max_workers=3)
ACTIVE=set(); GUARD=threading.RLock()
TERMINAL={'succeeded','failed','partial','uncertain'}
Image.MAX_IMAGE_PIXELS=35_000_000

class UserError(Exception):pass
class UnknownSubmission(UserError):pass

@contextmanager
def db():
 ROOT.mkdir(parents=True,exist_ok=True,mode=0o700)
 c=sqlite3.connect(ROOT/'personal.sqlite',timeout=20);c.row_factory=sqlite3.Row
 c.execute('PRAGMA journal_mode=WAL')
 c.executescript('''CREATE TABLE IF NOT EXISTS assets(id TEXT PRIMARY KEY,owner TEXT,path TEXT,created REAL);
 CREATE TABLE IF NOT EXISTS profiles(owner TEXT PRIMARY KEY,data TEXT);
 CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,owner TEXT,request_key TEXT,data TEXT,created REAL,UNIQUE(owner,request_key));
 CREATE TABLE IF NOT EXISTS image_credits(id TEXT PRIMARY KEY,owner TEXT,day TEXT,job TEXT,slot TEXT,state TEXT);
 CREATE INDEX IF NOT EXISTS credits_owner_day ON image_credits(owner,day);
 CREATE TABLE IF NOT EXISTS account_credit_limits(email TEXT PRIMARY KEY,daily_limit INTEGER NOT NULL CHECK(daily_limit>0));
 CREATE TABLE IF NOT EXISTS auth_accounts(id TEXT PRIMARY KEY,email TEXT UNIQUE,created REAL);
 CREATE TABLE IF NOT EXISTS auth_sessions(hash TEXT PRIMARY KEY,owner TEXT,email TEXT,expires REAL);
 CREATE TABLE IF NOT EXISTS auth_codes(email TEXT PRIMARY KEY,digest TEXT,expires REAL,attempts INTEGER,sent REAL);
 CREATE TABLE IF NOT EXISTS auth_mail_log(email TEXT,ip TEXT,created REAL);
 CREATE TABLE IF NOT EXISTS auth_attempts(ip TEXT,created REAL);''')
 try:
  with c:yield c
 finally:c.close()

def read_profile(owner):
 with db() as c:r=c.execute('SELECT data FROM profiles WHERE owner=?',(owner,)).fetchone()
 return json.loads(r[0]) if r else {'photos':[],'summary':None,'views':{}}

def save_profile(owner,p):
 with db() as c:c.execute('INSERT OR REPLACE INTO profiles VALUES(?,?)',(owner,json.dumps(p,ensure_ascii=False)))

def jobs(owner):
 with db() as c:rows=c.execute('SELECT data FROM jobs WHERE owner=? ORDER BY created DESC LIMIT 30',(owner,)).fetchall()
 return [json.loads(r[0]) for r in rows]

def load_job(jid):
 with db() as c:r=c.execute('SELECT data FROM jobs WHERE id=?',(jid,)).fetchone()
 return json.loads(r[0]) if r else None

SHANGHAI=timezone(timedelta(hours=8))
DAILY_CREDITS=10

def credit_day():return datetime.now(SHANGHAI).date().isoformat()

def credit_balance(owner,c=None):
 if c is None:
  with db() as connection:return credit_balance(owner,connection)
 account=c.execute('SELECT limits.daily_limit FROM auth_accounts AS account JOIN account_credit_limits AS limits ON limits.email=account.email WHERE account.id=?',(owner,)).fetchone()
 limit=account[0] if account else DAILY_CREDITS
 day=credit_day();rows=c.execute("SELECT state,COUNT(*) FROM image_credits WHERE owner=? AND day=? GROUP BY state",(owner,day)).fetchall();counts={r[0]:r[1] for r in rows}
 used=counts.get('charged',0);reserved=counts.get('reserved',0)
 reset=datetime.fromisoformat(day).replace(tzinfo=SHANGHAI)+timedelta(days=1)
 return {'remaining':max(0,limit-used-reserved),'limit':limit,'used':used,'reserved':reserved,'day':day,'resetAt':reset.isoformat()}

def reserve_credits(c,j,slots):
 needed=[]
 for slot in slots:
  if slot.get('asset'):continue
  old=c.execute('SELECT state FROM image_credits WHERE id=?',(slot.get('creditId',''),)).fetchone()
  if old and old[0] in {'reserved','charged'}:continue
  needed.append(slot)
 balance=credit_balance(j['owner'],c)
 if len(needed)>balance['remaining']:raise UserError('积分不足：本次需要 %d 积分，今日剩余 %d 积分；北京时间 0 点恢复至 %d 积分'%(len(needed),balance['remaining'],balance['limit']))
 for slot in needed:
  cid=secrets.token_hex(16);slot['creditId']=cid
  c.execute('INSERT INTO image_credits VALUES(?,?,?,?,?,?)',(cid,j['owner'],credit_day(),j['id'],slot['key'],'reserved'))

def save_job(j):
 j['updated']=time.time()
 with db() as c:
  c.execute('BEGIN IMMEDIATE')
  c.execute('UPDATE jobs SET data=? WHERE id=?',(json.dumps(j,ensure_ascii=False),j['id']))
  for slot in j['slots']:
   if not slot.get('creditId'):continue
   if slot.get('asset'):state='charged'
   elif slot.get('providerFailed') or (slot.get('providerCompleted') and j['status'] in TERMINAL) or (not slot.get('providerId') and slot.get('status') not in {'submitting','uncertain'} and (slot.get('status')=='failed' or j['status'] in TERMINAL)):state='refunded'
   else:continue
   c.execute("UPDATE image_credits SET state=? WHERE id=? AND state='reserved'",(state,slot['creditId']))


def clean_image(data):
 if len(data)>12_000_000:raise UserError('单张照片不能超过 12 MB')
 try:
  with Image.open(io.BytesIO(data)) as original:
   if original.format not in {'JPEG','PNG','WEBP'}:raise ValueError()
   image=ImageOps.exif_transpose(original).convert('RGB');image.thumbnail((1800,1800))
   if min(image.size)<160:raise ValueError()
   out=io.BytesIO();image.save(out,'JPEG',quality=92);return out.getvalue()
 except Exception:raise UserError('请选择清晰的 JPG、PNG 或 WebP 照片，短边至少 160 像素')

def store_asset(owner,data):
 data=clean_image(data);aid=secrets.token_hex(16);folder=ROOT/'images';folder.mkdir(mode=0o700,exist_ok=True)
 path=folder/(aid+'.jpg');path.write_bytes(data);path.chmod(0o600)
 with db() as c:c.execute('INSERT INTO assets VALUES(?,?,?,?)',(aid,owner,str(path),time.time()))
 return '/api/personal/assets/'+aid

def asset(owner,url):
 aid=url.rsplit('/',1)[-1]
 with db() as c:r=c.execute('SELECT path FROM assets WHERE id=? AND owner=?',(aid,owner)).fetchone()
 if not r:raise UserError('照片不存在或不属于当前形象库')
 return Path(r[0]).read_bytes()

def data_uri(owner,url):return 'data:image/jpeg;base64,'+base64.b64encode(asset(owner,url)).decode()

def api(path,body=None):
 key=os.getenv('GRSAI_API_KEY','').strip();base=os.getenv('GRSAI_BASE_URL','https://grsaiapi.com').rstrip('/')
 if not key:raise UserError('生图服务尚未配置，请稍后再试')
 req=Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
 try:
  with urlopen(req,timeout=125 if '/chat/' in path else 45) as r:result=json.loads(r.read(8_000_000))
 except HTTPError as e:
  try:
   d=json.loads(e.read(4000));error=d.get('error',{});msg=error.get('message','') if isinstance(error,dict) else str(error)
  except Exception:msg=''
  if '修复' in msg or 'maintenance' in msg.lower():raise UserError('GRsai：该模型正在修复，请稍后重试')
  raise UserError('GRsai 请求失败（%s）%s'%(e.code,'：'+msg[:160].replace(key,'[hidden]') if msg else ''))
 if not isinstance(result,dict):raise UserError('GRsai 返回格式无效')
 if result.get('error'):raise UserError('GRsai 未完成请求，请稍后重试')
 return result

def reason(prompt,images):
 content=[{'type':'text','text':prompt}]+[{'type':'image_url','image_url':{'url':u}} for u in images]
 r=api('/v1/chat/completions',{'model':REASON_MODEL,'messages':[{'role':'user','content':content}],'max_tokens':3500,'reasoning_effort':'low'})
 try:
  text=r['choices'][0]['message']['content'].strip()
  if text.startswith('```'):text=text.split('\n',1)[1].rsplit('```',1)[0]
  value=json.loads(text)
  if not isinstance(value,dict):raise ValueError()
  return value
 except Exception:raise UserError('形象分析未返回有效结果，请重试')

def remote_image(url):
 # Validate every redirect; never allow a client supplied host or a private endpoint.
 import server
 class SafeRedirect(HTTPRedirectHandler):
  def redirect_request(self,req,fp,code,msg,headers,newurl):
   if not server.public_url(newurl,resolve=True):raise UserError('图片地址不可用')
   return super().redirect_request(req,fp,code,msg,headers,newurl)
 if not server.public_url(url,resolve=True):raise UserError('图片地址不可用')
 try:
  with build_opener(SafeRedirect()).open(Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=40) as r:data=r.read(12_000_001)
  return clean_image(data)
 except UserError:raise
 except Exception:raise UserError('参考图或生成结果暂时无法下载，请重试')

def submit_image(prompt,images,size):
 r=api('/v1/api/generate',{'model':IMAGE_MODEL,'prompt':prompt,'images':images,'aspectRatio':size,'quality':'high','replyType':'async'})
 nested=r.get('data') or r.get('result') or r
 pid=nested.get('id') or r.get('id')
 if not pid:raise UnknownSubmission('GRsai 未返回任务编号；为避免重复计费，未自动重复提交')
 return str(pid)

def generated_url(r):
 for d in [r,r.get('data'),r.get('result')]:
  if not isinstance(d,dict):continue
  for p in d.get('results',[]):
   if isinstance(p,dict) and p.get('url'):return p['url']
  if d.get('url'):return d['url']
 return None

FACE_FRAMING='这是一张面部特写，EXTREME CLOSE-UP HEADSHOT，不是全身照、半身照或证件全身照。镜头只取完整头部、少量颈部与肩膀上缘；头顶到下巴占画面高度约70%至85%，脸部占画面宽度至少50%。人物正面直视镜头，清晰呈现眼睛、鼻子、嘴唇、皮肤细节。完整保留头发、耳朵和下巴，头顶留白不超过8%。画面下缘在锁骨附近截止，不得出现胸腹、腰、手、裤子、腿或鞋。背景只留少量干净浅灰区域。禁止远景、全身、宽松取景和大面积背景。'

def portrait_input(j,slot):
 if slot['key']=='face':
  summary=j.get('summary',{})
  return ('为身份参考中同一位成年人拍摄独立面部特写。严格保持本人的脸型五官、发型、年龄感与皮肤特征，不美化换脸。原片只提供人物身份，不沿用原片的身体姿势、远近或全身构图。自然柔和光线，不要文字、水印或拼图。'+FACE_FRAMING+'。本人面部特征参考：'+summary.get('description','')+'。实际穿戴配饰：'+json.dumps(summary.get('accessories',[]),ensure_ascii=False),'1024x1024')
 return j['prompt'],j['size']

def face_is_closeup(data):
 result=reason('只检查取景是否是面部特写，不判断身份或好看与否。返回严格 JSON：isCloseUp（布尔值，仅完整头部和少量肩颈为true；半身或全身为false），faceHeightRatio（头顶至下巴占整幅高度的比例0到1），faceWidthRatio（脸宽占整幅宽度的比例0到1）。若看见胸腹、腰、腿或鞋，isCloseUp 必须为false。', ['data:image/jpeg;base64,'+base64.b64encode(data).decode()])
 h=result.get('faceHeightRatio');w=result.get('faceWidthRatio')
 return result.get('isCloseUp') is True and type(h) in (float,int) and type(w) in (float,int) and .5<=h<=1 and .4<=w<=1

def execute(jid):
 j=load_job(jid)
 try:
  p=read_profile(j['owner']);images=[data_uri(j['owner'],u) for u in j['photos'][:6]]
  if not j.get('prompt'):
   j['stage']='分析形象' if j['kind'] in {'profile','face'} else '分析参考照片';save_job(j)
   if j['kind'] in {'profile','face'}:
    summary=reason('分析这些同一位成年人的照片，只写可见外观，不猜姓名、国籍、健康。返回 JSON：description（脸型、五官、发型、体态的具体中文描述），accessories（本人实际穿戴的配饰字符串数组，只包括眼镜、耳饰、项链、手表、戒指等，不包括杯子、手机、家具或背景道具；没有则返回空数组；只有单张照片时不要断言经常佩戴），missingViews（未见的正面、侧面、背面视角数组）。无法看见的细节写不确定。',images)
    if not isinstance(summary.get('description'),str) or not isinstance(summary.get('accessories'),list):raise UserError('形象分析字段不完整，请重试')
    summary['description']=summary['description'][:3000]
    summary['missingViews']=[x[:40] for x in summary.get('missingViews',[]) if isinstance(x,str)][:4] if isinstance(summary.get('missingViews',[]),list) else []
    summary['accessories']=[x[:80] for x in summary['accessories'][:12] if isinstance(x,str)]
    j['summary']=summary
    j['prompt']='生成这同一个成年人的独立形象参考照片，严格保持本人脸型五官、发型、体态，不美化换脸。原片只提供身份，不沿用原片的半身、坐姿或裁切构图。统一穿纯白圆领T恤、深灰直筒长裤、简洁白色休闲鞋；没有外套，无裸露，正侧背和特写使用相同衣服与发型。中性背景和自然光。只输出单张照片，不要拼图、文字。外观：'+summary['description']+'。常见配饰：'+json.dumps(summary['accessories'],ensure_ascii=False)
   else:
    ref='data:image/jpeg;base64,'+base64.b64encode(asset(j['owner'],j['referenceAsset'])).decode()
    scene=reason('只分析最后一张场景参考的摄影风格，不描述或复制其中人物的脸。返回 JSON：style（详细中文描述场景、自然姿态、构图、光线、色彩、镜头质感）。前面的图片是用户本人，只用于保持身份。',images+[ref])
    if not isinstance(scene.get('style'),str):raise UserError('场景分析字段不完整，请重试')
    j['prompt']='为前几张身份参考中的同一个成年人拍摄一张自然生活感摄影。严格保持用户本人的脸型五官、发型和体态。最后一张仅作场景、光影、构图和姿态参考，绝不能复制最后一张里的人脸。完整日常衣着、无裸露、无内衣泳装。禁止文字、水印、拼图。摄影要求：'+scene['style']+'。用户常见配饰：'+json.dumps(p.get('summary',{}).get('accessories',[]),ensure_ascii=False)
   save_job(j)
  if j['kind'] not in {'profile','face'}:images.append(data_uri(j['owner'],j['referenceAsset']))
  j['stage']='生成形象参考' if j['kind'] in {'profile','face'} else '生成个人照片';j['status']='running';save_job(j)
  # Submit independently and persist every upstream id before doing any further work.
  for i,s in enumerate(j['slots']):
   if s.get('asset') or s.get('providerId') or s.get('status') in {'failed','uncertain'}:continue
   s['status']='submitting';save_job(j)
   try:
    views={'front':'正面站立，脸和身体正对相机。FULL LENGTH HEAD TO TOE, including both shoes. 相机退远，完整头顶到双脚，头顶和鞋底上下各留白至少10%，人物占画面高度不超过80%，绝不能裁成半身或截断腿脚。','side':'严格90度侧面站立，头和身体同向侧对相机，不要四分之三角度。FULL LENGTH HEAD TO TOE, including both shoes. 完整头顶到双脚，头顶和鞋底上下各留白至少10%，人物占画面高度不超过80%，绝不裁切腿脚。','back':'严格180度背面站立，后脑和背部正对相机，不回头。FULL LENGTH HEAD TO TOE, including both shoes. 完整头顶到双脚，头顶和鞋底上下各留白至少10%，人物占画面高度不超过80%。','face':'正脸面部特写，头部正对相机，清晰呈现五官，保留完整发型和下巴，穿同一件白色圆领T恤。'}
    direction=('。视角：'+views[s['key']]+'。缺失角度只能作为 AI 补全参考，不声称是真实记录。') if j['kind'] in {'profile','face'} else ('。这是独立的第%d张作品，保持同一场景风格，使用略有区别的自然动作和取景。'%(i+1))
    prompt,size=portrait_input(j,s) if j['kind'] in {'profile','face'} else (j['prompt'],j['size'])
    s['providerId']=submit_image(prompt+(direction if s['key']!='face' else ''),images,size);s['status']='running';save_job(j)
   except UnknownSubmission as e:s['status']='uncertain';s['error']=str(e);save_job(j)
   except UserError as e:s['status']='failed';s['error']=str(e);save_job(j)
   except Exception:s['status']='uncertain';s['error']='提交连接中断，结果状态未知，未自动重复提交';save_job(j)
  deadline=time.time()+900
  while time.time()<deadline:
   pending=[s for s in j['slots'] if s.get('providerId') and not s.get('asset') and s.get('status') not in {'failed','uncertain'}]
   if not pending:break
   for s in pending:
    try:
     r=api('/v1/api/result?id='+quote(s['providerId']));d=r.get('data') or r.get('result') or r;state=d.get('status',r.get('status',''))
     if state in {'succeeded','completed','success'}:
      s['providerCompleted']=True
      url=generated_url(r)
      if not url:raise UserError('生成任务完成但没有图片，请重试')
      data=remote_image(url)
      if j['kind'] in {'profile','face'} and s['key']=='face':
       try:valid=face_is_closeup(data)
       except Exception:s['status']='failed';s['error']='面部特写取景检查暂不可用，可重试检查';save_job(j);continue
       if not valid:
        s['status']='failed';s['providerFailed']=True;s['error']='这张图不是合格的面部特写，已退回该张积分，请重试';save_job(j);continue
       s['framingChecked']=True
      s['asset']=store_asset(j['owner'],data);s['status']='succeeded';s.pop('error',None)
     elif state in {'failed','error','cancelled','canceled'}:s['status']='failed';s['providerFailed']=True;s['error']='GRsai 生成失败，请重试'
     else:s['progress']=d.get('progress',0)
     save_job(j)
    except UserError as e:s['lastError']=str(e);save_job(j)
    except Exception:s['lastError']='查询进度连接中断，正在重试';save_job(j)
   if any(s.get('status')=='running' for s in j['slots']):time.sleep(5)
  for s in j['slots']:
   if s.get('status')=='running':s['status']='failed';s['error']=s.get('lastError','生成超时，可重试查询已有任务')
  done=sum(bool(s.get('asset')) for s in j['slots']);j['status']='succeeded' if done==len(j['slots']) else 'partial' if done else 'uncertain' if any(s.get('status')=='uncertain' for s in j['slots']) else 'failed'
  if j['kind'] in {'profile','face'} and j.get('summary'):
   p=read_profile(j['owner'])
   if p.get('revision')==j['revision']:
    p['summary']=j['summary'];p['views']={**(p.get('views',{}) if j['kind']=='face' else {}),**{s['key']:s['asset'] for s in j['slots'] if s.get('asset')}};save_profile(j['owner'],p)
 except UserError as e:j['status']='failed';j['error']=str(e)
 except Exception:j['status']='failed';j['error']='任务暂时中断，已保存进度，可稍后重试'
 finally:
  save_job(j)
  with GUARD:ACTIVE.discard(jid)

def launch(jid):
 with GUARD:
  if jid in ACTIVE:return
  ACTIVE.add(jid);WORKERS.submit(execute,jid)

def resume():
 with db() as c:rows=c.execute('SELECT data FROM jobs').fetchall()
 for row in rows:
  j=json.loads(row[0])
  if j['status'] in TERMINAL:continue
  for s in j['slots']:
   if s.get('status')=='submitting' and not s.get('providerId'):s['status']='uncertain';s['error']='服务重启前提交状态未知，未重复提交'
  save_job(j);launch(j['id'])


def create_job(owner,q,catalog):
 key=q.get('requestKey','')
 if not isinstance(key,str) or not 12<=len(key)<=100:raise UserError('请求编号无效，请重新点击')
 with GUARD:
  with db() as c:old=c.execute('SELECT data FROM jobs WHERE owner=? AND request_key=?',(owner,key)).fetchone()
  if old:return json.loads(old[0])
  p=read_profile(owner)
  if not p['photos']:raise UserError('先上传自己的照片，建立形象库')
  history=jobs(owner)
  if sum(j['status'] not in TERMINAL for j in history)>=2:raise UserError('已有两个任务进行中，请完成后再生成')
  with db() as c:daily=c.execute('SELECT COUNT(*) FROM jobs WHERE created>?',(time.time()-86400,)).fetchone()[0]
  if daily>=int(os.getenv('OOTD_GLOBAL_DAILY_JOBS','100')):raise UserError('今日生图服务额度已用完，请稍后再试')
  if not os.getenv('GRSAI_API_KEY'):raise UserError('生图服务尚未配置')
  kind=q.get('kind')
  if kind not in {'profile','face','same','random'}:raise UserError('任务类型无效')
  required=4 if kind=='profile' else 1 if kind=='face' else 2
  if credit_balance(owner)['remaining']<required:raise UserError('积分不足：本次需要 %d 积分，今日剩余 %d 积分'%(required,credit_balance(owner)['remaining']))
  ref=None
  if kind not in {'profile','face'}:
   if not p.get('summary') or len(p.get('views',{}))<4:raise UserError('请先完成形象库整理，再生成个人照片')
   candidates=q.get('referenceIds',[]) if kind=='random' else [q.get('referenceId')]
   if not isinstance(candidates,list) or len(candidates)>500:raise UserError('参考图片无效')
   candidate_ids={x for x in candidates if isinstance(x,str)};available=[r for r in catalog if r['id'] in candidate_ids]
   if not available:raise UserError('当前照片参考已过期，请刷新后重试')
   ref=secrets.choice(available)
  jid=secrets.token_hex(16);j={'id':jid,'owner':owner,'requestKey':key,'kind':kind,'revision':p.get('revision'),'photos':p['photos'][:], 'status':'queued','stage':'排队中','created':time.time(),'slots':[],'size':'864x1152'}
  if kind=='profile':
   j['size']='1024x1536'
   j['slots']=[{'key':key,'label':label,'status':'queued'} for key,label in [('front','正面全身'),('side','侧面全身'),('back','背面全身'),('face','面部特写')]]
  elif kind=='face':
   j['size']='1024x1024';j['slots']=[{'key':'face','label':'面部特写','status':'queued'}]
  else:
   j['photos']=(p['photos'][:4]+[p['views']['face'],p['views']['front']])[:6]
   j['referenceAsset']=store_asset(owner,remote_image(ref['image']));j['reference']={'id':ref['id'],'title':ref['title'],'asset':j['referenceAsset']}
   if ref.get('width',0)>ref.get('height',1):j['size']='1152x864'
   j['slots']=[{'key':str(i),'label':'照片 '+str(i),'status':'queued'} for i in (1,2)]
  with db() as c:
   c.execute('BEGIN IMMEDIATE');reserve_credits(c,j,j['slots'])
   c.execute('INSERT INTO jobs VALUES(?,?,?,?,?)',(jid,owner,key,json.dumps(j,ensure_ascii=False),j['created']))
  launch(jid);return j

def public_job(j):return {k:v for k,v in j.items() if k not in {'owner','photos','prompt','revision','referenceAsset','requestKey'}}

def handle(h,catalog):
 path=urlparse(h.path).path
 if not path.startswith('/api/personal'):return False
 cookie=SimpleCookie()
 try:cookie.load(h.headers.get('Cookie',''))
 except Exception:pass
 token=cookie['ootd_personal'].value if 'ootd_personal' in cookie else ''
 new=not (len(token)==64 and all(c in '0123456789abcdef' for c in token))
 if new:token=secrets.token_hex(32)
 legacy_owner=hashlib.sha256(token.encode()).hexdigest()
 login=email_auth.session(token);owner=login['owner'] if login else legacy_owner
 ip=h.headers.get('X-Real-IP',h.client_address[0]) if h.client_address[0] in {'127.0.0.1','::1'} else h.client_address[0]
 expire_cookie=False
 def send(code,data=None,raw=None):
  body=raw if raw is not None else json.dumps(data,ensure_ascii=False).encode();h.send_response(code)
  h.send_header('Content-Type','image/jpeg' if raw is not None else 'application/json; charset=utf-8');h.send_header('Cache-Control','private, no-store');h.send_header('X-Content-Type-Options','nosniff');h.send_header('Content-Length',str(len(body)))
  if new:h.send_header('Set-Cookie','ootd_personal='+token+'; HttpOnly; SameSite=Lax; Path=/api/personal; Max-Age='+('0' if expire_cookie else '2592000')+('' if h.headers.get('Host','').startswith(('localhost','127.0.0.1')) else '; Secure'))
  h.end_headers();h.wfile.write(body)
 try:
  if h.command=='GET':
   if path=='/api/personal':send(200,{'credits':credit_balance(owner) if login else None,'authenticated':bool(login),'user':{'email':login['email']} if login else None,'loginConfigured':email_auth.configured(),'profile':read_profile(owner) if login else {'photos':[],'views':{},'summary':None},'jobs':[public_job(j) for j in jobs(owner)] if login else [],'configured':bool(os.getenv('GRSAI_API_KEY')),'imageModel':IMAGE_MODEL,'reasonModel':REASON_MODEL})
   elif path.startswith('/api/personal/assets/'):
    if not login:raise email_auth.AuthError('请先登录',401)
    send(200,raw=asset(owner,path))
   else:send(404,{'error':'未找到'})
   return True
  origin=h.headers.get('Origin')
  if origin and urlparse(origin).netloc!=h.headers.get('Host'):send(403,{'error':'请求来源无效'});return True
  if h.headers.get('Content-Type','').split(';')[0]!='application/json':raise UserError('请求格式无效')
  is_auth=path in {'/api/personal/auth/send','/api/personal/auth/verify','/api/personal/auth/logout'}
  if not is_auth and not login:raise email_auth.AuthError('请先登录后再使用个人形象与生图功能',401)
  length=int(h.headers.get('Content-Length','0'))
  if not 0<length<=(8192 if is_auth else 24_000_000):raise UserError('上传内容过大，最多上传 12 张照片')
  q=json.loads(h.rfile.read(length))
  if not isinstance(q,dict):raise UserError('请求格式无效')
  if path=='/api/personal/auth/send':send(200,email_auth.send_code(q.get('email'),ip))
  elif path=='/api/personal/auth/verify':
   token,user=email_auth.verify(q.get('email'),q.get('code'),legacy_owner,ip);new=True;send(200,{'authenticated':True,'user':user})
  elif path=='/api/personal/auth/logout':
   email_auth.logout(token);token='';new=True;expire_cookie=True;send(200,{'ok':True})
  elif path=='/api/personal/upload':
   uploads=q.get('photos',[]);p=read_profile(owner)
   if not isinstance(uploads,list) or not uploads or len(uploads)+len(p['photos'])>12:raise UserError('形象库最多保留 12 张原始照片')
   decoded=[]
   for u in uploads:
    if not isinstance(u,str) or not u.startswith(('data:image/jpeg;base64,','data:image/png;base64,','data:image/webp;base64,')):raise UserError('请选择 JPG、PNG 或 WebP 照片')
    try:decoded.append(clean_image(base64.b64decode(u.split(',',1)[1],validate=True)))
    except ValueError:raise UserError('图片编码无效')
   p['photos'] += [store_asset(owner,d) for d in decoded];p['views']={};p['summary']=None;p['revision']=secrets.token_hex(8);save_profile(owner,p);send(200,{'profile':p})
  elif path=='/api/personal/generate':send(202,{'job':public_job(create_job(owner,q,catalog()))})
  elif path=='/api/personal/retry':
   with GUARD:
    j=load_job(q.get('id',''))
    if not j or j['owner']!=owner:raise UserError('任务不存在')
    if j['status'] not in TERMINAL:raise UserError('任务仍在进行中')
    if j.get('retries',0)>=3:raise UserError('已重试三次，请稍后新建任务')
    if any(x['status'] not in TERMINAL for x in jobs(owner)):raise UserError('请等待当前任务完成后重试')
    j['retries']=j.get('retries',0)+1
    if j['revision']!=read_profile(owner).get('revision'):raise UserError('形象照片已更新，请新建任务')
    if any(s.get('status')=='uncertain' for s in j['slots']):raise UserError('提交状态未知，不能安全地自动重试，请稍后查看历史')
    with db() as c:
     c.execute('BEGIN IMMEDIATE');reserve_credits(c,j,j['slots'])
     # Save reservations and retry state atomically, including cross-day retries.
     for s in j['slots']:
      if not s.get('asset'):
       if s.pop('providerFailed',False):s.pop('providerId',None)
       s['status']='running' if s.get('providerId') else 'queued';s.pop('error',None)
     j['status']='queued';j.pop('error',None);j['updated']=time.time()
     c.execute('UPDATE jobs SET data=? WHERE id=?',(json.dumps(j,ensure_ascii=False),j['id']))
    launch(j['id']);send(202,{'job':public_job(j)})
  elif path=='/api/personal/delete':
   if any(j['status'] not in TERMINAL for j in jobs(owner)):raise UserError('请等待正在进行的任务结束后再删除')
   with db() as c:
    paths=c.execute('SELECT path FROM assets WHERE owner=?',(owner,)).fetchall()
    c.execute('DELETE FROM assets WHERE owner=?',(owner,));c.execute('DELETE FROM profiles WHERE owner=?',(owner,));c.execute('DELETE FROM jobs WHERE owner=?',(owner,))
   for r in paths:Path(r[0]).unlink(missing_ok=True)
   send(200,{'ok':True})
  else:send(404,{'error':'未找到'})
 except email_auth.AuthError as e:send(e.status,{'error':str(e)})
 except UserError as e:send(400,{'error':str(e)})
 except (ValueError,TypeError):send(400,{'error':'请求格式无效'})
 except (BrokenPipeError,ConnectionResetError):pass
 except Exception:send(500,{'error':'服务暂时不可用，请稍后重试'})
 return True
