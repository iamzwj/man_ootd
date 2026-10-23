import io,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import personal as p
class PersonalTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=patch.object(p,'ROOT',Path(self.tmp.name));self.root.start()
  out=io.BytesIO();Image.new('RGB',(240,320),'gray').save(out,'JPEG');self.img=out.getvalue();self.owner='owner-a';self.photo=p.store_asset(self.owner,self.img)
  p.save_profile(self.owner,{'photos':[self.photo],'revision':'one','views':{},'summary':None})
 def tearDown(self):self.root.stop();self.tmp.cleanup()
 def test_asset_private(self):
  self.assertTrue(p.asset(self.owner,self.photo))
  with self.assertRaises(p.UserError):p.asset('other',self.photo)
 def test_bad_image_rejected(self):
  with self.assertRaises(p.UserError):p.clean_image(b'not-an-image')
 def test_upload_strips_metadata(self):
  original=Image.open(io.BytesIO(self.img));exif=original.getexif();exif[270]='private metadata';out=io.BytesIO();original.save(out,'JPEG',exif=exif)
  self.assertFalse(Image.open(io.BytesIO(p.clean_image(out.getvalue()))).getexif())
 def make(self,kind='profile',**extra):
  with patch.dict('os.environ',{'GRSAI_API_KEY':'test'}),patch.object(p,'launch'),patch.object(p,'remote_image',return_value=self.img):
   return p.create_job(self.owner,{'requestKey':'unique-key-'+kind,'kind':kind,**extra},[{'id':'ref','image':'https://example.com/photo.jpg','title':'参考','width':300,'height':400}])
 def ready(self):p.save_profile(self.owner,{'photos':[self.photo],'revision':'one','views':dict.fromkeys(['front','side','back','face'],self.photo),'summary':{'accessories':['眼镜']}})
 def test_idempotent_four_view_job(self):
  a=self.make();b=self.make();self.assertEqual(a['id'],b['id']);self.assertEqual(len(a['slots']),4);self.assertEqual(len(p.jobs(self.owner)),1)
 def test_exact_two_outputs_and_identity_prompt(self):
  self.ready();j=self.make('same',referenceId='ref');self.assertEqual(len(j['slots']),2);self.assertNotEqual(j['status'],'succeeded')
  with patch.object(p,'reason',return_value={'style':'咖啡馆侧光'}),patch.object(p,'submit_image',side_effect=['first','second']) as submit,patch.object(p,'api',return_value={'status':'succeeded','results':[{'url':'https://example.com/result.jpg'}]}),patch.object(p,'remote_image',return_value=self.img):p.execute(j['id'])
  done=p.load_job(j['id']);self.assertEqual(done['status'],'succeeded');self.assertTrue(all(s.get('asset') for s in done['slots']));self.assertEqual(submit.call_count,2);self.assertIn('绝不能复制最后一张里的人脸',submit.call_args.args[0]);self.assertEqual(len(submit.call_args.args[1]),4)
 def test_partial_success_kept(self):
  self.ready();j=self.make('same',referenceId='ref')
  with patch.object(p,'reason',return_value={'style':'自然光'}),patch.object(p,'submit_image',side_effect=['first',p.UserError('模型维护')]),patch.object(p,'api',return_value={'status':'succeeded','results':[{'url':'https://example.com/out.jpg'}]}),patch.object(p,'remote_image',return_value=self.img):p.execute(j['id'])
  done=p.load_job(j['id']);self.assertEqual(done['status'],'partial');self.assertTrue(done['slots'][0]['asset']);self.assertEqual(done['slots'][1]['status'],'failed')
 def test_maintenance_is_real_failure(self):
  j=self.make()
  with patch.object(p,'reason',side_effect=p.UserError('GRsai：该模型正在修复')):p.execute(j['id'])
  self.assertEqual(p.load_job(j['id'])['status'],'failed');self.assertIsNone(p.read_profile(self.owner)['summary'])
 def test_recovery_does_not_resubmit_unknown(self):
  j=self.make();j['slots'][0]['status']='submitting';p.save_job(j)
  with patch.object(p,'launch') as launch:p.resume()
  self.assertEqual(p.load_job(j['id'])['slots'][0]['status'],'uncertain');launch.assert_called_once()
 def test_random_only_given_page(self):
  self.ready()
  with self.assertRaises(p.UserError):self.make('random',referenceIds=['not-on-page'])
 def test_missing_provider_id_is_uncertain(self):
  with patch.object(p,'api',return_value={'status':'accepted'}):
   with self.assertRaises(p.UnknownSubmission):p.submit_image('prompt',[],'864x1152')
 def test_model_ids_and_protocol(self):
  with patch.object(p,'api',return_value={'data':{'id':'123'}}) as api:self.assertEqual(p.submit_image('prompt',['data:image/jpeg;base64,abc'],'864x1152'),'123')
  self.assertEqual(api.call_args.args[0],'/v1/api/generate');self.assertEqual(api.call_args.args[1]['model'],'gpt-image-2.5');self.assertEqual(api.call_args.args[1]['replyType'],'async')
if __name__=='__main__':unittest.main()
