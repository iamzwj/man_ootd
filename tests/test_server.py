import html,json,sys,unittest, tempfile, socket
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
   self.assertIn('page=1',read.call_args[0][0])
   self.assertIn('query=',read.call_args[0][0])
 def test_visitor_page_is_not_a_successful_source(self):
  with patch.object(server,'read_public',return_value=b'<html>visitor login</html>'):
   self.assertEqual(server.dewu('outfit','全部',0),([],False))
 def test_dewu_does_not_fake_pagination(self):
  with patch.object(server,'read_public') as read:
   self.assertEqual(server.dewu('outfit','全部',len(server.DEWU_TOPICS)),([],True))
   read.assert_not_called()
class PhotographyTests(unittest.TestCase):
 def setUp(self):
  server.CACHE.clear();server.ACTIVE_SEARCHES.clear()
 def test_outfit_is_no_longer_a_supported_channel(self):
  with self.assertRaises(ValueError):server.discover('outfit','全部',0)
 def test_public_url_rejects_local_credentials_and_ports(self):
  for url in ['https://127.0.0.1/a','https://[::1]/a','https://169.254.169.254/a','https://user:pass@example.com/a','https://example.com:8080/a','https://foo.internal/a','http://example.com/a']:
   self.assertFalse(server.public_url(url),url)
  with patch.object(socket,'getaddrinfo',return_value=[(2,1,6,'',('10.0.0.1',443))]):
   self.assertFalse(server.public_url('https://example.com/a',resolve=True))
 def test_so_keeps_real_source_and_image_not_search_thumbnail(self):
  row={'title':'男生电影感摄影','link':'http://www.douyin.com/note/123','img':'https://images.example.com/photo.jpg','width':'800','height':'1200','thumb':'https://thumb.example.com/small.jpg'}
  rows=server.parse_so({'list':[row]},'电影人像');self.assertEqual(rows[0]['source'],'抖音');self.assertEqual(rows[0]['image'],row['img']);self.assertNotIn('ranking',rows[0]);self.assertEqual(rows[0]['url'],'https://www.douyin.com/note/123')
 def test_real_search_page_and_variant_both_advance(self):
  plans=[server.photo_plan('电影人像',i) for i in range(12)]
  self.assertEqual(len(set(plans)),12);self.assertEqual(plans[4][2],2)
 def test_failed_live_sources_still_return_verified_catalog(self):
  row={'id':'sample','category':'电影人像','channel':'photo','visualChecked':True}
  with patch.object(server,'catalog_rows',return_value=[row]),patch.object(server,'remember_photos'),patch.object(server,'bing_photos',return_value=([],False)),patch.object(server,'flickr_photos',return_value=([],False)),patch.object(server,'so_photos',return_value=([],False)):
   result=server.discover('photo','电影人像',0)
   self.assertTrue(result['sourceAvailable']);self.assertEqual(result['items'],[row])
 def test_content_fingerprint_deduplicates_different_image_addresses(self):
  rows=[{'id':'one','image':'https://a.example.com/1.jpg'},{'id':'two','image':'https://b.example.com/2.jpg'}]
  with patch.object(server.visual_filter,'accept',return_value=True),patch.object(server.visual_filter,'metadata',return_value={'fingerprint':'abcdef','width':800,'height':1200}):
   result=server.screen_photography(rows)
   self.assertEqual(len({p['id'] for p in result}),1)
 def test_only_current_editorial_approval_is_published(self):
  approved={'id':'approved','category':'电影人像','visualChecked':True,'reviewed':True,'aestheticVersion':server.REVIEW_POLICY}
  pending={**approved,'id':'pending','reviewed':False}
  old={**approved,'id':'old','aestheticVersion':'old-policy'}
  with patch.object(Path,'read_text',return_value=json.dumps([approved,pending,old])),patch.object(server,'LIVE_CATALOG',{}):
   self.assertEqual([p['id'] for p in server.catalog_rows('全部')],['approved'])
 def test_unreviewed_search_result_cannot_enter_live_response(self):
  pending={'id':'pending','category':'电影人像','visualChecked':True}
  with patch.object(server,'catalog_rows',return_value=[]),patch.object(server,'remember_photos'),patch.object(server,'bing_photos',return_value=([pending],True)),patch.object(server,'flickr_photos',return_value=([],False)),patch.object(server,'so_photos',return_value=([],False)):
   result=server.discover('photo','电影人像',0)
   self.assertEqual(result['items'],[]);self.assertFalse(result['hasMore']);self.assertEqual(result['nextCursor'],0)
 def test_catalog_pages_have_no_repetition(self):
  rows=[{'id':str(i),'visualChecked':True,'category':'电影人像'} for i in range(100)]
  with patch.object(server,'catalog_rows',return_value=rows):
   ids=[p['id'] for c in range(5) for p in server.seed_photos('全部',c)]
   self.assertEqual(len(ids),100);self.assertEqual(len(set(ids)),100)

if __name__=='__main__':unittest.main()
