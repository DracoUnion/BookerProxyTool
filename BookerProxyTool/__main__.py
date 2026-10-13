#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse

from . import __version__
from . import scan, crawl, forward, test, click


def main():
    parser = argparse.ArgumentParser(
        prog='BookerProxyTool', description='iBooker 代理工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('-v', '--version', action='version',
                        version=f'BookerProxyTool version: {__version__}')
    parser.set_defaults(func=lambda x: parser.print_help())
    subparsers = parser.add_subparsers()

    scan.reg_subparser(subparsers)
    crawl.reg_subparser(subparsers)
    forward.reg_subparser(subparsers)
    test.reg_subparser(subparsers)
    click.reg_subparser(subparsers)

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
