#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""数据库模型。

使用 SQLAlchemy 声明式 ORM 定义代理表。主键为自增 id，
(proto, host, port) 组成唯一约束，保证同一个代理不会重复入库。
"""

from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, Float, DateTime,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Proxy(Base):
    """一条代理记录。

    proto 为协议（http/https/socks4/socks5/socks5h），host:port 为地址，
    latency 为最近一次检测的耗时（秒），last_ok 为最近一次检测成功的时间。
    """

    __tablename__ = 'proxy'

    id = Column(Integer, primary_key=True)
    proto = Column(String(16), nullable=False, default='http')
    host = Column(String(64), nullable=False)
    port = Column(Integer, nullable=False)
    country = Column(String(64))
    anonymity = Column(String(16))
    source = Column(String(255))
    latency = Column(Float)
    last_ok = Column(DateTime)
    created = Column(DateTime, default=datetime.now)

    __table_args__ = (
        UniqueConstraint('proto', 'host', 'port', name='uq_proxy'),
    )

    def url(self):
        """返回 requests/camoufox 可直接使用的代理 URL。"""
        return f'{self.proto}://{self.host}:{self.port}'

    def __repr__(self):
        return f'<Proxy {self.url()}>'
