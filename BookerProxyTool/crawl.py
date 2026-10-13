#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""crawl 子命令：用 requests / camoufox 抓取页面，按正则提取代理，检测后入库。

正则支持命名分组（host、port，可选 proto），也支持位置分组：
    - 第 1 组为 host，第 2 组为 port，第 3 组（可选）为协议。
默认正则匹配形如 `1.2.3.4:8080` 或 `socks5://1.2.3.4:8080` 的文本。
"""

import argparse
import re
import sys
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import db, util

# 默认正则：captures proto(可选)、host、port。
DEFAULT_RE = r'(?:(?P<proto>https?|socks[45]h?)://)?(?P<host>\d{1,3}(?:\.\d{1,3}){3}):(?P<port>\d{1,5})'

CONF = {}


def fetch_requests(url, proxy=None, timeout=20):
    "用 requests 抓取页面。"
    sess = util.make_session()
    proxies = None
    if proxy:
        proxies = util.proxy_dict(*proxy)
    r = sess.get(util.normalize_url(url), proxies=proxies, timeout=timeout)
    r.raise_for_status()
    return r.text


def fetch_camoufox(url, timeout=30000):
    "用 camoufox 无头浏览器抓取页面（可渲染 JS）。"
    from camoufox.sync_api import Camoufox
    with Camoufox(headless=True) as browser:
        page = browser.new_page()
        page.goto(url, timeout=timeout)
        page.wait_for_load_state('networkidle')
        return page.content()


def fetch(url, engine='requests', proxy=None, timeout=20):
    "按引擎抓取页面。"
    if engine == 'camoufox':
        return fetch_camoufox(url, timeout=timeout * 1000)
    return fetch_requests(url, proxy=proxy, timeout=timeout)


def parse_proxies(text, pattern):
    """用正则从文本中提取代理，返回去重后的 (proto, host, port) 列表。

    proto 为空时回退到 --proto 指定的默认协议。
    """
    rx = re.compile(pattern)
    seen, out = set(), []
    for m in rx.finditer(text):
        gd = m.groupdict()
        if 'host' in gd:
            host, port = gd.get('host'), gd.get('port')
            proto = gd.get('proto') or CONF['proto']
        else:
            groups = m.groups()
            host = groups[0] if len(groups) > 0 else None
            port = groups[1] if len(groups) > 1 else None
            proto = (groups[2] if len(groups) > 2 and groups[2]
                     else CONF['proto'])
        if not host or not port:
            continue
        try:
            port = util.parse_port(str(port).strip())
        except ValueError:
            continue
        key = (proto, host.strip(), port)
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _check(item):
    proto, host, port = item
    latency = util.check_proxy(
        proto, host, port, test_url=CONF['url'], timeout=CONF['timeout'],
    )
    return proto, host, port, latency


def crawl_handle(args):
    CONF.update(proto=args.proto, url=args.url, timeout=args.timeout)

    n_page = n_found = n_ok = 0
    all_proxies = {}
    for url in args.urls:
        try:
            html = fetch(url, engine=args.engine,
                         timeout=args.page_timeout)
        except Exception as e:
            print(f'[抓取失败] {url}: {e}', file=sys.stderr)
            continue
        n_page += 1
        proxies = parse_proxies(html, args.regex)
        n_found += len(proxies)
        for proto, host, port in proxies:
            all_proxies.setdefault((proto, host, port), url)
        print(f'[抓取] {url} 提取到 {len(proxies)} 个代理')

    if not all_proxies:
        print('未提取到任何代理')
        return

    print(f'共 {n_page} 个页面，{len(all_proxies)} 个候选代理，开始检测')
    with db.get_session(args.db) as sess, \
            ThreadPoolExecutor(max_workers=args.threads) as pool:
        futs = {pool.submit(_check, it): it for it in all_proxies}
        for fut in as_completed(futs):
            proto, host, port, latency = fut.result()
            if latency is None:
                continue
            n_ok += 1
            p, created = db.add_proxy(
                sess, proto, host, port, source=all_proxies[(proto, host, port)],
                latency=latency, last_ok=datetime.now(),
            )
            print(f"[{'新增' if created else '更新'}] "
                  f'{proto}://{host}:{port} 耗时 {latency:.2f}s')
    print(f'抓取完成，候选 {len(all_proxies)} 个，可用 {n_ok} 个')


def reg_subparser(subparsers):
    parser = subparsers.add_parser(
        'crawl', help='抓取页面上的代理，检测后入库',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description='''示例：
  BookerProxyTool crawl https://example.com/proxies
  BookerProxyTool crawl https://example.com -e camoufox -r "(\\d+\\.\\d+\\.\\d+\\.\\d+):(\\d+)"''',
    )
    parser.add_argument('urls', nargs='+', help='要抓取的网页 URL')
    parser.add_argument('-e', '--engine', default='requests',
                        choices=['requests', 'camoufox'],
                        help='抓取引擎，默认 requests')
    parser.add_argument('-r', '--regex', default=DEFAULT_RE,
                        help='提取代理的正则，支持命名分组 host/port/proto')
    parser.add_argument('--proto', default='http', choices=util.PROTOCOLS,
                        help='正则未给出协议时的默认协议，默认 http')
    parser.add_argument('-u', '--url', default=util.DEFAULT_TEST_URL,
                        help='检测网站，默认百度')
    parser.add_argument('-t', '--threads', type=int, default=50,
                        help='检测并发线程数，默认 50')
    parser.add_argument('--timeout', type=float, default=6,
                        help='单个检测请求超时（秒），默认 6')
    parser.add_argument('--page-timeout', type=float, default=20,
                        help='页面抓取超时（秒），默认 20')
    parser.add_argument('--db', default=db.DEFAULT_DB, help='数据库文件路径')
    parser.set_defaults(func=crawl_handle)
