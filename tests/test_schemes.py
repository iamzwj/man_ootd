from test_personal import PersonalTests
from unittest.mock import patch
import personal as p

class SchemeTests(PersonalTests):
 def test_single_view_keeps_other_views_and_charges_one(self):
  self.ready();before=p.read_profile(self.owner)['views'].copy();j=self.make('view',view='side')
  self.assertEqual(len(j['slots']),1);self.assertEqual(p.credit_balance(self.owner)['remaining'],9)
  with patch.object(p,'reason',return_value={'description':'短发','accessories':[]}),patch.object(p,'submit_image',return_value='one') as submit,patch.object(p,'api',return_value={'status':'succeeded','results':[{'url':'https://example.com/result.jpg'}]}),patch.object(p,'remote_image',return_value=self.img):p.execute(j['id'])
  after=p.read_profile(self.owner);self.assertEqual(submit.call_count,1)
  for key in ['front','back','face']:self.assertEqual(after['views'][key],before[key])
  self.assertNotEqual(after['views']['side'],before['side']);self.assertEqual(after['selectedScheme'],j['id'])
  self.assertEqual(p.select_scheme(self.owner,j['id'])['views'],after['views'])
  with self.assertRaises(p.UserError):p.select_scheme('other',j['id'])
 def test_failed_regeneration_preserves_selected_scheme(self):
  self.ready();before=p.read_profile(self.owner);j=self.make('view',view='face')
  with patch.object(p,'reason',side_effect=p.UserError('维护')):p.execute(j['id'])
  self.assertEqual(p.read_profile(self.owner),before);self.assertEqual(p.credit_balance(self.owner)['remaining'],10)
 def test_invalid_view_rejected(self):
  self.ready()
  with self.assertRaises(p.UserError):self.make('view',view='invalid')
 def test_same_uses_selected_four_views_and_freezes_them(self):
  self.ready();profile=p.read_profile(self.owner)
  selected={k:p.store_asset(self.owner,self.img) for k in ['face','front','side','back']}
  profile.update(views=selected,selectedScheme='chosen-scheme',summary={'description':'所选方案','accessories':['眼镜']});p.save_profile(self.owner,profile)
  j=self.make('same',referenceId='ref',schemeId='chosen-scheme')
  self.assertEqual(j['photos'],[self.photo,selected['front']]);self.assertEqual(j['realIdentityPhoto'],self.photo);self.assertEqual(j['identityViews'],selected)
  profile.update(views=dict.fromkeys(selected,self.photo),selectedScheme='later-scheme',summary={'accessories':['帽子']});p.save_profile(self.owner,profile)
  with patch.object(p,'reason',return_value={'style':'窗边自然光'}),patch.object(p,'submit_image',side_effect=['a','b']) as submit,patch.object(p,'api',return_value={'status':'succeeded','results':[{'url':'https://example.com/out.jpg'}]}),patch.object(p,'remote_image',return_value=self.img):p.execute(j['id'])
  self.assertEqual(submit.call_count,2);self.assertEqual(submit.call_args.args[1][:-1],[p.data_uri(self.owner,u) for u in [self.photo,selected['front']]])
  self.assertIn('眼镜',submit.call_args.args[0]);self.assertNotIn('帽子',submit.call_args.args[0]);self.assertEqual(p.load_job(j['id'])['identityScheme'],'chosen-scheme')
 def test_stale_selected_scheme_rejected_before_charging(self):
  self.ready();before=p.credit_balance(self.owner)['remaining']
  with self.assertRaises(p.UserError):self.make('same',referenceId='ref',schemeId='stale-scheme')
  self.assertEqual(p.credit_balance(self.owner)['remaining'],before)
 def test_seventh_upload_and_product_references_are_used(self):
  self.ready();profile=p.read_profile(self.owner);profile['photos']=[p.store_asset(self.owner,self.img) for _ in range(7)];profile['accessoryPolicy']={'required':['项链','手串'],'excluded':['手表','戒指']};p.save_profile(self.owner,profile)
  j=self.make('same',referenceId='ref');self.assertEqual(len(j['accessorySourcePhotos']),7)
  details={'accessories':['银色方形吊坠项链','黑色珠子手串','手表','戒指'],'accessoryImageIndices':[5,6]}
  with patch.object(p,'reason',side_effect=[details,{'style':'咖啡馆自然光'}]) as reasoning,patch.object(p,'submit_image',side_effect=['a','b']) as submit,patch.object(p,'api',return_value={'status':'succeeded','results':[{'url':'https://example.com/out.jpg'}]}),patch.object(p,'remote_image',return_value=self.img),patch.object(p,'accessories_match',return_value=True):p.execute(j['id'])
  done=p.load_job(j['id']);self.assertEqual(done['status'],'succeeded');self.assertEqual(len(reasoning.call_args_list[0].args[1]),7);self.assertEqual(done['accessoryRefs'],profile['photos'][5:7])
  images=submit.call_args.args[1];self.assertEqual(len(images),5);self.assertEqual(images[2:4],[p.data_uri(self.owner,u) for u in profile['photos'][5:7]])
  self.assertEqual(done['accessories'],details['accessories'][:2]);self.assertIn('禁止佩戴手表',submit.call_args.args[0]);self.assertIn('禁止佩戴戒指',submit.call_args.args[0])
 def test_wrong_accessories_refund_without_overwriting_views(self):
  self.ready();profile=p.read_profile(self.owner);profile['accessoryPolicy']={'required':['项链','手串'],'excluded':['手表','戒指']};p.save_profile(self.owner,profile);j=self.make('view',view='front')
  with patch.object(p,'reason',return_value={'description':'短发','accessories':['项链','手串']}),patch.object(p,'submit_image',return_value='one'),patch.object(p,'api',return_value={'status':'succeeded','results':[{'url':'https://example.com/out.jpg'}]}),patch.object(p,'remote_image',return_value=self.img),patch.object(p,'accessories_match',return_value=False):p.execute(j['id'])
  self.assertEqual(p.load_job(j['id'])['status'],'failed');self.assertEqual(p.read_profile(self.owner),profile);self.assertEqual(p.credit_balance(self.owner)['remaining'],10)
 def test_no_necklace_policy_overrides_old_scheme_and_uploaded_accessories(self):
  job={'accessoryPolicy':{'required':['手串'],'excluded':['项链','手表','戒指']}}
  items=p.accessory_rules(job,['银色项链','黑色珠子手串','手表','戒指'])
  self.assertEqual(items,['黑色珠子手串'])
  prompt=p.accessory_prompt(job,items);self.assertIn('禁止佩戴项链',prompt);self.assertIn('禁止佩戴手表',prompt);self.assertIn('禁止佩戴戒指',prompt)

 def test_real_face_selection_is_owned_persisted_and_snapshotted(self):
  self.ready();second=p.store_asset(self.owner,self.img);profile=p.read_profile(self.owner);profile['photos'].append(second);p.save_profile(self.owner,profile)
  p.select_identity_photo(self.owner,second)
  with self.assertRaises(p.UserError):p.select_identity_photo('other',second)
  j=self.make('same',referenceId='ref');self.assertEqual(j['photos'][0],second)
  p.select_identity_photo(self.owner,self.photo);self.assertEqual(p.load_job(j['id'])['photos'][0],second)
