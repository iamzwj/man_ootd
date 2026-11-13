import io,json,tempfile,unittest
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
  self.assertIn('不得建议恢复面部特写中的固定表情',reason.call_args.args[0])
 def test_manual_review_is_owned_and_deduplicated(self):
  with self.assertRaises(p.UserError):p.start_review('other','job-review','1')
  with patch.object(p.REVIEW_WORKERS,'submit') as submit:
   p.start_review('owner','job-review','1');p.start_review('owner','job-review','1');self.assertEqual(submit.call_count,1)
  p.REVIEWING.discard(('job-review','1'))
