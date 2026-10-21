"""Add only an OOTD API location; preserve TLS and all other virtual hosts."""
from pathlib import Path
import re, time
snippet=Path('/etc/nginx/snippets/ootd-api.conf')
snippet.write_text('''location ^~ /api/ {
    proxy_pass http://127.0.0.1:8794;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_read_timeout 25s;
    proxy_buffering off;
}
''')
found=False
for link in Path('/etc/nginx/sites-enabled').iterdir():
 if not link.is_file():continue
 path=link.resolve();text=path.read_text()
 if not re.search(r'server_name\s+ootd\.17design\.fun\s*;',text):continue
 found=True
 if 'include /etc/nginx/snippets/ootd-api.conf;' in text:continue
 updated=re.sub(r'(server_name\s+ootd\.17design\.fun\s*;)',r'\1\n    include /etc/nginx/snippets/ootd-api.conf;',text)
 backup=path.with_name(path.name+'.before-live-'+str(int(time.time())))
 backup.write_text(text);path.write_text(updated)
if not found:raise RuntimeError('Dedicated OOTD virtual host not found; refusing to edit other sites')
