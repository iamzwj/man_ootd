import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import personal as p
from test_email_auth import Handler

class JobVisibilityTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  root=patch.object(p,'ROOT',Path(self.tmp.name));root.start();self.addCleanup(root.stop)
 def add(self,jid,status,slots,owner='owner'):
  j={'id':jid,'owner':owner,'kind':'same','created':1,'status':status,'slots':slots}
  with p.db() as c:c.execute('INSERT INTO jobs VALUES(?,?,?,?,?)',(jid,owner,'request-'+jid,json.dumps(j),1))
 def test_refresh_omits_empty_failed_and_ungenerated_finished_jobs_but_keeps_ledger(self):
  self.add('failed','failed',[{'key':'1','status':'failed'}]);self.add('empty','partial',[{'key':'1','status':'queued'}])
  with p.db() as c:c.execute('INSERT INTO image_credits VALUES(?,?,?,?,?,?)',('credit','owner',p.credit_day(),'failed','1','charged'))
  with patch.object(p.email_auth,'session',return_value={'owner':'owner','email':'test@example.com'}):
   h=Handler();self.assertEqual(h.run()['jobs'],[]);self.assertEqual(h.status,200)
  self.assertEqual(len(p.jobs('owner')),2);self.assertEqual(p.credit_balance('owner')['used'],1)
 def test_partial_results_keep_images_and_remove_only_empty_slots(self):
  self.add('partial','partial',[{'key':'1','status':'succeeded','asset':'/image'},{'key':'2','status':'failed'},{'key':'3','status':'queued'}])
  self.assertEqual([s['key'] for s in p.public_jobs('owner')[0]['slots']],['1'])
  self.assertEqual(len(p.load_job('partial')['slots']),3)
 def test_active_jobs_and_uncertain_submissions_remain_visible(self):
  for status in ['queued','running']:
   self.add(status,status,[{'key':'1','status':'queued'},{'key':'2','status':'running'}])
  self.add('unknown','uncertain',[{'key':'1','status':'uncertain','providerId':'pending'},{'key':'2','status':'failed'}])
  visible={j['id']:j for j in p.public_jobs('owner')}
  self.assertEqual(set(visible),{'queued','running','unknown'});self.assertEqual(len(visible['running']['slots']),2);self.assertEqual(len(visible['unknown']['slots']),1)
 def test_deleted_results_disappear_without_cross_account_access(self):
  self.add('deleted','succeeded',[{'key':'1','asset':'/old','deleted':True}])
  self.add('other','failed',[{'key':'1','status':'failed'}],owner='someone-else')
  self.assertEqual(p.public_jobs('owner'),[]);self.assertIsNotNone(p.load_job('other'))
