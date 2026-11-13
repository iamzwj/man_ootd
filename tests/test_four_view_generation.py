import unittest
from unittest.mock import patch
from test_personal import PersonalTests
import personal as p

class FourViewGenerationTests(PersonalTests):
 def test_same_uses_only_frozen_scheme_and_style_without_original_accessories(self):
  self.ready();profile=p.read_profile(self.owner)
  profile['views']={k:p.store_asset(self.owner,self.img) for k in p.IDENTITY_VIEW_ORDER};profile['summary']={'description':'当前方案','accessories':['黑框透明镜片眼镜','银色耳环']};p.save_profile(self.owner,profile)
  j=self.make('same',referenceId='ref')
  self.assertEqual(j['identityMethod'],p.SCHEME_METHOD);self.assertNotIn('accessorySourcePhotos',j);self.assertNotIn('realIdentityPhoto',j)
  with patch.object(p,'reason',return_value={'style':'普通街头'}) as reason,patch.object(p,'submit_image',side_effect=['a','b']) as submit,patch.object(p,'api',return_value={'status':'succeeded','results':[{'url':'https://example.com/out.jpg'}]}),patch.object(p,'remote_image',return_value=self.img):p.execute(j['id'])
  self.assertEqual(reason.call_count,1);self.assertEqual(len(reason.call_args.args[1]),1)
  self.assertIn('表情与神态',reason.call_args.args[0]);self.assertIn('嘴部开合',reason.call_args.args[0])
  self.assertIn('表情与神态以第5张风格图为准',submit.call_args.args[0]);self.assertIn('不能照搬其微笑',submit.call_args.args[0])
  self.assertEqual(len(submit.call_args.args[1]),5);self.assertNotIn(self.photo,j['photos']);self.assertIn('第4张面部特写为主',submit.call_args.args[0]);self.assertIn('黑框透明镜片眼镜',submit.call_args.args[0]);self.assertIn('accessoriesChecked',p.load_job(j['id'])['slots'][0])
 def test_missing_expected_view_is_rejected_before_credit_reservation(self):
  self.ready();profile=p.read_profile(self.owner);profile['views']['face']='';p.save_profile(self.owner,profile)
  before=p.credit_balance(self.owner)
  with self.assertRaises(p.UserError):self.make('same',referenceId='ref')
  self.assertEqual(p.credit_balance(self.owner),before)
 def test_missing_glasses_fails_output_and_refunds(self):
  self.ready();j=self.make('same',referenceId='ref')
  with patch.object(p,'reason',return_value={'style':'街头'}),patch.object(p,'submit_image',side_effect=['a','b']),patch.object(p,'api',return_value={'status':'succeeded','results':[{'url':'https://example.com/out.jpg'}]}),patch.object(p,'remote_image',return_value=self.img),patch.object(p,'accessories_match',return_value=False):p.execute(j['id'])
  self.assertEqual(p.load_job(j['id'])['status'],'failed');self.assertEqual(p.credit_balance(self.owner)['remaining'],10)
