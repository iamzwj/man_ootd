import io,json,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import personal as p

class ReviewTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=patch.object(p,'ROOT',Path(self.tmp.name));self.root.start();self.addCleanup(self.root.stop);self.addCleanup(self.tmp.cleanup)
  stream=io.BytesIO();Image.new('RGB',(200,250),'gray').save(stream,'JPEG');self.original=p.store_asset('owner',stream.getvalue());self.output=p.store_asset('owner',stream.getvalue())
  self.job={'id':'job-review','owner':'owner','kind':'same','created':1,'requestKey':'review-key-123','status':'succeeded','realIdentityPhoto':self.original,'photos':[self.original],'slots':[{'key':'1','asset':self.output,'status':'succeeded','review':{'status':'passed','model':'test','reference':self.original}}]}
  with p.db() as c:c.execute('INSERT INTO jobs VALUES(?,?,?,?,?)',(self.job['id'],'owner',self.job['requestKey'],json.dumps(self.job),1))
 def raw(self,verdict='pass',issues=None):return {k:{'verdict':verdict,'issues':issues or [],'suggestions':[]} for k in ('appearance','naturalness')}
 def test_review_uses_real_original_then_output_and_normalizes(self):
  with patch.object(p,'reason',return_value=self.raw()) as reason:r=p.review_generated(self.job,self.job['slots'][0])
  self.assertEqual(r['status'],'passed');self.assertEqual(reason.call_args.args[1],[p.data_uri('owner',self.original),p.data_uri('owner',self.output)])
  with patch.object(p,'reason',return_value=self.raw(issues=['眼型有明显变化'])):self.assertEqual(p.review_generated(self.job,self.job['slots'][0])['status'],'needs_changes')
  with patch.object(p,'reason',return_value=self.raw('uncertain')):self.assertEqual(p.review_generated(self.job,self.job['slots'][0])['status'],'uncertain')
 def test_missing_or_invalid_review_does_not_pass(self):
  with patch.object(p,'reason',return_value={}):self.assertEqual(p.review_safely(self.job,self.job['slots'][0])['status'],'failed')
  j={**self.job,'realIdentityPhoto':None}
  self.assertEqual(p.review_safely(j,j['slots'][0])['status'],'failed')
 def test_scheme_review_uses_saved_face_instead_of_original(self):
  face=p.store_asset('owner',p.asset('owner',self.original));j={**self.job,'identityMethod':p.SCHEME_METHOD,'identityViews':{'face':face},'accessories':['黑框眼镜']}
  with patch.object(p,'reason',return_value=self.raw()) as reason:r=p.review_generated(j,j['slots'][0])
  self.assertEqual(reason.call_args.args[1][0],p.data_uri('owner',face));self.assertIn('可见区域缺少指定眼镜',reason.call_args.args[0]);self.assertEqual(r['referenceKind'],'scheme-face')
 def package(self,**change):return p.publishing_package('owner',{'id':'job-review','slot':'1','platform':'xiaohongshu','confirmed':True,'title':'窗边','caption':'光影记录',**change})
 def test_package_contains_only_result_and_copy_with_ai_label(self):
  with zipfile.ZipFile(io.BytesIO(self.package())) as z:
   self.assertEqual(set(z.namelist()),{'photo.jpg','caption.txt','review.json','发布说明.txt'});self.assertEqual(z.read('photo.jpg'),p.asset('owner',self.output));self.assertIn('AI生成图片',z.read('caption.txt').decode());self.assertNotIn(self.original,z.read('review.json').decode())
 def test_publish_requires_pass_and_human_confirmation_and_ownership(self):
  with self.assertRaises(p.UserError):self.package(confirmed=False)
  with self.assertRaises(p.UserError):p.publishing_package('other',{'id':'job-review'})
  j=p.load_job('job-review');j['slots'][0]['review']['status']='checking';p.save_job(j)
  with self.assertRaises(p.UserError):self.package()
 def test_manual_review_is_owned_and_deduplicated(self):
  with self.assertRaises(p.UserError):p.start_review('other','job-review','1')
  with patch.object(p.REVIEW_WORKERS,'submit') as submit:
   p.start_review('owner','job-review','1');p.start_review('owner','job-review','1');self.assertEqual(submit.call_count,1)
  p.REVIEWING.discard(('job-review','1'))

 def test_uncertain_review_can_be_manually_confirmed_without_faking_pass(self):
  j=p.load_job('job-review');j['slots'][0]['review']['status']='uncertain';p.save_job(j)
  with zipfile.ZipFile(io.BytesIO(self.package())) as z:
   review=json.loads(z.read('review.json'));self.assertEqual(review['status'],'uncertain');self.assertTrue(review['humanConfirmedForPreparation'])
