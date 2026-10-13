#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""test 子命令：用指定网站检测库中的全部代理，可用的保留并更新，不可用的删除。"""

import argparse
import sys
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import db, util

CONF = {}


def _check(item):
    proto, host, port = item
    latency = util.check_proxy(
        proto, host, port, test_url=CONF['url'], timeout=CONF['timeout'],
    )
    return proto, host, port, latency


def test_handle(args):
    CONF.update(url=args.url, timeout=args.timeout)
    with db.get_session(args.db) as sess:
        proxies = [(p.proto, p.host, p.port) for p in db.all_proxies(sess)]

    total = len(proxies)
    print(f'库中共 {total} 个代理，开始检测（{args.url}）')
    if total == 0:
        return

    lat = {}
    with ThreadPoolExecutor(max_workers=args.threads) as pool:
        futs = [pool.submit(_check, it) for it in proxies]
        for fut in as_completed(futs):
            proto, host, port, latency = fut.result()
            lat[(proto, host, port)] = latency

    n_ok = n_bad = 0
    with db.get_session(args.db) as sess:
        for p in db.all_proxies(sess):
            latency = lat.get((p.proto, p.host, p.port))
            if latency is not None:
                n_ok += 1
                p.latency = latency
                p.last_ok = datetime.now()
                print(f'[保留] {p.url()} 耗时 {latency:.2f}s')
            else:
                n_bad += 1
                if args.keep_bad:
                    print(f'[失效][保留] {p.url()}')
                else:
                    db.delete_proxy(sess, p)
                    print(f'[删除] {p.url()}')
    print(f'检测完成，保留 {n_ok} 个，删除 {n_bad} 个')


def reg_subparser(subparsers):
    parser = subparsers.add_parser(
        'test', help='检测库中代理，能用的保留、不能用的删除',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description='''示例：
  BookerProxyTool test
  BookerProxyTool test -u https://www.google.com -t 200''',
    )
    parser.add_argument('-u', '--url', default=util.DEFAULT_TEST_URL,
                        help='检测网站，默认百度')
    parser.add_argument('-t', '--threads', type=int, default=100,
                        help='并发线程数，默认 100')
    parser.add_argument('--timeout', type=float, default=6,
                        help='单个请求超时（秒），默认 6')
    parser.add_argument('--keep-bad', action='store_true',
                        help='保留失效代理（默认删除）')
    parser.add_argument('--db', default=db.DEFAULT_DB, help='数据库文件路径')
    parser.set_defaults(func=test_handle)
