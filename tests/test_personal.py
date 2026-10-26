import io,json,tempfile,time,unittest
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
  a=self.make();b=self.make();self.assertEqual(a['id'],b['id']);self.assertEqual(len(a['slots']),4);self.assertEqual(a['size'],'1024x1536');self.assertEqual(len(p.jobs(self.owner)),1)
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
 def test_reasoning_uses_verified_model_and_effort(self):
  with patch.object(p,'api',return_value={'choices':[{'message':{'content':'{"description":"短发","accessories":[]}'}}]}) as api:
   self.assertEqual(p.reason('分析',['data:image/jpeg;base64,abc'])['accessories'],[])
  self.assertEqual(api.call_args.args[1]['model'],'gpt-5.6-terra');self.assertEqual(api.call_args.args[1]['reasoning_effort'],'low')
 def test_complete_profile_persists_four_distinct_views(self):
  j=self.make()
  with patch.object(p,'reason',return_value={'description':'短发成年男性','accessories':[],'missingViews':['背面']}) as reason,patch.object(p,'submit_image',side_effect=['a','b','c','d']),patch.object(p,'api',return_value={'status':'succeeded','results':[{'url':'https://example.com/result.jpg'}]}),patch.object(p,'remote_image',return_value=self.img),patch.object(p,'face_is_closeup',return_value=True):p.execute(j['id'])
  profile=p.read_profile(self.owner);self.assertEqual(set(profile['views']),{'front','side','back','face'});self.assertEqual(len(set(profile['views'].values())),4);self.assertEqual(p.load_job(j['id'])['status'],'succeeded');self.assertIn('不包括杯子',reason.call_args.args[0])
 def test_face_prompt_has_no_full_body_instructions(self):
  prompt,size=p.portrait_input({'prompt':'FULL LENGTH HEAD TO TOE, including both shoes','size':'1024x1536','summary':{'description':'短发','accessories':[]}}, {'key':'face'})
  self.assertEqual(size,'1024x1024');self.assertIn('70%至85%',prompt);self.assertNotIn('FULL LENGTH HEAD TO TOE',prompt);self.assertNotIn('白色休闲鞋',prompt)
 def test_face_gate_rejects_full_body_and_invalid_json_fields(self):
  for result in [{'isCloseUp':False,'faceHeightRatio':.12,'faceWidthRatio':.1},{'isCloseUp':True,'faceHeightRatio':.2,'faceWidthRatio':.6},{'isCloseUp':True,'faceHeightRatio':True,'faceWidthRatio':True},{}]:
   with patch.object(p,'reason',return_value=result):self.assertFalse(p.face_is_closeup(self.img))
  with patch.object(p,'reason',return_value={'isCloseUp':True,'faceHeightRatio':.75,'faceWidthRatio':.65}):self.assertTrue(p.face_is_closeup(self.img))
 def test_standalone_face_task_is_not_a_supported_action(self):
  with self.assertRaises(p.UserError):self.make('face')
 def test_wrong_face_output_fails_and_refunds(self):
  j=self.make()
  with patch.object(p,'reason',return_value={'description':'短发','accessories':[]}),patch.object(p,'submit_image',return_value='face-id'),patch.object(p,'api',return_value={'status':'succeeded','results':[{'url':'https://example.com/wrong.jpg'}]}),patch.object(p,'remote_image',return_value=self.img),patch.object(p,'face_is_closeup',return_value=False):p.execute(j['id'])
  self.assertEqual(p.load_job(j['id'])['status'],'partial');self.assertEqual(p.credit_balance(self.owner)['remaining'],7);self.assertNotIn('face',p.read_profile(self.owner)['views'])
 def test_failed_result_with_error_is_not_treated_as_transport_error(self):
  for result in [{'status':'failed','error':'generate image failed'},{'data':{'status':'failed'},'error':{'message':'failed'}}]:
   with patch.dict('os.environ',{'GRSAI_API_KEY':'test'}),patch.object(p,'urlopen',return_value=io.BytesIO(json.dumps(result).encode())):
    self.assertEqual(p.api('/v1/api/result?id=private'),result)
 def test_long_running_profile_finishes_partial_on_upstream_failure(self):
  j=self.make();j['prompt']='existing prompt';j['summary']={'description':'short hair','accessories':[]};j['created']=time.time()-4000
  for slot in j['slots'][:3]:slot['asset']=self.photo;slot['status']='succeeded'
  j['slots'][3].update(providerId='failed-face',status='running');p.save_job(j)
  with patch.object(p,'api',return_value={'status':'failed','error':'generate image failed'}),patch.object(p,'submit_image') as submit:p.execute(j['id'])
  done=p.load_job(j['id']);self.assertEqual(done['status'],'partial');self.assertTrue(done['slots'][3]['providerFailed']);self.assertEqual(len(p.read_profile(self.owner)['views']),3);self.assertEqual(p.credit_balance(self.owner)['remaining'],7);submit.assert_not_called()
 def test_poll_deadline_is_not_extended_by_resume(self):
  self.ready();j=self.make('same',referenceId='ref');j['prompt']='existing prompt';j['pollDeadline']=time.time()-1
  for slot in j['slots']:slot.update(providerId='pending',status='running')
  p.save_job(j)
  with patch.object(p,'api',return_value={'status':'running'}),patch.object(p.time,'sleep') as sleep:p.execute(j['id'])
  done=p.load_job(j['id']);self.assertEqual(done['status'],'failed');self.assertEqual(done['pollDeadline'],j['pollDeadline']);sleep.assert_not_called()
 def test_remove_only_selected_photo_preserves_views_and_credits(self):
  other=p.store_asset(self.owner,self.img);profile=p.read_profile(self.owner);profile.update(photos=[self.photo,other],views={'front':'generated-reference'},summary={'description':'keep'});p.save_profile(self.owner,profile)
  result=p.remove_photo(self.owner,self.photo);self.assertEqual(result['photos'],[other]);self.assertEqual(result['views'],profile['views']);self.assertEqual(result['summary'],profile['summary']);self.assertEqual(p.credit_balance(self.owner)['remaining'],10)
  with self.assertRaises(p.UserError):p.asset(self.owner,self.photo)
 def test_remove_cannot_access_another_account(self):
  with self.assertRaises(p.UserError):p.remove_photo('other-owner',self.photo)
  self.assertTrue(p.asset(self.owner,self.photo))
 def test_remove_keeps_submitted_task_reference_snapshot(self):
  j=self.make();result=p.remove_photo(self.owner,self.photo);self.assertEqual(result['photos'],[]);self.assertEqual(p.load_job(j['id'])['photos'],[self.photo]);self.assertTrue(p.asset(self.owner,self.photo))
 def test_model_ids_and_protocol(self):
  with patch.object(p,'api',return_value={'data':{'id':'123'}}) as api:self.assertEqual(p.submit_image('prompt',['data:image/jpeg;base64,abc'],'864x1152'),'123')
  self.assertEqual(api.call_args.args[0],'/v1/api/generate');self.assertEqual(api.call_args.args[1]['model'],'gpt-image-2');self.assertEqual(api.call_args.args[1]['replyType'],'async')
if __name__=='__main__':unittest.main()
