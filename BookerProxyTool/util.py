#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""公共工具：IP 段展开、请求头、代理检测、随机 UA。"""

import itertools
import ipaddress
import random
import re

import requests
from requests.exceptions import RequestException

# 默认检测站点。
DEFAULT_TEST_URL = 'https://www.baidu.com'

UA_LIST = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 '
    '(KHTML, like Gecko) Version/17.0 Safari/605.1.15',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) '
    'Gecko/20100101 Firefox/121.0',
]

# 支持扫描/入库的协议。
PROTOCOLS = ('http', 'https', 'socks4', 'socks5', 'socks5h')


def rand_ua():
    "返回一个随机 UA。"
    return random.choice(UA_LIST)


def normalize_url(url):
    "补全协议前缀，便于 IP 段/网站参数省略 http(s)://。"
    if not url:
        return url
    if not re.match(r'^\w+://', url):
        url = 'http://' + url
    return url


def make_session(n_retries=0):
    "创建一个带随机 UA 的 requests 会话。"
    sess = requests.Session()
    sess.headers.update({'User-Agent': rand_ua()})
    if n_retries > 0:
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        retry = Retry(total=n_retries, backoff_factor=0.3)
        adapter = HTTPAdapter(max_retries=retry)
        sess.mount('http://', adapter)
        sess.mount('https://', adapter)
    return sess


def proxy_dict(proto, host, port):
    "把 proto/host/port 转成 requests 需要的 proxies 字典。"
    return {
        'http': f'{proto}://{host}:{port}',
        'https': f'{proto}://{host}:{port}',
    }


def check_proxy(proto, host, port, test_url=DEFAULT_TEST_URL,
                timeout=6, session=None):
    """检测单个代理是否可用。

    通过该代理访问 test_url，成功返回耗时（秒，float），失败返回 None。
    """
    import time

    sess = session or make_session()
    proxies = proxy_dict(proto, host, port)
    try:
        t0 = time.time()
        r = sess.get(normalize_url(test_url), proxies=proxies,
                     timeout=timeout, allow_redirects=True)
        dt = time.time() - t0
        if r.status_code < 400:
            return dt
    except RequestException:
        pass
    except Exception:
        pass
    return None


def parse_port(s):
    "解析单个端口，非法则抛 ValueError。"
    p = int(s)
    if not 0 < p < 65536:
        raise ValueError(f'非法端口：{s}')
    return p


def parse_ports(spec):
    """解析逗号分隔的端口列表，支持区间，如 '80,443,8000-8010'。"""
    ports = []
    for part in str(spec).split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            a, b = part.split('-', 1)
            a, b = parse_port(a), parse_port(b)
            ports.extend(range(min(a, b), max(a, b) + 1))
        else:
            ports.append(parse_port(part))
    # 去重并保持顺序。
    return list(dict.fromkeys(ports))


def remove_dup(seq):
    "去重并保持顺序。"
    return list(dict.fromkeys(seq))


def iter_hosts(ip_seg):
    """展开一个 IP 段，逐个返回可用的主机地址字符串。

    支持单个 IP、CIDR（10.0.0.0/24）、`a-b` 区间（10.0.0.1-10.0.0.20）
    以及带通配的网段（192.168.1.*）。
    """
    ip_seg = ip_seg.strip()
    if '-' in ip_seg and '*' not in ip_seg and '/' not in ip_seg:
        # a-b 形式的 IP 区间，如 10.0.0.1-10.0.0.20
        a, b = ip_seg.split('-', 1)
        a = ipaddress.ip_address(a.strip())
        b = ipaddress.ip_address(b.strip())
        if int(a) > int(b):
            a, b = b, a
        for i in range(int(a), int(b) + 1):
            yield str(ipaddress.ip_address(i))
    elif '*' in ip_seg:
        parts = [p.split('-') if '-' in p else [p] for p in ip_seg.split('.')]
        pools = []
        for p in parts:
            if len(p) == 2:
                a, b = int(p[0]), int(p[1])
                pools.append(range(min(a, b), max(a, b) + 1))
            elif p[0] == '*':
                pools.append(range(256))
            else:
                pools.append([int(p[0])])
        for combo in itertools.product(*pools):
            yield '.'.join(str(x) for x in combo)
    else:
        if '/' in ip_seg:
            net = ipaddress.ip_network(ip_seg, strict=False)
            for ip in net.hosts():
                yield str(ip)
        else:
            yield str(ipaddress.ip_address(ip_seg))


def iter_addr(ip_segs, ports):
    """展开 IP 段 × 端口的全部组合，逐个 yield (host, port)。

    对 CIDR / 通配网段会把 host 留空（由调用方决定是否扫描全部主机）。
    """
    hosts = []
    for seg in ip_segs:
        hosts.extend(iter_hosts(seg))
    for host in remove_dup(hosts):
        for port in ports:
            yield host, port


def hdl(handler, **kwargs):
    "装饰器：给子命令处理函数挂上元信息，供 __main__ 统一调度。"

    def deco(func):
        func.handler = handler
        func.kwargs = kwargs
        return func
    return deco
