import concurrent.futures,io,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import personal as p

class CreditsTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=patch.object(p,'ROOT',Path(self.tmp.name));self.root.start();self.day=patch.object(p,'credit_day',return_value='2026-10-23');self.day.start()
  out=io.BytesIO();Image.new('RGB',(240,320),'gray').save(out,'JPEG');self.image=out.getvalue();self.photo=p.store_asset('one',self.image)
  p.save_profile('one',{'photos':[self.photo],'views':dict.fromkeys(['front','side','back','face'],self.photo),'summary':{'accessories':[]},'revision':'one'})
 def tearDown(self):self.day.stop();self.root.stop();self.tmp.cleanup()
 def make(self,key='one',kind='same'):
  with patch.dict(os.environ,{'GRSAI_API_KEY':'test'}),patch.object(p,'launch'),patch.object(p,'remote_image',return_value=self.image):
   return p.create_job('one',{'requestKey':'request-key-'+key,'kind':kind,'referenceId':'ref'},[{'id':'ref','image':'https://example.com/image.jpg','title':'ref'}])
 def settle(self,j,success=0,uncertain=False):
  for i,s in enumerate(j['slots']):
   if i<success:s['asset']=self.photo;s['status']='succeeded'
   else:s['status']='uncertain' if uncertain else 'failed'
  j['status']='uncertain' if uncertain else 'succeeded' if success==len(j['slots']) else 'partial' if success else 'failed';p.save_job(j)
 def test_daily_ten_and_account_isolation(self):
  self.assertEqual(p.credit_balance('one')['remaining'],10);self.make();self.assertEqual(p.credit_balance('one')['remaining'],8);self.assertEqual(p.credit_balance('other')['remaining'],10)
 def test_profile_four_and_idempotent_submission(self):
  a=self.make(kind='profile');b=self.make(kind='profile');self.assertEqual(a['id'],b['id']);self.assertEqual(p.credit_balance('one')['remaining'],6)
 def test_success_charge_once_partial_refund_once(self):
  j=self.make();self.settle(j,1);p.save_job(j);balance=p.credit_balance('one');self.assertEqual(balance['remaining'],9);self.assertEqual(balance['used'],1);self.assertEqual(balance['reserved'],0)
 def test_analysis_failure_refunds_all(self):
  j=self.make(kind='profile');j['status']='failed';p.save_job(j);self.assertEqual(p.credit_balance('one')['remaining'],10)
 def test_unknown_submission_stays_reserved(self):
  j=self.make();self.settle(j,uncertain=True);self.assertEqual(p.credit_balance('one')['remaining'],8);self.assertEqual(p.credit_balance('one')['reserved'],2)
 def test_timeout_query_retry_does_not_double_charge(self):
  j=self.make()
  for s in j['slots']:s['providerId']='running-id';s['status']='failed'
  j['status']='failed';p.save_job(j)
  with p.db() as c:c.execute('BEGIN IMMEDIATE');p.reserve_credits(c,j,j['slots'])
  self.assertEqual(p.credit_balance('one')['remaining'],8)
 def test_failed_provider_retry_reserves_only_failed_image(self):
  j=self.make();self.settle(j,1)
  with p.db() as c:c.execute('BEGIN IMMEDIATE');p.reserve_credits(c,j,j['slots'])
  self.assertEqual(p.credit_balance('one')['remaining'],8);self.assertEqual(p.credit_balance('one')['used'],1);self.assertEqual(p.credit_balance('one')['reserved'],1)
 def test_daily_limit_cannot_be_bypassed_by_new_jobs(self):
  for i in range(5):self.settle(self.make(str(i)),2)
  self.assertEqual(p.credit_balance('one')['remaining'],0)
  with self.assertRaises(p.UserError):self.make('excess')
 def test_midnight_reset_and_cross_day_refund(self):
  j=self.make();self.day.stop()
  with patch.object(p,'credit_day',return_value='2026-10-24'):
   self.assertEqual(p.credit_balance('one')['remaining'],10);self.settle(j,0);self.assertEqual(p.credit_balance('one')['remaining'],10)
  self.day=patch.object(p,'credit_day',return_value='2026-10-23');self.day.start();self.assertEqual(p.credit_balance('one')['remaining'],10)
 def test_deleting_jobs_does_not_restore_spent_credits(self):
  j=self.make();self.settle(j,2)
  with p.db() as c:c.execute('DELETE FROM jobs WHERE owner=?',('one',))
  self.assertEqual(p.credit_balance('one')['remaining'],8)
 def test_completed_provider_but_failed_download_refunds(self):
  j=self.make()
  for s in j['slots']:s['providerId']='done';s['providerCompleted']=True;s['status']='failed'
  j['status']='failed';p.save_job(j);self.assertEqual(p.credit_balance('one')['remaining'],10)
 def test_definite_upstream_failure_refunds_with_provider_id(self):
  j=self.make()
  for s in j['slots']:s['providerId']='failed';s['providerFailed']=True;s['status']='failed'
  j['status']='failed';p.save_job(j);self.assertEqual(p.credit_balance('one')['remaining'],10)
 def test_atomic_concurrent_reservations(self):
  def reserve(i):
   j={'id':str(i),'owner':'one','slots':[{'key':'1'},{'key':'2'}]}
   try:
    with p.db() as c:c.execute('BEGIN IMMEDIATE');p.reserve_credits(c,j,j['slots'])
    return True
   except p.UserError:return False
  with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(reserve,range(8)))
  self.assertEqual(sum(results),5);self.assertEqual(p.credit_balance('one')['remaining'],0)
 def test_transaction_rollback_restores_balance(self):
  with self.assertRaises(ValueError):
   with p.db() as c:
    c.execute('BEGIN IMMEDIATE');p.reserve_credits(c,{'id':'bad','owner':'one'},[{'key':'1'}]);raise ValueError()
  self.assertEqual(p.credit_balance('one')['remaining'],10)

if __name__=='__main__':unittest.main()
