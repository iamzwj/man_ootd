import html,json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import server
from unittest.mock import patch
class DiscoveryTests(unittest.TestCase):
 def raw(self,title,image='https://i.pinimg.com/originals/ab/cd/ef/abcdef1234567890abcdef1234567890.jpg',page='https://www.pinterest.com/pin/123/'):
  return '<a m="'+html.escape(json.dumps({'t':title,'murl':image,'purl':page}),quote=True)+'">'
 def test_real_men_require_positive_original_post_evidence(self):
  for caption in ['女生街拍穿搭','男生卡通穿搭','男生动漫写真穿搭','男生穿搭','街拍穿搭','男生AI摄影穿搭','男生真人大胡子穿搭']:
   self.assertFalse(server.eligible_person({'msg':caption},'outfit','简约干净'),caption)
  self.assertTrue(server.eligible_person({'msg':'男生日常穿搭 真人街拍'},'outfit','简约干净'))
  self.assertFalse(server.eligible_person({'msg':'男生真人穿搭','album':{'name':'二次元'}},'outfit','简约干净'))
  self.assertTrue(server.eligible_person({'msg':'男生海边胶片摄影'},'photo','海边日落'))
  self.assertFalse(server.eligible_person({'msg':'男生室内摄影'},'photo','海边日落'))
 def test_cursor_advances_real_query_or_page(self):
  for category in ['全部','韩系休闲']:
   jobs=[tuple(server.plan('outfit',category,c)) for c in range(100)]
   self.assertEqual(len(set(jobs)),100)
 def test_scroll_reaches_new_provider_page_without_waiting_all_styles(self):
  self.assertGreater(server.plan('outfit','全部',2)[0][3],server.plan('outfit','全部',0)[0][3])
 def test_rejects_product_unknown_sites_and_ai(self):
  raw=self.raw('Korean men casual outfit')+self.raw('Korean woman outfit')+self.raw('AI generated men outfit')+self.raw('men casual outfit',page='https://example.com/x')
  self.assertEqual(len(server.parse_images(raw,'outfit','韩系休闲')),1)
 def test_metadata_only_and_cross_size_dedup(self):
  url='https://i.pinimg.com/originals/ab/cd/ef/abcdef1234567890abcdef1234567890.jpg'
  self.assertEqual(server.identity(url),server.identity(url.replace('originals','736x')))
  rows=server.parse_images(self.raw('men casual outfit')*2,'outfit','韩系休闲')
  self.assertEqual(len(rows),1);self.assertTrue(rows[0]['image'].startswith('https://'));self.assertNotIn('images/',rows[0]['image'])
class DomesticTests(unittest.TestCase):
 def setUp(self):server.CACHE.clear()
 def test_unknown_metrics_stay_unknown(self):
  self.assertEqual(server.count_value({},'views'),None)
 def test_new_sources_fail_closed_without_model(self):
  with patch.object(server.visual_filter,'ready',return_value=False):
   item=server.domestic_item('https://photo.tuchong.com/1/lr/2.jpg','https://tuchong.com/1/2/','图虫','男生咖啡馆摄影',[],'photo','全部',800,1000,{})
   self.assertIsNone(item)
 def test_domestic_urls_and_category_are_checked(self):
  args=['https://photo.tuchong.com/1/lr/2.jpg','https://tuchong.com/1/2/','图虫','男生咖啡馆摄影',[],'photo','咖啡馆',800,1000,{}]
  with patch.object(server.visual_filter,'ready',return_value=True):
   self.assertEqual(server.domestic_item(*args)['category'],'咖啡馆')
   for image in ['http://photo.tuchong.com/a.jpg','https://photo.tuchong.com.evil.test/a.jpg','https://127.0.0.1/a.jpg']:
    self.assertIsNone(server.domestic_item(image,*args[1:]))
   args[6]='海边日落';self.assertIsNone(server.domestic_item(*args))
 def test_provider_pages_advance_and_visual_rejections_are_removed(self):
  row={'type':'multi-photo','url':'https://tuchong.com/1/2/','title':'男生日常穿搭','tags':[],
   'images':[{'user_id':1,'img_id':2,'width':800,'height':1000}],'views':20000}
  response=json.dumps({'result':'SUCCESS','data':{'post_list':[row]}}).encode()
  with patch.object(server,'read_public',return_value=response) as read,patch.object(server.visual_filter,'ready',return_value=True),patch.object(server.visual_filter,'accept',return_value=False):
   self.assertEqual(server.tuchong('outfit','全部',1),([],True))
   self.assertIn('page=2',read.call_args[0][0])
 def test_visitor_page_is_not_a_successful_source(self):
  with patch.object(server,'read_public',return_value=b'<html>visitor login</html>'):
   self.assertEqual(server.dewu('outfit','全部',0),([],False))
 def test_dewu_does_not_fake_pagination(self):
  with patch.object(server,'read_public') as read:
   self.assertEqual(server.dewu('outfit','全部',len(server.DEWU_TOPICS)),([],True))
   read.assert_not_called()
 def test_failed_source_does_not_hide_working_sources(self):
  with patch.object(server,'duitang',return_value=([],False)),patch.object(server,'tuchong',return_value=([{'id':'x','engagement':{}}],True)),patch.object(server,'dewu',return_value=([],False)):
   result=server.discover('outfit','全部',0)
   self.assertTrue(result['sourceAvailable']);self.assertEqual(result['items'][0]['id'],'x')
   self.assertNotIn('StyleHint',[s['name'] for s in result['sources']])

if __name__=='__main__':unittest.main()
