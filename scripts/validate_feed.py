import json
from pathlib import Path
from PIL import Image
root=Path(__file__).resolve().parent.parent
d=json.loads((root/'data/feed.json').read_text());assert len(d['items'])>=12
ids=set();keys=set();channels=set()
for p in d['items']:
 assert p['id'] not in ids and p['imageKey'] not in keys
 ids.add(p['id']);keys.add(p['imageKey']);channels.add(p['channel'])
 assert p['url'].startswith('https://') and p['image'].startswith('images/') and '..' not in p['image']
 with Image.open(root/p['image']) as im:im.verify()
assert channels=={'outfit','photo'}
print('Verified',len(ids),'unique previews in both channels')
