#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""scan 子命令：扫描 IP 段 × 端口 的全部组合，检测可用的代理服务器并入库。"""

import argparse
import sys
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import db, util

# 运行期配置（由 scan_handle 填充），供线程池中的 worker 读取。
CONF = {}


def _worker(host, port):
    latency = util.check_proxy(
        CONF['proto'], host, port,
        test_url=CONF['url'], timeout=CONF['timeout'],
    )
    return host, port, latency


def scan_handle(args):
    CONF.update(
        proto=args.proto, url=args.url, timeout=args.timeout,
    )
    ports = util.parse_ports(args.ports)
    hosts = util.remove_dup(
        h for seg in args.ip_segs for h in util.iter_hosts(seg)
    )
    total = len(hosts) * len(ports)
    print(f'扫描 {len(hosts)} 个主机 × {len(ports)} 个端口 = {total} 个组合')
    if total == 0:
        return

    n_ok = n_done = 0
    with db.get_session(args.db) as sess, \
            ThreadPoolExecutor(max_workers=args.threads) as pool:
        futs = {
            pool.submit(_worker, host, port)
            for host in hosts for port in ports
        }
        for fut in as_completed(futs):
            n_done += 1
            try:
                host, port, latency = fut.result()
            except Exception as e:
                print(f'[错误] {e}', file=sys.stderr)
                continue
            if latency is not None:
                n_ok += 1
                p, created = db.add_proxy(
                    sess, args.proto, host, port,
                    source='scan', latency=latency, last_ok=datetime.now(),
                )
                print(f"[{'新增' if created else '更新'}] "
                      f'{host}:{port} 耗时 {latency:.2f}s')
            if n_done % 500 == 0 or n_done == total:
                print(f'进度 {n_done}/{total}，可用 {n_ok}', file=sys.stderr)
    print(f'扫描完成，共 {total} 个组合，可用 {n_ok} 个')


def reg_subparser(subparsers):
    parser = subparsers.add_parser(
        'scan', help='扫描 IP 段 × 端口，检测可用代理并入库',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description='''示例：
  BookerProxyTool scan 192.168.1.0/24 -p 8080,3128
  BookerProxyTool scan 10.0.0.1-10.0.0.20 -p 80,443,8000-8010
  BookerProxyTool scan 192.168.1.* -p 1080 --proto socks5''',
    )
    parser.add_argument('ip_segs', nargs='+',
                        help='IP 段，支持单个 IP、CIDR、a-b 区间、* 通配')
    parser.add_argument('-p', '--ports',
                        default='8080,3128,1080,8888,108,8000',
                        help='端口列表，逗号分隔，支持 a-b 区间')
    parser.add_argument('--proto', default='http', choices=util.PROTOCOLS,
                        help='代理协议，默认 http')
    parser.add_argument('-u', '--url', default=util.DEFAULT_TEST_URL,
                        help='检测网站，默认百度')
    parser.add_argument('-t', '--threads', type=int, default=100,
                        help='并发线程数，默认 100')
    parser.add_argument('--timeout', type=float, default=6,
                        help='单个请求超时（秒），默认 6')
    parser.add_argument('--db', default=db.DEFAULT_DB, help='数据库文件路径')
    parser.set_defaults(func=scan_handle)
