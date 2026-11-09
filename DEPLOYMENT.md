# 青泡：腾讯云部署

此项目不依赖 ChatGPT Sites。生产运行方式与 `ssc` 相同：腾讯云 Ubuntu、Nginx、systemd 和服务器端 SQLite。

## DNS

在 DNSPod 配置 `www.lsstools01.site` 的 A 记录到腾讯云服务器 `43.135.22.183`，移除该子域名任何旧的 ChatGPT/Cloudflare A 或 CNAME 记录。

## 首次安装（服务器）

1. 将 GitHub 仓库的发布包上传到 `/tmp/qingpao-release` 并解压。
2. 执行：`cd /tmp/qingpao-release && bash deploy/install-cloud.sh`。脚本先加载 HTTP 引导站点，再自动申请 Let’s Encrypt 证书并切换 HTTPS。
4. 验证：`curl https://www.lsstools01.site/api/me`。

数据库与附件都保存在 `/opt/qingpao/data`，发布脚本不会覆盖它们。应用以 `qingpao.service` 运行；排障命令：`sudo systemctl status qingpao nginx`。

## 功能边界

账户密码只保存在服务器端，使用 PBKDF2 哈希；配对码 10 分钟有效；在线状态以最近 75 秒心跳判断；客户端每 4 秒拉取新消息和在线状态。
