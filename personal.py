"""Private appearance libraries and durable GRsai photography jobs."""
from contextlib import contextmanager
from datetime import datetime,timedelta,timezone
import base64, concurrent.futures, hashlib, io, json, os, secrets, sqlite3, threading, time, zipfile
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
REVIEW_WORKERS=concurrent.futures.ThreadPoolExecutor(max_workers=2)
REVIEWING=set()
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
 with db() as c:rows=c.execute('SELECT data FROM jobs WHERE owner=? ORDER BY created DESC',(owner,)).fetchall()
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
 nested=result.get('data') or result.get('result') or result
 state=str(nested.get('status',result.get('status',''))).lower() if isinstance(nested,dict) else ''
 if result.get('error') and not (path.startswith('/v1/api/result') and state in {'failed','error','cancelled','canceled'}):raise UserError('GRsai 未完成请求，请稍后重试')
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

NATURAL_CAPTURE='保持真实正面原照的眼睛大小与间距、眉形、鼻梁鼻翼、唇形、脸宽、下颌轮廓和年龄感，不重新设计长相。只调整照片成像方式：像普通相机在现场拍出的自然照片，沿用参考场景的机位、构图、明暗关系、衣着与姿态。保留本人自然肤色及皮肤微小明暗过渡，柔和收敛高光和锐化，不拉高皮肤局部对比，不做美颜磨皮。保持面部细节适度清晰，避免每一处边缘都同样锐利；衣物和背景仍有真实细节。降低HDR和人像精修感，但不添加可见颗粒、模糊、噪点或任何五官改动。'

IDENTITY_VIEW_ORDER=('front','side','back','face')
SCHEME_METHOD='scheme-four-v1'

def scheme_prompt(j,style):
 return ('使用当前选定个人形象方案中的同一个成年人生成独立自然生活摄影。第1张为正面全身，第2张为侧面全身，第3张为背面全身，第4张为面部特写，第5张且最后一张为风格参考。前四张共同约束人物长相、发型、体态、眼镜与耳饰；面部细节、眼型眼距、鼻形、唇形、脸宽和下颌轮廓以第4张面部特写为主，身体比例与各角度外观参考第1至3张。不美化换脸、不削瘦面颊、不放大眼睛、不变年轻。必须保留形象方案中的眼镜，不能因为风格人物没有眼镜而摘掉、换成墨镜或遮住；耳饰和其他配饰遵守方案配饰清单。最后一张只提供场景、光线、构图、动作和衣服裤子，不提供长相、发型、眼镜或首饰，绝不能复制最后一张里的人脸。不参考上传原照或其他方案。完整日常衣着，无裸露、内衣泳装；禁止文字、水印、拼图。风格要求：'+style+'。选定方案外观描述：'+j.get('identitySummary',{}).get('description','')+accessory_prompt(j,j.get('accessories',[]))+NATURAL_CAPTURE.replace('真实正面原照','选定方案面部特写'))

def accessory_rules(j,items):
 policy=j.get('accessoryPolicy') or {}
 excluded=[x for x in policy.get('excluded',[]) if isinstance(x,str)][:12]
 result=[x[:300] for x in items if isinstance(x,str) and not any(no in x for no in excluded)][:12]
 for item in policy.get('required',[]):
  if isinstance(item,str) and not any(item in x for x in result) and not any(no in item for no in excluded):result.append(item+'（严格参照上传的实物照片）')
 return result

def accessory_prompt(j,items):
 items=accessory_rules(j,items)
 text='。配饰必须严格使用以下清单和上传的实物参考：'+json.dumps(items,ensure_ascii=False)+'。仅当清单包含对应配饰时：项链按实物保持链条颜色、吊坠形状与长度，戴在颈部；手串按实物保持珠子颜色、排列与材质，戴在手腕，不得替换成手表。身体和取景允许时清楚呈现，不要省略；面部特写不可为展示手串而拉远镜头。不得复制场景人物或旧形象参考中的额外饰品，不得凭空添加清单外的配饰。'
 for item in set((j.get('accessoryPolicy') or {}).get('excluded',[]))|{x for x in ('手表','戒指') if not any(x in a for a in items)}:text+='禁止佩戴'+item+'。'
 return text

def accessories_match(data,j):
 policy=j.get('accessoryPolicy') or {}
 required=j.get('accessories',[]) if j.get('identityMethod')==SCHEME_METHOD else policy.get('required',[])
 result=reason('检查生成图是否遵守配饰要求。要求佩戴：'+json.dumps(required,ensure_ascii=False)+'；绝对禁止：'+json.dumps(policy.get('excluded',[]),ensure_ascii=False)+'。返回 JSON：matches（布尔值），missingVisibleAccessories（数组，仅身体相应区域清楚可见却缺失的配饰；眼部可见且要求眼镜时必须佩戴指定眼镜，不得用墨镜替代；颈部可见应有指定项链，手腕可见应有指定手串；出画或遮挡不算缺失），forbiddenDetected（图中出现的禁止配饰数组）。手串不能误认成手表，不能因为背景风格而放宽要求。', ['data:image/jpeg;base64,'+base64.b64encode(data).decode()])
 return result.get('matches') is True and result.get('missingVisibleAccessories')==[] and result.get('forbiddenDetected')==[]

def portrait_input(j,slot):
 if slot['key']=='face':
  summary=j.get('summary',{})
  return ('为身份参考中同一位成年人拍摄独立面部特写。严格保持本人的脸型五官、发型、年龄感与皮肤特征，不美化换脸。原片只提供人物身份，不沿用原片的身体姿势、远近或全身构图。自然柔和光线，不要文字、水印或拼图。'+FACE_FRAMING+'。本人面部特征参考：'+summary.get('description','')+'。实际穿戴配饰：'+json.dumps(summary.get('accessories',[]),ensure_ascii=False)+accessory_prompt(j,summary.get('accessories',[])),'1024x1024')
 return j['prompt'],j['size']

def face_is_closeup(data):
 result=reason('只检查取景是否是面部特写，不判断身份或好看与否。返回严格 JSON：isCloseUp（布尔值，仅完整头部和少量肩颈为true；半身或全身为false），faceHeightRatio（头顶至下巴占整幅高度的比例0到1），faceWidthRatio（脸宽占整幅宽度的比例0到1）。若看见胸腹、腰、腿或鞋，isCloseUp 必须为false。', ['data:image/jpeg;base64,'+base64.b64encode(data).decode()])
 h=result.get('faceHeightRatio');w=result.get('faceWidthRatio')
 return result.get('isCloseUp') is True and type(h) in (float,int) and type(w) in (float,int) and .5<=h<=1 and .4<=w<=1

def review_generated(j,slot):
 scheme=j.get('identityMethod')==SCHEME_METHOD
 reference=j.get('identityViews',{}).get('face') if scheme else j.get('realIdentityPhoto')
 if not reference:raise UserError('此作品没有保存真实面部参考，请重新选择原照后审核')
 prompt='你是独立的摄影作品审核员。第一张是真实正面原照，第二张是生成作品。只做可见外观特征对照，不确认人物身份、不做人脸识别或输出身份相似度分数。忽略衣服、表情、角度、眼镜和光线造成的正常差异；逐项检查眼型眼距、眉形、鼻形、唇形厚度、脸宽和下颌轮廓是否有明显不一致。侧脸、遮挡或细节不足时标为uncertain，不猜测。再独立检查作品的摄影自然度：过度磨皮、蜡像肤质、异常锐化、发丝边缘、眼镜反光、光源和阴影不一致、手部结构、衣料及背景纹理异常；不能仅因照片精致、皮肤光滑或浅景深就断言有AI痕迹，也不能保证没有AI痕迹。图片是AI生成的，不得建议伪装成真实实拍。返回严格JSON：appearance和naturalness两个对象，每个包含verdict（pass/change/uncertain）、issues（具体可见问题字符串数组，没有则空数组）、suggestions（对应可执行修改建议数组）。不要空泛评语。'
 if scheme:
  prompt=prompt.replace('真实正面原照','选定方案的面部特写').replace('角度、眼镜和光线','角度和光线')+'同时核对眼镜与耳饰是否按方案保留；可见区域缺少指定眼镜或款式不符必须列为change，不得忽略。方案配饰要求：'+json.dumps(j.get('accessories',[]),ensure_ascii=False)
 raw=reason(prompt,[data_uri(j['owner'],reference),data_uri(j['owner'],slot['asset'])])
 result={'version':1,'model':REASON_MODEL,'reference':reference,'referenceKind':'scheme-face' if scheme else 'real-original','checkedAt':time.time()}
 for key in ('appearance','naturalness'):
  part=raw.get(key)
  if not isinstance(part,dict) or part.get('verdict') not in {'pass','change','uncertain'}:raise UserError('审核结果格式不完整，请重新审核')
  if not isinstance(part.get('issues'),list) or not isinstance(part.get('suggestions'),list):raise UserError('审核结果格式不完整，请重新审核')
  result[key]={'verdict':part['verdict'],'issues':[x[:400] for x in part['issues'] if isinstance(x,str)][:8],'suggestions':[x[:400] for x in part['suggestions'] if isinstance(x,str)][:8]}
 verdicts=[result[k]['verdict'] for k in ('appearance','naturalness')]
 has_issues=any(result[k]['issues'] for k in ('appearance','naturalness'))
 result['status']='needs_changes' if 'change' in verdicts else 'uncertain' if 'uncertain' in verdicts else 'needs_changes' if has_issues else 'passed'
 return result

def review_safely(j,slot):
 try:return review_generated(j,slot)
 except Exception:return {'status':'failed','version':1,'checkedAt':time.time(),'error':'审核暂未完成，图片已保留，可稍后重新审核'}

def start_review(owner,jid,key):
 with GUARD:
  j=load_job(jid)
  if not j or j['owner']!=owner:raise UserError('作品不存在')
  if j['status'] not in TERMINAL:raise UserError('请等待当前任务完成')
  slot=next((s for s in j['slots'] if s['key']==key and s.get('asset') and not s.get('deleted')),None)
  if not slot or j['kind'] not in {'same','random'}:raise UserError('请选择已生成的个人作品')
  if (jid,key) in REVIEWING:return j
  if j.get('identityMethod')!=SCHEME_METHOD and not j.get('realIdentityPhoto'):
   profile=read_profile(owner);photo=profile.get('identityPhoto') or next(iter(profile.get('photos',[])),None)
   if not photo:raise UserError('请先上传并选择真实正面原照')
   j['realIdentityPhoto']=photo
  slot['review']={'status':'checking','started':time.time()};save_job(j);REVIEWING.add((jid,key))
 def work():
  result=review_safely(j,slot)
  with GUARD:
   latest=load_job(jid)
   if latest and latest['owner']==owner:
    target=next((s for s in latest['slots'] if s['key']==key and s.get('asset')==slot['asset']),None)
    if target:target['review']=result;save_job(latest)
   REVIEWING.discard((jid,key))
 REVIEW_WORKERS.submit(work);return j

def publishing_package(owner,q):
 j=load_job(q.get('id',''))
 if not j or j['owner']!=owner:raise UserError('作品不存在')
 slot=next((s for s in j['slots'] if s['key']==q.get('slot') and s.get('asset') and not s.get('deleted')),None)
 if not slot or (slot.get('review') or {}).get('status') not in {'passed','needs_changes','uncertain'}:raise UserError('请先完成作品审核，再人工确认是否准备发布')
 if q.get('confirmed') is not True:raise UserError('请先确认已核对图片与文案')
 title=q.get('title');caption=q.get('caption');platform=q.get('platform')
 if not isinstance(title,str) or not title.strip() or len(title)>80:raise UserError('请输入80字以内标题')
 if not isinstance(caption,str) or len(caption)>2000:raise UserError('正文最多2000字')
 if platform not in {'xiaohongshu','douyin'}:raise UserError('请选择发布平台')
 caption=caption.strip()
 if 'AI生成图片' not in caption.splitlines():caption+='\n\nAI生成图片'
 data=io.BytesIO()
 with zipfile.ZipFile(data,'w',compression=zipfile.ZIP_DEFLATED) as z:
  z.writestr('photo.jpg',asset(owner,slot['asset']))
  z.writestr('caption.txt',title.strip()+'\n\n'+caption)
  review=slot['review'];z.writestr('review.json',json.dumps({**{k:v for k,v in review.items() if k not in {'reference'}},'humanConfirmedForPreparation':True},ensure_ascii=False,indent=2))
  z.writestr('发布说明.txt','这是发布准备包，尚未向平台上传或发布。\n解压后上传photo.jpg，填写caption.txt中的标题与正文。发布前请人工确认图片、内容及平台的AI生成标识。\nAI审核仅提供外观与摄影自然度建议，不证明身份或保证没有生成痕迹。')
 return data.getvalue()

def execute(jid):
 j=load_job(jid)
 try:
  j.setdefault('started',time.time());save_job(j)
  p=read_profile(j['owner']);images=[data_uri(j['owner'],u) for u in j['photos'][:12]]
  if not j.get('prompt'):
   j['stage']='分析形象' if j['kind'] in {'profile','face','view'} else '分析参考照片';save_job(j)
   if j['kind'] in {'profile','face','view'}:
    summary=reason('分析这些同一位成年人的照片，只写可见外观，不猜姓名、国籍、健康。返回 JSON：description（脸型、五官、发型、体态的具体中文描述），accessories（用户实际上传的配饰详细描述数组：包括人物佩戴的，以及单独拍摄的项链吊坠、手串等实物照片；逐项描述颜色、材质、形状、佩戴位置。单独拍的配饰也视作用户明确要求佩戴，不要忽略。不得臆造没有实物证据的手表、戒指。不包括杯子、手机、家具或背景道具；没有则返回空数组），accessoryImageIndices（只拍配饰实物、没有人脸的参考图的从0开始索引数组；有人脸的照片不放入该数组），missingViews（未见的正面、侧面、背面视角数组）。无法看见的细节写不确定。',images)
    if not isinstance(summary.get('description'),str) or not isinstance(summary.get('accessories'),list):raise UserError('形象分析字段不完整，请重试')
    summary['description']=summary['description'][:3000]
    summary['missingViews']=[x[:40] for x in summary.get('missingViews',[]) if isinstance(x,str)][:4] if isinstance(summary.get('missingViews',[]),list) else []
    summary['accessories']=accessory_rules(j,summary['accessories'])
    j['summary']=summary
    j['prompt']='生成这同一个成年人的独立形象参考照片，严格保持本人脸型五官、发型、体态，不美化换脸。原片只提供身份，不沿用原片的半身、坐姿或裁切构图。统一穿纯白圆领T恤、深灰直筒长裤、简洁白色休闲鞋；没有外套，无裸露，正侧背和特写使用相同衣服与发型。中性背景和自然光。只输出单张照片，不要拼图、文字。外观：'+summary['description']+'。常见配饰：'+json.dumps(summary['accessories'],ensure_ascii=False)+accessory_prompt(j,summary['accessories'])
   elif j.get('identityMethod')==SCHEME_METHOD:
    ref=data_uri(j['owner'],j['referenceAsset'])
    scene=reason('只分析最后一张风格图的场景、光线、构图、动作与衣服裤子，不描述人物五官、发型、眼镜和首饰。返回 JSON：style（具体中文描述）。', [ref])
    if not isinstance(scene.get('style'),str):raise UserError('风格分析字段不完整，请重试')
    j['prompt']=scheme_prompt(j,scene['style'])
   else:
    if j.get('accessorySourcePhotos') and 'accessoryRefs' not in j:
     sources=j['accessorySourcePhotos'][:12]
     details=reason('仅检查上传原片中的配饰，不重新分析人物身份。返回 JSON：accessories（已佩戴和单独拍摄的项链吊坠、手串等实物详细描述数组，含颜色、形状、材质；没有证据的手表戒指不得添加），accessoryImageIndices（从0开始，只选择没有人脸的配饰实物照片索引；含人脸照片不可选）。单独拍摄的配饰也需识别，但必须遵守用户禁戴清单；accessories和accessoryImageIndices都不得包含禁戴物品，仅选择允许佩戴的配饰实物参考；若照片包含禁戴饰品，不选择该照片。用户禁戴清单：'+json.dumps((j.get('accessoryPolicy') or {}).get('excluded',[]),ensure_ascii=False), [data_uri(j['owner'],u) for u in sources])
     indices=details.get('accessoryImageIndices',[])
     j['accessoryRefs']=[sources[i] for i in indices if type(i) is int and 0<=i<len(sources)][:6] if isinstance(indices,list) else []
     items=details.get('accessories')
     j['accessories']=accessory_rules(j,items if isinstance(items,list) else j.get('identitySummary',{}).get('accessories',[]));save_job(j)
    ref='data:image/jpeg;base64,'+base64.b64encode(asset(j['owner'],j['referenceAsset'])).decode()
    scene=reason('只分析最后一张场景参考的摄影风格，不描述或复制其中人物的脸。返回 JSON：style（详细中文描述场景、衣着、自然姿态、构图、光线、色彩、镜头质感）。前面的图片是用户本人，只用于保持身份。',images+[ref])
    if not isinstance(scene.get('style'),str):raise UserError('场景分析字段不完整，请重试')
    j['prompt']='为前几张身份参考中的同一个成年人拍摄一张自然生活感摄影。第一张是用户真实正面原照，是面部身份的最高优先级依据：严格保持其眼型和自然眼裂大小、眼距、眉形眉毛浓度、鼻形、唇形厚度与宽度、面颊饱满程度、脸宽、下巴形状和五官比例。不放大或画圆眼睛，不加粗眉毛或嘴唇，不拉长下半脸、不削瘦面颊或收尖下巴、不变年轻、不美化换脸。第二张是用户选定方案的外观辅助图，仅参考发型、眼镜和体态；衣着遵循最后一张场景参考，绝不能覆盖第一张的眼睛、鼻子、嘴唇和脸型；两张冲突时真实正面原照优先。人物朝向、机位与动作遵循最后一张场景参考，不固定为正面或低机位。最后一张仅作场景、光影、构图和姿态参考，绝不能复制最后一张里的人脸。完整日常衣着、无裸露、无内衣泳装。禁止文字、水印、拼图。摄影要求：'+scene['style']+'。用户常见配饰：'+json.dumps(j.get('accessories',j.get('identitySummary',p.get('summary') or {}).get('accessories',[])),ensure_ascii=False)+accessory_prompt(j,j.get('accessories',j.get('identitySummary',p.get('summary') or {}).get('accessories',[])))+'第3张至场景参考之前的附加图片仅作配饰实物参考，不改变真实正面原照中的身份。'+NATURAL_CAPTURE
   if j['kind'] in {'same','random'} and j.get('identityMethod') not in {'real-front-v1',SCHEME_METHOD}:
    j['prompt']='根据已保存的人物参考保持同一人的五官长相；最后一张只作场景参考。'+scene['style']+accessory_prompt(j,j.get('accessories',[]))+NATURAL_CAPTURE.replace('真实正面原照','已保存人物参考')
   save_job(j)
  if j['kind'] not in {'profile','face','view'}:
   images.extend(data_uri(j['owner'],u) for u in j.get('accessoryRefs',[]));images.append(data_uri(j['owner'],j['referenceAsset']))
  j['stage']='生成形象参考' if j['kind'] in {'profile','face','view'} else '生成个人照片';j['status']='running';save_job(j)
  # Submit independently and persist every upstream id before doing any further work.
  for i,s in enumerate(j['slots']):
   if s.get('asset') or s.get('providerId') or s.get('status') in {'failed','uncertain'}:continue
   s['status']='submitting';save_job(j)
   try:
    views={'front':'正面站立，脸和身体正对相机。FULL LENGTH HEAD TO TOE, including both shoes. 相机退远，完整头顶到双脚，头顶和鞋底上下各留白至少10%，人物占画面高度不超过80%，绝不能裁成半身或截断腿脚。','side':'严格90度侧面站立，头和身体同向侧对相机，不要四分之三角度。FULL LENGTH HEAD TO TOE, including both shoes. 完整头顶到双脚，头顶和鞋底上下各留白至少10%，人物占画面高度不超过80%，绝不裁切腿脚。','back':'严格180度背面站立，后脑和背部正对相机，不回头。FULL LENGTH HEAD TO TOE, including both shoes. 完整头顶到双脚，头顶和鞋底上下各留白至少10%，人物占画面高度不超过80%。','face':'正脸面部特写，头部正对相机，清晰呈现五官，保留完整发型和下巴，穿同一件白色圆领T恤。'}
    direction=('。视角：'+views[s['key']]+'。缺失角度只能作为 AI 补全参考，不声称是真实记录。') if j['kind'] in {'profile','face','view'} else ('。这是独立的第%d张作品，保持同一场景风格，使用略有区别的自然动作和取景。'%(i+1))
    prompt,size=portrait_input(j,s) if j['kind'] in {'profile','face','view'} else (j['prompt'],j['size'])
    s['providerId']=submit_image(prompt+(direction if s['key']!='face' else ''),images,size);s['status']='running';save_job(j)
   except UnknownSubmission as e:s['status']='uncertain';s['error']=str(e);save_job(j)
   except UserError as e:s['status']='failed';s['error']=str(e);save_job(j)
   except Exception:s['status']='uncertain';s['error']='提交连接中断，结果状态未知，未自动重复提交';save_job(j)
  deadline=j.setdefault('pollDeadline',j['started']+900);save_job(j)
  while True:
   pending=[s for s in j['slots'] if s.get('providerId') and not s.get('asset') and s.get('status') not in {'failed','uncertain'}]
   if not pending:break
   for s in pending:
    try:
     r=api('/v1/api/result?id='+quote(s['providerId']));d=r.get('data') or r.get('result') or r;state=str(d.get('status',r.get('status',''))).lower()
     if state in {'succeeded','completed','success'}:
      s['providerCompleted']=True
      url=generated_url(r)
      if not url:raise UserError('生成任务完成但没有图片，请重试')
      data=remote_image(url)
      if j['kind'] in {'profile','face','view'} and s['key']=='face':
       s['phase']='checking_face';save_job(j)
       try:valid=face_is_closeup(data)
       except Exception:s['status']='failed';s['error']='面部特写取景检查暂不可用，可重试检查';save_job(j);continue
       if not valid:
        s['status']='failed';s['providerFailed']=True;s['error']='这张图不是合格的面部特写，已退回该张积分，请重试';save_job(j);continue
       s['framingChecked']=True
      if j.get('accessoryPolicy') or j.get('identityMethod')==SCHEME_METHOD:
       s['phase']='checking_accessories';save_job(j)
       try:valid=accessories_match(data,j)
       except Exception:s['status']='failed';s['providerFailed']=True;s['error']='配饰检查暂不可用，已退回该张积分';save_job(j);continue
       if not valid:
        s['status']='failed';s['providerFailed']=True;s['error']='配饰与要求不符，已退回该张积分；原有图片保留，可重新生成';save_job(j);continue
       s['accessoriesChecked']=True
      s['asset']=store_asset(j['owner'],data);s['phase']='done';s['status']='succeeded';s.pop('error',None)
     elif state in {'failed','error','cancelled','canceled'}:s['status']='failed';s['providerFailed']=True;s['error']='GRsai 生成失败，请重试'
     else:s['progress']=d.get('progress',0)
     save_job(j)
    except UserError as e:s['lastError']=str(e);save_job(j)
    except Exception:s['lastError']='查询进度连接中断，正在重试';save_job(j)
   if time.time()>=deadline:break
   if any(s.get('status')=='running' for s in j['slots']):time.sleep(5)
  for s in j['slots']:
   if s.get('status')=='running':s['status']='failed';s['error']=s.get('lastError','等待上游超时；已保留成图，重试只处理未完成图片')
  if j['kind'] in {'same','random'} and j.get('reviewVersion')==1:
   for slot in j['slots']:
    if slot.get('asset') and (slot.get('review') or {}).get('status') not in {'passed','needs_changes','uncertain','failed'}:
     j['stage']='审核作品';slot['review']={'status':'checking','started':time.time()};save_job(j)
     slot['review']=review_safely(j,slot);save_job(j)
  done=sum(bool(s.get('asset')) for s in j['slots']);j['status']='succeeded' if done==len(j['slots']) else 'partial' if done else 'uncertain' if any(s.get('status')=='uncertain' for s in j['slots']) else 'failed'
  if j['kind'] in {'profile','face','view'} and j.get('summary'):
   with GUARD:
    p=read_profile(j['owner'])
    generated={s['key']:s['asset'] for s in j['slots'] if s.get('asset')}
    if generated:
     j['schemeViews']={**(j.get('baseViews',{}) if j['kind']=='view' else p.get('views',{}) if j['kind']=='face' else {}),**generated}
     if p.get('revision')==j['revision'] and (j['kind']!='view' or p.get('selectedScheme')==j.get('baseScheme')):
      p['summary']=j['summary'];p['views']=j['schemeViews'];p['selectedScheme']=j['id'];save_profile(j['owner'],p)
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
  if j['status'] in TERMINAL:
   for slot in j['slots']:
    if (slot.get('review') or {}).get('status')=='checking':slot['review']={'status':'failed','error':'服务已重启，请重新审核'}
   save_job(j);continue
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
  if not p['photos'] and q.get('kind') in {'profile','view'}:raise UserError('先上传自己的照片，建立形象库')
  history=jobs(owner)
  with db() as c:daily=c.execute('SELECT COUNT(*) FROM jobs WHERE created>?',(time.time()-86400,)).fetchone()[0]
  if daily>=int(os.getenv('OOTD_GLOBAL_DAILY_JOBS','100')):raise UserError('今日生图服务额度已用完，请稍后再试')
  if not os.getenv('GRSAI_API_KEY'):raise UserError('生图服务尚未配置')
  kind=q.get('kind')
  if kind not in {'profile','view','same','random'}:raise UserError('任务类型无效')
  if kind in {'profile','view'} and any(j['status'] not in TERMINAL and j['kind'] in {'profile','face','view'} for j in history):raise UserError('请等待当前形象生成完成')
  required=4 if kind=='profile' else 1 if kind=='view' else 2
  if kind=='view' and q.get('view') not in {'front','side','back','face'}:raise UserError('视图无效')
  if credit_balance(owner)['remaining']<required:raise UserError('积分不足：本次需要 %d 积分，今日剩余 %d 积分'%(required,credit_balance(owner)['remaining']))
  ref=None
  if kind not in {'profile','face','view'}:
   if not p.get('summary') or len(p.get('views',{}))<4:raise UserError('请先完成形象库整理，再生成个人照片')
   if 'schemeId' in q and q['schemeId']!=p.get('selectedScheme'):raise UserError('形象方案已变更，请确认所选方案后重新生成')
   candidates=q.get('referenceIds',[]) if kind=='random' else [q.get('referenceId')]
   if not isinstance(candidates,list) or len(candidates)>500:raise UserError('参考图片无效')
   candidate_ids={x for x in candidates if isinstance(x,str)};available=[r for r in catalog if r['id'] in candidate_ids]
   if not available:raise UserError('当前照片参考已过期，请刷新后重试')
   ref=secrets.choice(available)
  jid=secrets.token_hex(16);j={'id':jid,'owner':owner,'requestKey':key,'kind':kind,'revision':p.get('revision'),'photos':p['photos'][:],'accessoryPolicy':p.get('accessoryPolicy',{}), 'status':'queued','stage':'排队中','created':time.time(),'slots':[],'size':'864x1152'}
  if kind=='profile':
   j['size']='1024x1536'
   j['slots']=[{'key':key,'label':label,'status':'queued'} for key,label in [('front','正面全身'),('side','侧面全身'),('back','背面全身'),('face','面部特写')]]
  elif kind=='view':
   if not p.get('summary'):raise UserError('请先整理形象库')
   j['size']='1024x1536';j['baseViews']=dict(p.get('views',{}));j['baseScheme']=p.get('selectedScheme');j['summary']=p['summary']
   names={'front':'正面全身','side':'侧面全身','back':'背面全身','face':'面部特写'}
   j['slots']=[{'key':q['view'],'label':names[q['view']],'status':'queued'}]
  else:
   if any(not isinstance(p['views'].get(k),str) or not p['views'][k] for k in IDENTITY_VIEW_ORDER):raise UserError('请先完成正面、侧面、背面和面部特写四张形象参考')
   j['identityViews']={k:p['views'][k] for k in IDENTITY_VIEW_ORDER}
   j['identityScheme']=p.get('selectedScheme');j['identitySummary']=p.get('summary') or {}
   j['identityMethod']=SCHEME_METHOD;j['reviewVersion']=1
   j['accessories']=accessory_rules(j,j['identitySummary'].get('accessories',[]))
   j['photos']=[j['identityViews'][k] for k in IDENTITY_VIEW_ORDER]
   j['referenceAsset']=store_asset(owner,remote_image(ref['image']));j['reference']={'id':ref['id'],'title':ref['title'],'asset':j['referenceAsset']}
   if ref.get('width',0)>ref.get('height',1):j['size']='1152x864'
   j['slots']=[{'key':str(i),'label':'照片 '+str(i),'status':'queued'} for i in (1,2)]
  with db() as c:
   c.execute('BEGIN IMMEDIATE');reserve_credits(c,j,j['slots'])
   c.execute('INSERT INTO jobs VALUES(?,?,?,?,?)',(jid,owner,key,json.dumps(j,ensure_ascii=False),j['created']))
  launch(jid);return j

def select_identity_photo(owner,url):
 with GUARD:
  p=read_profile(owner)
  if not isinstance(url,str) or url not in p.get('photos',[]):raise UserError('请选择已上传的本人正面原照')
  p['identityPhoto']=url;save_profile(owner,p);return p

def select_scheme(owner,jid):
 with GUARD:
  j=load_job(jid)
  if not j or j['owner']!=owner or j['kind'] not in {'profile','view','face'}:raise UserError('方案不存在')
  if j['status'] not in TERMINAL:raise UserError('方案仍在生成中')
  views=j.get('schemeViews') or {x['key']:x['asset'] for x in j['slots'] if x.get('asset')}
  if len(views)!=4 or not j.get('summary'):raise UserError('请选择已完成四个视图的方案')
  p=read_profile(owner);p['views']=views;p['summary']=dict(j['summary']);p['summary']['accessories']=accessory_rules({'accessoryPolicy':p.get('accessoryPolicy',{})},p['summary'].get('accessories',[]));p['selectedScheme']=j['id'];save_profile(owner,p)
  return p

def remove_photo(owner,url):
 with GUARD:
  profile=read_profile(owner)
  if not isinstance(url,str) or url not in profile['photos']:raise UserError('这张照片不在当前形象库中')
  profile['photos']=[photo for photo in profile['photos'] if photo!=url]
  if profile.get('identityPhoto')==url:profile['identityPhoto']=profile['photos'][0] if profile['photos'] else None
  # Existing generated images and submitted reference snapshots are unaffected.
  save_profile(owner,profile)
  with db() as c:
   history=[json.loads(r[0]) for r in c.execute('SELECT data FROM jobs WHERE owner=?',(owner,)).fetchall()]
   referenced=any(url in job.get('photos',[]) or url in job.get('accessorySourcePhotos',[]) or url in job.get('accessoryRefs',[]) or job.get('realIdentityPhoto')==url or job.get('referenceAsset')==url for job in history) or url in profile.get('views',{}).values()
   if not referenced:
    row=c.execute('SELECT path FROM assets WHERE id=? AND owner=?',(url.rsplit('/',1)[-1],owner)).fetchone()
    c.execute('DELETE FROM assets WHERE id=? AND owner=?',(url.rsplit('/',1)[-1],owner))
    if row:Path(row[0]).unlink(missing_ok=True)
  return profile

def public_job(j):
 result={k:v for k,v in j.items() if k not in {'owner','photos','prompt','revision','referenceAsset','requestKey','accessorySourcePhotos'}}
 result['slots']=[s for s in j['slots'] if not s.get('deleted') and (j['status'] not in TERMINAL or s.get('asset') or s.get('status')=='uncertain')]
 return result

def public_jobs(owner):
 # Empty finished results disappear on refresh; durable jobs and credit records remain for reconciliation.
 result=[]
 for j in jobs(owner):
  visible=public_job(j)
  if visible['slots'] or j['status'] not in TERMINAL:result.append(visible)
 return result

def delete_works(owner,items):
 if not isinstance(items,list) or not 1<=len(items)<=500:raise UserError('请选择 1 至 500 张作品')
 with GUARD:
  history={j['id']:j for j in jobs(owner)};targets={}
  for item in items:
   if not isinstance(item,dict) or not isinstance(item.get('id'),str) or not isinstance(item.get('slot'),str):raise UserError('作品选择格式无效')
   j=history.get(item['id'])
   if not j or j['kind'] not in {'same','random'}:raise UserError('作品不存在或不属于当前账户')
   s=next((s for s in j['slots'] if s['key']==item['slot'] and s.get('asset')),None)
   if not s:raise UserError('请选择已生成的作品')
   if j['status'] not in TERMINAL or j['id'] in ACTIVE or (j['id'],s['key']) in REVIEWING or s.get('review',{}).get('status')=='checking':raise UserError('请等待所选作品生成或审核完成后再删除')
   targets[(j['id'],s['key'])]=(j,s)
  urls={s['asset'] for j,s in targets.values()}
  # Keep completed-slot tombstones and the credit ledger so retries cannot regenerate deleted results.
  for j,s in targets.values():s['deleted']=True
  visible=[{**j,'slots':[s for s in j['slots'] if not s.get('deleted')]} for j in history.values()]
  references=json.dumps([read_profile(owner),visible],ensure_ascii=False)
  paths=[]
  with db() as c:
   c.execute('BEGIN IMMEDIATE')
   for jid in {j['id'] for j,s in targets.values()}:
    j=history[jid];j['updated']=time.time();c.execute('UPDATE jobs SET data=? WHERE id=? AND owner=?',(json.dumps(j,ensure_ascii=False),jid,owner))
   for url in urls:
    # Retain a shared asset when another view or submitted task still needs it.
    if url in references:continue
    aid=url.rsplit('/',1)[-1];row=c.execute('SELECT path FROM assets WHERE id=? AND owner=?',(aid,owner)).fetchone()
    c.execute('DELETE FROM assets WHERE id=? AND owner=?',(aid,owner))
    if row:paths.append(Path(row[0]))
  for path in paths:path.unlink(missing_ok=True)
  return {'deleted':len(targets)}

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
 def send(code,data=None,raw=None,content_type=None,filename=None):
  body=raw if raw is not None else json.dumps(data,ensure_ascii=False).encode();h.send_response(code)
  h.send_header('Content-Type',content_type or ('image/jpeg' if raw is not None else 'application/json; charset=utf-8'));h.send_header('Cache-Control','private, no-store');h.send_header('X-Content-Type-Options','nosniff');h.send_header('Content-Length',str(len(body)))
  if filename:h.send_header('Content-Disposition','attachment; filename="'+filename+'"')
  if new:h.send_header('Set-Cookie','ootd_personal='+token+'; HttpOnly; SameSite=Lax; Path=/api/personal; Max-Age='+('0' if expire_cookie else '2592000')+('' if h.headers.get('Host','').startswith(('localhost','127.0.0.1')) else '; Secure'))
  h.end_headers();h.wfile.write(body)
 try:
  if h.command=='GET':
   if path=='/api/personal':send(200,{'credits':credit_balance(owner) if login else None,'authenticated':bool(login),'user':{'email':login['email']} if login else None,'loginConfigured':email_auth.configured(),'profile':read_profile(owner) if login else {'photos':[],'views':{},'summary':None},'jobs':public_jobs(owner) if login else [],'configured':bool(os.getenv('GRSAI_API_KEY')),'imageModel':IMAGE_MODEL,'reasonModel':REASON_MODEL})
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
  elif path=='/api/personal/photo/identity':send(200,{'profile':select_identity_photo(owner,q.get('photo'))})
  elif path=='/api/personal/scheme/select':send(200,{'profile':select_scheme(owner,q.get('id',''))})
  elif path=='/api/personal/photo/remove':send(200,{'profile':remove_photo(owner,q.get('photo'))})
  elif path=='/api/personal/works/delete':send(200,delete_works(owner,q.get('items')))
  elif path=='/api/personal/review':send(202,{'job':public_job(start_review(owner,q.get('id',''),q.get('slot')))})
  elif path=='/api/personal/publish/package':send(200,raw=publishing_package(owner,q),content_type='application/zip',filename='ootd-publish.zip')
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
     j['status']='queued';j['pollDeadline']=time.time()+900;j.pop('error',None);j['updated']=time.time()
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
