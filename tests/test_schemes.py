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
