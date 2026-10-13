#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""数据库会话与常用增删查操作。"""

import os
from os import path
from contextlib import contextmanager

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from .model import Base, Proxy

# 默认数据库文件（sqlite）位于当前工作目录。
DEFAULT_DB = path.join(os.getcwd(), 'proxy.db')
_engine = None
_Session = None


def init_db(dbpath=DEFAULT_DB):
    """初始化引擎并建表，返回 sessionmaker。"""
    global _engine, _Session
    _engine = create_engine(f'sqlite:///{dbpath}', future=True)
    Base.metadata.create_all(_engine)
    _Session = sessionmaker(bind=_engine, future=True)
    return _Session


@contextmanager
def get_session(dbpath=DEFAULT_DB):
    """上下文管理器，进入时打开会话，退出时提交（异常则回滚）。"""
    if _Session is None:
        init_db(dbpath)
    sess = _Session()
    try:
        yield sess
        sess.commit()
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()


def add_proxy(sess, proto, host, port, **kw):
    """插入一个代理，已存在则更新其附加字段并返回，否则新建。

    返回 (proxy, created)：created 为 True 表示新建，False 表示更新。
    """
    p = sess.execute(
        select(Proxy).where(
            Proxy.proto == proto, Proxy.host == host, Proxy.port == port
        )
    ).scalar_one_or_none()
    if p is not None:
        for k, v in kw.items():
            if hasattr(p, k):
                setattr(p, k, v)
        return p, False
    p = Proxy(proto=proto, host=host, port=port, **kw)
    sess.add(p)
    return p, True


def all_proxies(sess):
    "取出全部代理。"
    return sess.execute(select(Proxy)).scalars().all()


def count_proxies(sess):
    "统计代理数量。"
    return sess.query(Proxy).count()


def delete_proxy(sess, p):
    "删除一个代理。"
    sess.delete(p)


def delete_proxies(sess, ps):
    "批量删除代理。"
    for p in ps:
        sess.delete(p)
