# BookerProxyTool

iBooker/DracoUnion 代理工具

一套面向代理池的命令行工具：扫描网段挖掘代理、抓取页面收集代理、本地开启隧道代理转发，以及对代理库做检测与访问压测。

## 安装

通过 pip（推荐）：

```
pip install BookerProxyTool
```

从源码安装：

```
pip install git+https://github.com/DracoUnion/BookerProxyTool.git
```

Python 版本要求：>= 3.8。

安装后可通过 `BookerProxyTool` 或 `proxy-tool` 两个命令调用（两者等价），也可以使用 `python -m BookerProxyTool`。

### 可选依赖

+   `crawl -e camoufox` 需要 `camoufox` 无头浏览器（`pip install camoufox` 并 `camoufox fetch`）。
+   SOCKS4/SOCKS5 代理需要 `requests[socks]`（已包含在依赖中，对应 `PySocks`）。

## 使用说明

```
BookerProxyTool -h    # 查看帮助
BookerProxyTool -v    # 查看版本
```

代理库默认为当前目录下的 `proxy.db`（SQLite），所有子命令都可用 `--db` 指定其它文件。

### scan：扫描 IP 段挖掘代理

扫描给定 IP 段与端口列表的全部组合，用指定网站逐个检测，能连通的入库。

```
BookerProxyTool scan <ip段...> [-p 端口列表] [--proto 协议] [-u 检测网站] [-t 线程数] [--timeout 秒]
```

| 参数 | 说明 |
| --- | --- |
| `ip_segs` | IP 段，支持单个 IP、CIDR、`a-b` 区间、`*` 通配，可给多个 |
| `-p, --ports` | 端口列表，逗号分隔，支持 `a-b` 区间，默认 `8080,3128,1080,8888,108,8000` |
| `--proto` | 代理协议（http/https/socks4/socks5/socks5h），默认 http |
| `-u, --url` | 检测网站，默认百度 |
| `-t, --threads` | 并发线程数，默认 100 |
| `--timeout` | 单个请求超时（秒），默认 6 |
| `--db` | 数据库文件路径 |

```
BookerProxyTool scan 192.168.1.0/24 -p 8080,3128
BookerProxyTool scan 10.0.0.1-10.0.0.20 -p 80,443,8000-8010
BookerProxyTool scan 192.168.1.* -p 1080 --proto socks5
```

### crawl：抓取页面上的代理

用 requests 或 camoufox 抓取给定网页，按正则提取代理，检测后入库。

```
BookerProxyTool crawl <url...> [-e 引擎] [-r 正则] [--proto 协议] [-u 检测网站] [-t 线程数]
```

| 参数 | 说明 |
| --- | --- |
| `urls` | 要抓取的网页 URL，可给多个 |
| `-e, --engine` | 抓取引擎：`requests`（默认）或 `camoufox`（可渲染 JS） |
| `-r, --regex` | 提取代理的正则，支持命名分组 `host`/`port`/`proto`，也支持位置分组（第 1 组 host、第 2 组 port、第 3 组协议） |
| `--proto` | 正则未给出协议时的默认协议，默认 http |
| `-u, --url` | 检测网站，默认百度 |
| `-t, --threads` | 检测并发线程数，默认 50 |
| `--timeout` | 单个检测请求超时（秒），默认 6 |
| `--page-timeout` | 页面抓取超时（秒），默认 20 |
| `--db` | 数据库文件路径 |

默认正则匹配形如 `1.2.3.4:8080` 或 `socks5://1.2.3.4:8080` 的文本。

```
BookerProxyTool crawl https://example.com/proxies
BookerProxyTool crawl https://example.com -e camoufox \
    -r "(\d+\.\d+\.\d+\.\d+):(\d+)" --proto http
```

### forward：隧道代理服务

在本地开启一个 HTTP/HTTPS 代理服务，收到的请求（含 CONNECT 隧道）会随机转发到库中的某个代理。

```
BookerProxyTool forward [-H 监听地址] [-p 监听端口] [-t 超时] [--refresh 秒] [--db 文件]
```

| 参数 | 说明 |
| --- | --- |
| `-H, --host` | 监听地址，默认 `127.0.0.1` |
| `-p, --port` | 监听端口，默认 `8899` |
| `-t, --timeout` | 上游连接/请求超时（秒），默认 20 |
| `--refresh` | 代理池刷新间隔（秒），默认 10 |
| `--db` | 数据库文件路径 |

```
BookerProxyTool forward
curl -x http://127.0.0.1:8899 https://www.baidu.com
```

访问 `/__proxytool__/status` 可查看当前代理池大小与前若干条代理。

### test：检测并清理代理库

用指定网站检测库中每个代理，成功的保留（并更新延迟与最近成功时间），失败的删除。

```
BookerProxyTool test [-u 检测网站] [-t 线程数] [--timeout 秒] [--keep-bad] [--db 文件]
```

| 参数 | 说明 |
| --- | --- |
| `-u, --url` | 检测网站，默认百度 |
| `-t, --threads` | 并发线程数，默认 100 |
| `--timeout` | 单个请求超时（秒），默认 6 |
| `--keep-bad` | 保留失效代理（默认删除） |

```
BookerProxyTool test
BookerProxyTool test -u https://www.google.com -t 200
```

### click：用所有代理访问网站

用库中的每个代理访问指定网站若干次，用于验证连通性或产生流量。

```
BookerProxyTool click [url] [-n 次数] [-t 线程数] [--timeout 秒] [--db 文件]
```

| 参数 | 说明 |
| --- | --- |
| `url` | 要访问的网站，默认百度 |
| `-n, --times` | 每个代理访问次数，默认 1 |
| `-t, --threads` | 并发线程数，默认 100 |
| `--timeout` | 单个请求超时（秒），默认 6 |

```
BookerProxyTool click https://www.baidu.com -n 3
```

## 代理库

默认使用 SQLite 数据库 `proxy.db`，表结构（`proxy` 表）如下：

| 字段 | 说明 |
| --- | --- |
| `id` | 自增主键 |
| `proto` | 协议（http/https/socks4/socks5/socks5h） |
| `host` / `port` | 代理地址 |
| `country` / `anonymity` | 国家 / 匿名度（预留） |
| `source` | 来源（`scan` 或抓取页面 URL） |
| `latency` | 最近一次检测耗时（秒） |
| `last_ok` | 最近一次检测成功时间 |
| `created` | 入库时间 |

`(proto, host, port)` 唯一，重复入库会更新已有记录。

## 协议

本项目基于 SATA 协议发布。

您有义务为此开源项目点赞，并考虑额外给予作者适当的奖励。

## 赞助我们

![](https://home.apachecn.org/img/about/donate.jpg)

## 另见

+   [ApacheCN 学习资源](https://docs.apachecn.org/)
+   [计算机电子书](http://it-ebooks.flygon.net)
+   [布客新知](http://flygon.net/ixinzhi/)
