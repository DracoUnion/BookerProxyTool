#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""forward 子命令：在本地开启隧道代理服务，随机转发到库中的代理。

基于 Flask（Werkzeug）实现：
  - HTTP 请求：由 Flask 视图用 requests 经上游代理转发；
  - HTTPS 请求（CONNECT 方法）：在 WSGI 请求处理器中建立原始 TCP 隧道，
    直接连到上游代理，再把客户端数据双向透传。

上游代理从数据库中随机抽取，可用 --refresh 控制刷新间隔。
"""

import argparse
import ipaddress
import random
import select
import socket
import struct
import threading
import time

import requests
from flask import Flask, Response, request
from werkzeug.serving import WSGIRequestHandler, make_server

from . import db, util

# 转发时不应透传的逐跳首部。
HOP_BY_HOP = {
    'connection', 'keep-alive', 'proxy-authenticate',
    'proxy-authorization', 'proxy-connection', 'te',
    'trailers', 'transfer-encoding', 'upgrade',
}

STATUS_PATH = '/__proxytool__/status'

CONF = {}
_pool = []
_pool_time = 0.0
_pool_lock = threading.Lock()


# ---------------------------------------------------------------- 代理池 ----

def get_pool():
    "返回当前代理池（(proto, host, port) 列表），按 TTL 从数据库刷新。"
    global _pool, _pool_time
    with _pool_lock:
        if _pool and time.time() - _pool_time < CONF['refresh']:
            return _pool
        with db.get_session(CONF['db']) as sess:
            _pool = [(p.proto, p.host, p.port) for p in db.all_proxies(sess)]
        _pool_time = time.time()
        return _pool


def pick_proxy():
    "随机抽取一个上游代理，池为空返回 None。"
    pool = get_pool()
    return random.choice(pool) if pool else None


# ----------------------------------------------------------- HTTP 转发 ----

def build_app():
    app = Flask('BookerProxyTool')

    @app.route(STATUS_PATH)
    def status():
        pool = get_pool()
        return {'count': len(pool), 'proxies': pool[:50]}

    @app.route('/', defaults={'path': ''}, methods=[
        'GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS'])
    @app.route('/<path:path>', methods=[
        'GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS'])
    def proxy(path):
        upstream = pick_proxy()
        if upstream is None:
            return '代理池为空', 502
        # Flask 的 request.url 对普通代理请求即是完整目标 URL。
        headers = {
            k: v for k, v in request.headers.items()
            if k.lower() not in HOP_BY_HOP and k.lower() != 'host'
        }
        try:
            resp = requests.request(
                method=request.method, url=request.url, headers=headers,
                data=request.get_data(),
                proxies=util.proxy_dict(*upstream),
                timeout=CONF['timeout'], allow_redirects=False,
            )
        except Exception as e:
            return f'转发失败：{e}', 502
        # 去掉逐跳首部，并交由 Werkzeug 重新计算长度/编码。
        resp_headers = [
            (k, v) for k, v in resp.raw.headers.items()
            if k.lower() not in HOP_BY_HOP
            and k.lower() not in ('content-encoding', 'content-length')
        ]
        resp_headers.append(('Connection', 'close'))
        return Response(resp.content, resp.status_code, resp_headers)

    return app


# ----------------------------------------------------------- CONNECT 隧道 ----

def _connect_http_proxy(uhost, uport, host, port, timeout):
    "经 HTTP 代理建立到 host:port 的 CONNECT 隧道，返回已连接的 socket。"
    sock = socket.create_connection((uhost, uport), timeout=timeout)
    sock.sendall(
        f'CONNECT {host}:{port} HTTP/1.1\r\n'
        f'Host: {host}:{port}\r\n\r\n'.encode()
    )
    # 读取响应头，直到空行。
    buf = b''
    while b'\r\n\r\n' not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            sock.close()
            raise OSError('上游代理提前关闭连接')
        buf += chunk
    status_line = buf.split(b'\r\n', 1)[0]
    if b' 200' not in status_line:
        sock.close()
        raise OSError(f'上游代理拒绝 CONNECT：{status_line!r}')
    return sock


def _socks_addr(host):
    "构造 SOCKS 目标地址段：IP 用 ATYP=1，域名用 ATYP=3。"
    try:
        ip = ipaddress.ip_address(host)
        return b'\x01' + ip.packed
    except ValueError:
        hb = host.encode()
        return b'\x03' + bytes([len(hb)]) + hb


def _connect_socks(proto, uhost, uport, host, port, timeout):
    "经 SOCKS4/SOCKS5 代理建立到 host:port 的连接。"
    sock = socket.create_connection((uhost, uport), timeout=timeout)
    if proto.startswith('socks5'):
        # 握手：声明无需认证。
        sock.sendall(b'\x05\x01\x00')
        if sock.recv(2) != b'\x05\x00':
            sock.close()
            raise OSError('SOCKS5 握手失败')
        # CONNECT 请求。
        sock.sendall(b'\x05\x01\x00' + _socks_addr(host)
                     + struct.pack('!H', port))
        head = sock.recv(4)
        if len(head) < 4 or head[1] != 0:
            sock.close()
            raise OSError(f'SOCKS5 连接失败，rep={head[1:2]!r}')
        # 消费绑定地址（ATYP 决定长度）。
        wrap = head[3]
        if wrap == 1:
            sock.recv(4)
        elif wrap == 4:
            sock.recv(16)
        elif wrap == 3:
            n = sock.recv(1)[0]
            sock.recv(n)
        sock.recv(2)
    else:
        addr = _socks_addr(host)
        if addr[0] != 1:
            sock.close()
            raise OSError('SOCKS4 仅支持 IPv4 目标')
        sock.sendall(b'\x04\x01' + struct.pack('!H', port) + addr[1:] + b'\x00')
        rep = sock.recv(8)
        if len(rep) < 2 or rep[1] != 0x5a:
            sock.close()
            raise OSError(f'SOCKS4 连接失败，rep={rep[1:2]!r}')
    return sock


def _pump(a, b):
    "在两个 socket 之间双向透传数据，任一方向关闭即结束。"
    try:
        while True:
            r, _, _ = select.select([a, b], [], [], 60)
            if not r:
                continue
            for s in r:
                other = b if s is a else a
                try:
                    data = s.recv(65536)
                except OSError:
                    return
                if not data:
                    return
                try:
                    other.sendall(data)
                except OSError:
                    return
    except OSError:
        return


class ProxyRequestHandler(WSGIRequestHandler):
    "扩展 Werkzeug 的请求处理器：CONNECT 走原始 TCP 隧道，其余走 Flask。"

    def do_CONNECT(self):
        self.close_connection = True
        host, _, port = self.path.partition(':')
        try:
            port = int(port or 443)
        except ValueError:
            self.send_error(400, 'Bad Request')
            return
        upstream = pick_proxy()
        if upstream is None:
            self.send_error(502, 'Proxy pool is empty')
            return
        proto, uhost, uport = upstream
        try:
            if proto.startswith('socks'):
                local = _connect_socks(proto, uhost, uport, host, port,
                                       CONF['timeout'])
            else:
                local = _connect_http_proxy(uhost, uport, host, port,
                                            CONF['timeout'])
        except Exception as e:
            self.send_error(502, f'Bad Gateway: {e}')
            return
        try:
            self.wfile.write(b'HTTP/1.1 200 Connection Established\r\n\r\n')
            self.wfile.flush()
            _pump(self.connection, local)
        finally:
            try:
                local.close()
            except OSError:
                pass


def forward_handle(args):
    CONF.update(db=args.db, timeout=args.timeout, refresh=args.refresh)
    with db.get_session(args.db) as sess:
        n = db.count_proxies(sess)
    print(f'代理库中共 {n} 个代理，监听 {args.host}:{args.port}')
    print(f'HTTP/HTTPS 代理地址：http://{args.host}:{args.port}')
    app = build_app()
    srv = make_server(args.host, args.port, app, threaded=True,
                      request_handler=ProxyRequestHandler)
    print('按 Ctrl+C 停止')
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print('\n已停止')


def reg_subparser(subparsers):
    parser = subparsers.add_parser(
        'forward', help='开启隧道代理服务，随机转发到库中的代理',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description='''示例：
  BookerProxyTool forward
  BookerProxyTool forward -H 0.0.0.0 -p 8899
  curl -x http://127.0.0.1:8899 https://www.baidu.com''',
    )
    parser.add_argument('-H', '--host', default='127.0.0.1',
                        help='监听地址，默认 127.0.0.1')
    parser.add_argument('-p', '--port', type=int, default=8899,
                        help='监听端口，默认 8899')
    parser.add_argument('-t', '--timeout', type=float, default=20,
                        help='上游连接/请求超时（秒），默认 20')
    parser.add_argument('--refresh', type=float, default=10,
                        help='代理池刷新间隔（秒），默认 10')
    parser.add_argument('--db', default=db.DEFAULT_DB, help='数据库文件路径')
    parser.set_defaults(func=forward_handle)
