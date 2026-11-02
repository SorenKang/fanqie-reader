# -*- coding: utf-8 -*-
"""下载书源后端。

阅读器本身不含任何下载逻辑，搜书/下载交给开源项目
zhongbai2333/Tomato-Novel-Downloader（Rust，MIT）的 `--server` 模式。
本脚本按当前平台从它的 Releases 取对应二进制，落到 vendor/。

    python tools/fetch_source.py            # 下载当前平台最新版
    python tools/fetch_source.py --check    # 只看有没有、什么版本
"""
from __future__ import annotations

import json
import os
import platform
import stat
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
VENDOR = os.path.join(ROOT, 'vendor')
API = 'https://api.github.com/repos/zhongbai2333/Tomato-Novel-Downloader/releases/latest'
FALLBACK_TAG = 'v2.4.16'
FALLBACK_BASE = ('https://github.com/zhongbai2333/Tomato-Novel-Downloader'
                 '/releases/download/' + FALLBACK_TAG + '/')

UA = {'User-Agent': 'fanqie-reader-fetch', 'Accept': 'application/vnd.github+json'}


def is_windows() -> bool:
    return platform.system() == 'Windows'


def exe_path() -> str:
    return os.path.join(VENDOR, 'tomato-rust.exe' if is_windows() else 'tomato-rust')


def platform_key() -> str:
    system = platform.system()
    machine = platform.machine().lower()
    arm = machine in ('arm64', 'aarch64')
    if system == 'Windows':
        return 'WinArm64' if arm else 'Win64'
    if system == 'Darwin':
        return 'macOS_arm64' if arm else 'macOS_amd64'
    return 'Linux_arm64' if arm else 'Linux_amd64'


def http_json(url: str):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode('utf-8'))


def download(url: str, dst: str):
    req = urllib.request.Request(url, headers={'User-Agent': 'fanqie-reader-fetch'})
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = dst + '.part'
    with urllib.request.urlopen(req, timeout=120) as r, open(tmp, 'wb') as fh:
        total = int(r.headers.get('content-length') or 0)
        done = 0
        while True:
            chunk = r.read(65536)
            if not chunk:
                break
            fh.write(chunk)
            done += len(chunk)
            if total:
                pct = done * 100 // total
                sys.stdout.write(f'\r  下载中 {pct:3d}%  {done / 1048576:5.1f} / '
                                 f'{total / 1048576:.1f} MB')
                sys.stdout.flush()
    print()
    os.replace(tmp, dst)


def find_asset(release) -> tuple[str, str]:
    key = platform_key()
    for a in release.get('assets', []):
        if key in a['name']:
            return a['name'], a['browser_download_url']
    raise SystemExit(f'这个版本里没有适配 {key} 的包，去 Releases 页面手动挑一个：'
                     f'{release.get("html_url", "")}')


def main():
    target = exe_path()
    if '--check' in sys.argv:
        print('平台      :', platform_key())
        print('目标文件  :', target)
        print('已安装    :', os.path.isfile(target))
        if os.path.isfile(target):
            print('大小      :', round(os.path.getsize(target) / 1048576, 2), 'MB')
        return

    if os.path.isfile(target):
        print(f'已存在：{target}')
        print('想重装就先删掉它，再跑一次。')
        return

    print('平台      :', platform_key())
    name = url = None
    try:
        release = http_json(API)
        print('上游版本  :', release.get('tag_name'))
        name, url = find_asset(release)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        print(f'查询 Releases 失败（{e}），改用内置地址 {FALLBACK_TAG}')
        guess = {
            'Win64': f'TomatoNovelDownloader-Win64-{FALLBACK_TAG}.exe',
            'WinArm64': f'TomatoNovelDownloader-WinArm64-{FALLBACK_TAG}.exe',
            'Linux_amd64': f'TomatoNovelDownloader-Linux_amd64-{FALLBACK_TAG}',
            'Linux_arm64': f'TomatoNovelDownloader-Linux_arm64-{FALLBACK_TAG}',
            'macOS_amd64': f'TomatoNovelDownloader-macOS_amd64-{FALLBACK_TAG}',
            'macOS_arm64': f'TomatoNovelDownloader-macOS_arm64-{FALLBACK_TAG}',
        }
        name = guess[platform_key()]
        url = FALLBACK_BASE + name

    print('下载      :', name)
    download(url, target)

    if not is_windows():
        mode = os.stat(target).st_mode
        os.chmod(target, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    print('完成      :', target, round(os.path.getsize(target) / 1048576, 2), 'MB')
    print('现在可以启动阅读器，点「搜书」。')


if __name__ == '__main__':
    main()
