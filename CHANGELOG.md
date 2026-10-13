# 变更日志

## 2026.10.13.0

* 首个版本：实现 `scan`、`crawl`、`forward`、`test`、`click` 五个子命令
* `scan`：扫描 IP 段 × 端口组合，检测可用代理入库
* `crawl`：用 requests/camoufox 抓取页面，按正则提取代理入库
* `forward`：Flask + CONNECT 隧道的本地代理服务，随机转发到库中代理
* `test`：检测库中代理，成功保留并更新延迟，失败删除
* `click`：用库中所有代理访问指定网站若干次
* 基于 SQLite + SQLAlchemy 的代理库