# OOTD · 日常灵感档案

https://ootd.17design.fun

年轻男生穿搭按风格分类，生活摄影按场景分类。浏览器向 `/api/discover` 按需请求下一页；刷新、换一批、滑到底都会继续取新结果。游标持久保存在当前浏览器，不设每日图片配额；实际可用内容受公开来源限制，没有新结果会明确提示，不重复填充。

服务器 `server.py` 使用 Python 标准库查询公开图片搜索索引，筛选可追溯的平台来源，只在有限内存缓存图片地址，绝不下载或保存照片。照片由浏览器从原始 CDN 加载；服务工作线程 `sw.js` 在本机最多缓存 80 张，自动清理旧缓存。收藏、去重记录也在浏览器本地。

无需第三方 API 密钥。当前不是 Ins/小红书官方实时接口，无可验证点赞排序。来源检索可能被限流或返回空页，年轻化、风格和场景采用关键词筛选，不能保证每张图都符合审美。

本地运行 `python3 server.py`，访问 http://127.0.0.1:8794 。测试 `node --test tests/feed.test.mjs` 与 `python3 -m unittest discover -s tests -p test_server.py`。

部署由本仓库 GitHub Actions 执行。Nginx 只为独立的 ootd.17design.fun 站点添加 /api/ 转发，systemd 服务 ootd-feed 监听 127.0.0.1:8794。不改其他站点。无定时采图任务。
