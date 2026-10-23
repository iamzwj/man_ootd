"""Email OTP authentication. Codes and session tokens are never stored in plaintext."""
import hashlib,hmac,json,os,re,secrets,smtplib,ssl,time
from email.message import EmailMessage
from email.utils import formataddr

class AuthError(Exception):
 def __init__(self,message,status=400):super().__init__(message);self.status=status

def configured():return all(os.getenv(k) for k in ('SMTP_HOST','SMTP_USERNAME','SMTP_PASSWORD'))

def normalize(email):
 if not isinstance(email,str):raise AuthError('请输入有效的邮箱地址')
 email=email.strip().lower()
 if len(email)>254 or not re.fullmatch(r'[a-z0-9._%+\-]{1,64}@[a-z0-9](?:[a-z0-9.\-]*[a-z0-9])?\.[a-z]{2,63}',email):raise AuthError('请输入有效的邮箱地址')
 return email

def key():
 import personal as p
 path=p.ROOT/'auth.key'
 try:
  fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
  with os.fdopen(fd,'wb') as f:f.write(secrets.token_bytes(32))
 except FileExistsError:pass
 return path.read_bytes()

def digest(email,code):return hmac.new(key(),(email+'\0'+code).encode(),hashlib.sha256).hexdigest()
def token_hash(token):return hashlib.sha256(token.encode()).hexdigest()

def session(token):
 if not token:return None
 import personal as p
 with p.db() as c:r=c.execute('SELECT owner,email FROM auth_sessions WHERE hash=? AND expires>?',(token_hash(token),time.time())).fetchone()
 return dict(r) if r else None

def mail(email,code):
 if not configured():raise AuthError('邮箱登录服务暂未配置，请稍后再试',503)
 username=os.environ['SMTP_USERNAME'];port=int(os.getenv('SMTP_PORT','465'));host=os.environ['SMTP_HOST']
 msg=EmailMessage();msg['From']=formataddr(('OOTD',username));msg['To']=email;msg['Subject']='OOTD 登录验证码'
 msg.set_content('你的 OOTD 登录验证码：'+code+'\n\n验证码 10 分钟内有效，仅可使用一次。如非本人操作，请忽略此邮件。请勿向他人透露验证码。')
 msg.add_alternative('<div style="font-family:sans-serif;color:#30392d;padding:24px"><h2>登录 OOTD</h2><p>你的邮箱验证码</p><p style="font-size:30px;font-weight:600;letter-spacing:7px">'+code+'</p><p>10 分钟内有效，仅可使用一次。<br>如非本人操作，请忽略此邮件。请勿向他人透露验证码。</p></div>',subtype='html')
 try:
  context=ssl.create_default_context()
  if port==465:
   with smtplib.SMTP_SSL(host,port,timeout=15,context=context) as smtp:
    smtp.login(username,os.environ['SMTP_PASSWORD']);refused=smtp.send_message(msg,from_addr=username,to_addrs=[email])
  else:
   with smtplib.SMTP(host,port,timeout=15) as smtp:
    smtp.ehlo();smtp.starttls(context=context);smtp.ehlo();smtp.login(username,os.environ['SMTP_PASSWORD']);refused=smtp.send_message(msg,from_addr=username,to_addrs=[email])
  if refused:raise AuthError('邮件服务器未接受验证码，请稍后再试',503)
 except AuthError:raise
 except Exception:raise AuthError('验证码发送失败，请稍后重试',503)

def send_code(email,ip):
 import personal as p
 email=normalize(email)
 if not configured():raise AuthError('邮箱登录服务暂未配置，请稍后再试',503)
 now=time.time();code=f'{secrets.randbelow(1000000):06d}'
 with p.GUARD:
  with p.db() as c:
   c.execute('DELETE FROM auth_mail_log WHERE created<?',(now-86400,));c.execute('DELETE FROM auth_sessions WHERE expires<?',(now,))
   recent=c.execute('SELECT sent FROM auth_codes WHERE email=?',(email,)).fetchone()
   if recent and recent[0]>now-60:raise AuthError('请 60 秒后再获取验证码',429)
   counts=[c.execute(sql,args).fetchone()[0] for sql,args in [
    ('SELECT COUNT(*) FROM auth_mail_log WHERE email=? AND created>?',(email,now-3600)),
    ('SELECT COUNT(*) FROM auth_mail_log WHERE ip=? AND created>?',(ip,now-3600)),
    ('SELECT COUNT(*) FROM auth_mail_log WHERE created>?',(now-3600,))]]
   if counts[0]>=5 or counts[1]>=10 or counts[2]>=100:raise AuthError('验证码请求较多，请稍后再试',429)
   c.execute('INSERT OR REPLACE INTO auth_codes VALUES(?,?,?,?,?)',(email,digest(email,code),now+600,0,now))
   c.execute('INSERT INTO auth_mail_log VALUES(?,?,?)',(email,ip,now))
 try:mail(email,code)
 except Exception:
  with p.db() as c:c.execute('DELETE FROM auth_codes WHERE email=? AND digest=?',(email,digest(email,code)))
  raise
 return {'sent':True,'retryAfter':60,'expiresIn':600}

def verify(email,code,legacy_owner,ip):
 import personal as p
 email=normalize(email)
 if not isinstance(code,str) or not re.fullmatch(r'\d{6}',code):raise AuthError('请输入 6 位验证码')
 now=time.time()
 with p.GUARD:
  failure=None
  with p.db() as c:
   c.execute('DELETE FROM auth_attempts WHERE created<?',(now-3600,))
   count=c.execute('SELECT COUNT(*) FROM auth_attempts WHERE ip=? AND created>?',(ip,now-3600)).fetchone()[0]
   if count>=30:raise AuthError('验证请求较多，请稍后再试',429)
   c.execute('INSERT INTO auth_attempts VALUES(?,?)',(ip,now))
   r=c.execute('SELECT digest,expires,attempts FROM auth_codes WHERE email=?',(email,)).fetchone()
   if not r or r['expires']<=now:failure=AuthError('验证码已过期，请重新获取')
   elif r['attempts']>=5:failure=AuthError('验证码错误次数过多，请重新获取',429)
   elif not hmac.compare_digest(r['digest'],digest(email,code)):
    c.execute('UPDATE auth_codes SET attempts=attempts+1 WHERE email=?',(email,));failure=AuthError('验证码不正确')
   else:
    c.execute('DELETE FROM auth_codes WHERE email=?',(email,))
    account=c.execute('SELECT id FROM auth_accounts WHERE email=?',(email,)).fetchone()
    if account:owner=account['id']
    else:
     # Adopt a pre-login library only on first registration; rotate the cookie below.
     owner=legacy_owner
     if c.execute('SELECT 1 FROM auth_accounts WHERE id=?',(owner,)).fetchone():owner=secrets.token_hex(32)
     c.execute('INSERT INTO auth_accounts VALUES(?,?,?)',(owner,email,now))
    token=secrets.token_hex(32)
    c.execute('INSERT INTO auth_sessions VALUES(?,?,?,?)',(token_hash(token),owner,email,now+30*86400))
  if failure:raise failure
 return token,{'email':email}

def logout(token):
 import personal as p
 with p.db() as c:c.execute('DELETE FROM auth_sessions WHERE hash=?',(token_hash(token),))
