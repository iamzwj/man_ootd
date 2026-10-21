# OOTD · 日常灵感档案

线上地址：https://ootd.17design.fun

两个独立频道：年轻男生穿搭（按风格）、生活氛围摄影（按拍摄场景）。瀑布流按批追加，不重新排列已经显示的照片；收藏、浏览记录、不感兴趣保存在浏览器。图片预览由本站提供，原帖保留来源链接。

## 本地运行

`python3 -m http.server 8873`，访问 `http://127.0.0.1:8873`。

`node --test tests/feed.test.mjs` 检查分类、去重、未看过内容优先及 URL 校验。

## 图片更新

`.github/workflows/deploy-tencent.yml` 使用现有服务器密钥部署到独立 OOTD 目录。每天北京时间 07:20 由 GitHub Actions 尝试补充公开可检索内容，也可手动触发 workflow_dispatch。GitHub 调度可能延迟。

采集脚本：`python scripts/collect.py --discover --previous-url https://ootd.17design.fun`。依赖 Pillow、requests。通过公开搜索索引发现 Pinterest 等来源的图片，验证、压缩并缓存预览，以源图片标识和感知哈希去重。失败保留已有内容，不虚构平台点赞和发布时间。每日不保证有新增；搜索索引和来源站点可用性会影响数量，关键词分类不等于人工审核。

`data/excluded.json` 为人工排除列表；`data/corrections.json` 为分类修正，后续采集会继续遵守。`seed-research.json` 保留首批来源证据；`data/feed.json` 是网站实际加载的图片库。

## 部署隔离

发布只更新 `/var/www/ootd/releases/` 及 `/var/www/ootd/public`，不修改其他网站的 Nginx 或服务。先验证数据、图像和代码，再原子切换软链接；本机健康检查失败会回滚。最后验证公网 OOTD 与 D-Gen 健康状态。
