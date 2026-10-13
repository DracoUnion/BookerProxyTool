#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""click 子命令：用库中的每个代理访问指定网站若干次。"""

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import db, util

CONF = {}


def _visit(task):
    proto, host, port, i = task
    latency = util.check_proxy(
        proto, host, port, test_url=CONF['url'], timeout=CONF['timeout'],
    )
    return proto, host, port, i, latency


def click_handle(args):
    CONF.update(url=args.url, timeout=args.timeout)
    with db.get_session(args.db) as sess:
        proxies = [(p.proto, p.host, p.port) for p in db.all_proxies(sess)]

    total = len(proxies) * args.times
    print(f'库中共 {len(proxies)} 个代理，每个访问 {args.times} 次，'
          f'共 {total} 次')
    if total == 0:
        return

    n_ok = 0
    with ThreadPoolExecutor(max_workers=args.threads) as pool:
        futs = [
            pool.submit(_visit, (proto, host, port, i))
            for proto, host, port in proxies
            for i in range(args.times)
        ]
        for fut in as_completed(futs):
            proto, host, port, i, latency = fut.result()
            if latency is not None:
                n_ok += 1
                print(f'[成功] {proto}://{host}:{port} 第 {i + 1} 次 '
                      f'耗时 {latency:.2f}s')
            else:
                print(f'[失败] {proto}://{host}:{port} 第 {i + 1} 次',
                      file=sys.stderr)
    print(f'访问完成，成功 {n_ok}/{total}')


def reg_subparser(subparsers):
    parser = subparsers.add_parser(
        'click', help='用库中所有代理访问指定网站若干次',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description='''示例：
  BookerProxyTool click https://www.baidu.com -n 3
  BookerProxyTool click https://www.google.com -n 1 -t 200''',
    )
    parser.add_argument('url', nargs='?', default=util.DEFAULT_TEST_URL,
                        help='要访问的网站，默认百度')
    parser.add_argument('-n', '--times', type=int, default=1,
                        help='每个代理访问次数，默认 1')
    parser.add_argument('-t', '--threads', type=int, default=100,
                        help='并发线程数，默认 100')
    parser.add_argument('--timeout', type=float, default=6,
                        help='单个请求超时（秒），默认 6')
    parser.add_argument('--db', default=db.DEFAULT_DB, help='数据库文件路径')
    parser.set_defaults(func=click_handle)
