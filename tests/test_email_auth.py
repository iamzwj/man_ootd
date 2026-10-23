import io,json,os,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
import personal as p
import email_auth as a

class Handler:
 def __init__(self,path='',data=None,cookie='',method=None):
  self.path='/api/personal'+path;self.command=method or ('POST' if data is not None else 'GET');self.client_address=('127.0.0.1',1);self.status=0;self.sent={};self.wfile=io.BytesIO()
  body=json.dumps(data).encode() if data is not None else b'';self.rfile=io.BytesIO(body)
  self.headers={'Host':'ootd.example.com','Origin':'https://ootd.example.com','Content-Type':'application/json','Content-Length':str(len(body)),'Cookie':cookie}
 def send_response(self,status):self.status=status
 def send_header(self,k,v):self.sent[k]=v
 def end_headers(self):pass
 def run(self):p.handle(self,lambda:[]);return json.loads(self.wfile.getvalue())

class EmailAuthTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=patch.object(p,'ROOT',Path(self.tmp.name));self.root.start();self.env=patch.dict(os.environ,{'SMTP_HOST':'smtp.test','SMTP_USERNAME':'sender@example.com','SMTP_PASSWORD':'test'});self.env.start()
 def tearDown(self):self.env.stop();self.root.stop();self.tmp.cleanup()
 def code(self,email='a@example.com',ip='ip'):
  with patch.object(a,'mail') as mail:a.send_code(email,ip)
  return mail.call_args.args[1]
 def test_send_stores_only_digest_and_enforces_cooldown(self):
  code=self.code()
  with p.db() as c:r=c.execute('SELECT * FROM auth_codes').fetchone()
  self.assertNotEqual(r['digest'],code);self.assertEqual(len(r['digest']),64)
  with self.assertRaises(a.AuthError) as e:a.send_code('a@example.com','ip')
  self.assertEqual(e.exception.status,429)
 def test_five_wrong_attempts_are_persisted(self):
  code=self.code();wrong='111111' if code!='111111' else '222222'
  for _ in range(5):
   with self.assertRaises(a.AuthError):a.verify('a@example.com',wrong,'legacy','ip')
  with self.assertRaises(a.AuthError) as e:a.verify('a@example.com',code,'legacy','ip')
  self.assertEqual(e.exception.status,429)
 def test_expired_and_reused_codes_rejected(self):
  code=self.code();token,_=a.verify('a@example.com',code,'legacy','ip');self.assertEqual(a.session(token)['owner'],'legacy')
  with self.assertRaises(a.AuthError):a.verify('a@example.com',code,'legacy','ip')
  code=self.code('b@example.com')
  with p.db() as c:c.execute('UPDATE auth_codes SET expires=0 WHERE email=?',('b@example.com',))
  with self.assertRaises(a.AuthError):a.verify('b@example.com',code,'legacy','ip')
 def test_same_email_restores_library_across_sessions(self):
  code=self.code();t1,_=a.verify('a@example.com',code,'legacy','ip');p.save_profile('legacy',{'photos':['private'],'views':{}})
  with p.db() as c:c.execute('UPDATE auth_codes SET sent=0')
  code=self.code();t2,_=a.verify('a@example.com',code,'different-browser','ip')
  self.assertNotEqual(t1,t2);self.assertEqual(a.session(t2)['owner'],'legacy');a.logout(t1);self.assertIsNone(a.session(t1));self.assertTrue(a.session(t2))
 def test_email_accounts_are_separate(self):
  c1=self.code();c2=self.code('b@example.com');t1,_=a.verify('a@example.com',c1,'one','ip');t2,_=a.verify('b@example.com',c2,'two','ip')
  self.assertNotEqual(a.session(t1)['owner'],a.session(t2)['owner'])
 def test_unauthenticated_generation_and_assets_blocked(self):
  for path,data in [('/generate',{'kind':'profile'}),('/upload',{'photos':[]}),('/retry',{}),('/assets/unknown',None)]:
   h=Handler(path,data);result=h.run();self.assertEqual(h.status,401);self.assertIn('登录',result['error'])
  h=Handler();result=h.run();self.assertFalse(result['authenticated']);self.assertEqual(result['jobs'],[])
 def test_real_http_contract_cookie_and_logout(self):
  h=Handler('/auth/send',{'email':'a@example.com'})
  with patch.object(a,'mail') as mail:result=h.run()
  self.assertTrue(result['sent']);code=mail.call_args.args[1]
  h=Handler('/auth/verify',{'email':'a@example.com','code':code});self.assertTrue(h.run()['authenticated']);cookie=h.sent['Set-Cookie'];self.assertIn('HttpOnly',cookie);self.assertIn('Secure',cookie)
  h=Handler(cookie=cookie.split(';')[0]);self.assertTrue(h.run()['authenticated'])
  out=Handler('/auth/logout',{},cookie=cookie.split(';')[0]);self.assertTrue(out.run()['ok']);self.assertIn('Max-Age=0',out.sent['Set-Cookie'])
  self.assertFalse(Handler(cookie=cookie.split(';')[0]).run()['authenticated'])
 def test_csrf_and_email_header_injection_rejected(self):
  h=Handler('/auth/send',{'email':'a@example.com'});h.headers['Origin']='https://evil.example';h.run();self.assertEqual(h.status,403)
  with self.assertRaises(a.AuthError):a.normalize('a@example.com\r\nBcc: victim@example.com')
 def test_expired_session_cannot_access(self):
  code=self.code();token,_=a.verify('a@example.com',code,'legacy','ip')
  with p.db() as c:c.execute('UPDATE auth_sessions SET expires=0')
  self.assertIsNone(a.session(token))
 def test_ip_rate_limit_does_not_send_mail(self):
  with p.db() as c:
   c.executemany('INSERT INTO auth_mail_log VALUES(?,?,?)',[(str(i)+'@example.com','ip',time.time()) for i in range(10)])
  with patch.object(a,'mail') as mail:
   with self.assertRaises(a.AuthError):a.send_code('a@example.com','ip')
   mail.assert_not_called()

if __name__=='__main__':unittest.main()
