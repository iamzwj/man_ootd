import html,json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import server
class DiscoveryTests(unittest.TestCase):
 def raw(self,title,image='https://i.pinimg.com/originals/ab/cd/ef/abcdef1234567890abcdef1234567890.jpg',page='https://www.pinterest.com/pin/123/'):
  return '<a m="'+html.escape(json.dumps({'t':title,'murl':image,'purl':page}),quote=True)+'">'
 def test_cursor_advances_real_query_or_page(self):
  for category in ['全部','韩系休闲']:
   jobs=[tuple(server.plan('outfit',category,c)) for c in range(100)]
   self.assertEqual(len(set(jobs)),100)
 def test_rejects_product_unknown_sites_and_ai(self):
  raw=self.raw('Korean men casual outfit')+self.raw('Korean woman outfit')+self.raw('AI generated men outfit')+self.raw('men casual outfit',page='https://example.com/x')
  self.assertEqual(len(server.parse_images(raw,'outfit','韩系休闲')),1)
 def test_metadata_only_and_cross_size_dedup(self):
  url='https://i.pinimg.com/originals/ab/cd/ef/abcdef1234567890abcdef1234567890.jpg'
  self.assertEqual(server.identity(url),server.identity(url.replace('originals','736x')))
  rows=server.parse_images(self.raw('men casual outfit')*2,'outfit','韩系休闲')
  self.assertEqual(len(rows),1);self.assertTrue(rows[0]['image'].startswith('https://'));self.assertNotIn('images/',rows[0]['image'])
if __name__=='__main__':unittest.main()
