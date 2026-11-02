import io,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import personal as p

class DeleteWorksTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  root=patch.object(p,'ROOT',Path(self.tmp.name));root.start();self.addCleanup(root.stop)
  stream=io.BytesIO();Image.new('RGB',(200,250),'gray').save(stream,'JPEG')
  self.urls=[p.store_asset('owner',stream.getvalue()) for _ in range(3)]
  p.save_profile('owner',{'photos':[self.urls[0]],'views':{}})
  self.job={'id':'work','owner':'owner','kind':'same','status':'succeeded','created':1,'slots':[{'key':'1','asset':self.urls[1],'status':'succeeded'},{'key':'2','asset':self.urls[2],'status':'succeeded'}]}
  with p.db() as c:
   c.execute('INSERT INTO jobs VALUES(?,?,?,?,?)',('work','owner','request',json.dumps(self.job),1))
   c.execute('INSERT INTO image_credits VALUES(?,?,?,?,?,?)',('credit','owner',p.credit_day(),'work','1','charged'))
 def test_deletes_only_selected_asset_and_preserves_credits_and_original(self):
  result=p.delete_works('owner',[{'id':'work','slot':'1'}]);self.assertEqual(result['deleted'],1)
  j=p.load_job('work');self.assertTrue(j['slots'][0]['deleted']);self.assertEqual([s['key'] for s in p.public_job(j)['slots']],['2'])
  with self.assertRaises(p.UserError):p.asset('owner',self.urls[1])
  self.assertTrue(p.asset('owner',self.urls[0]));self.assertTrue(p.asset('owner',self.urls[2]))
  self.assertEqual(p.credit_balance('owner')['used'],1)
  p.delete_works('owner',[{'id':'work','slot':'1'}])
 def test_batch_validation_is_atomic_and_owner_scoped(self):
  for owner,items in [('other',[{'id':'work','slot':'1'}]),('owner',[{'id':'work','slot':'1'},{'id':'missing','slot':'2'}]),('owner',[])]:
   with self.assertRaises(p.UserError):p.delete_works(owner,items)
  self.assertTrue(p.asset('owner',self.urls[1]));self.assertFalse(p.load_job('work')['slots'][0].get('deleted'))
 def test_running_and_reviewing_results_cannot_be_deleted(self):
  j=p.load_job('work');j['status']='running';p.save_job(j)
  with self.assertRaises(p.UserError):p.delete_works('owner',[{'id':'work','slot':'1'}])
  j['status']='succeeded';j['slots'][0]['review']={'status':'checking'};p.save_job(j)
  with self.assertRaises(p.UserError):p.delete_works('owner',[{'id':'work','slot':'1'}])
 def test_shared_asset_remains_accessible_and_deleted_work_cannot_be_reviewed(self):
  p.save_profile('owner',{'photos':[self.urls[0]],'views':{'front':self.urls[1]}})
  p.delete_works('owner',[{'id':'work','slot':'1'},{'id':'work','slot':'2'}])
  self.assertTrue(p.asset('owner',self.urls[1]));self.assertEqual(p.public_job(p.load_job('work'))['slots'],[])
  with self.assertRaises(p.UserError):p.start_review('owner','work','1')
