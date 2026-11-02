# -*- coding: utf-8 -*-
"""番茄书源客户端。

后端是开源项目 zhongbai2333/Tomato-Novel-Downloader（Rust，MIT），
以 `--server` 起一个本地 Web UI + HTTP API（默认 127.0.0.1:18423）。
这里只做三件事：托管这个进程、封装它的 API、把下载结果落进 books/。

对外接口：
    src = TomatoSource()
    src.start()                  # 确保后端在跑（不在就拉起来）
    src.search('三体')            # -> [{title, author, book_id}, ...]
    src.download(book_id)        # 建下载任务
    src.jobs()                   # 查任务进度
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
VENDOR = os.path.join(ROOT, 'vendor')
EXE = os.path.join(VENDOR, 'tomato-rust.exe')
DATA = os.path.join(VENDOR, 'data')
BOOKS = os.path.join(ROOT, 'books')
PORT = 18423

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008


class SourceError(RuntimeError):
    pass


class TomatoSource:
    def __init__(self, port: int = PORT):
        self.port = port
        self.base = f'http://127.0.0.1:{port}'
        # 本地回环请求绕开系统代理，否则会被 Clash 之类拦下来
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    # ------------------------------------------------------------ HTTP
    def _call(self, path: str, method: str = 'GET', body=None, timeout: float = 25):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            self.base + path, data=data, method=method,
            headers={'content-type': 'application/json'})
        with self._opener.open(req, timeout=timeout) as r:
            raw = r.read().decode('utf-8', 'replace')
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {'raw': raw}

    def is_running(self, timeout: float = 1.5) -> bool:
        try:
            self._call('/api/status', timeout=timeout)
            return True
        except Exception:
            return False

    def start(self, wait: float = 30) -> bool:
        """后端没在跑就拉起来。成功返回 True。"""
        if self.is_running():
            return True
        if not os.path.isfile(EXE):
            raise SourceError(f'缺少书源程序：{EXE}')
        os.makedirs(DATA, exist_ok=True)
        flags = CREATE_NO_WINDOW | DETACHED_PROCESS
        try:
            subprocess.Popen(
                [EXE, '--server', '--data-dir', DATA],
                cwd=VENDOR, close_fds=True, creationflags=flags,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL)
        except OSError as e:
            raise SourceError(f'拉起书源失败：{e}') from e

        t0 = time.time()
        while time.time() - t0 < wait:
            if self.is_running():
                return True
            time.sleep(0.6)
        return False

    # ------------------------------------------------------------ 业务
    def search(self, keyword: str):
        d = self._call('/api/search?q=' + urllib.parse.quote(keyword), timeout=45)
        return d.get('items') or []

    def preview(self, book_id):
        return self._call('/api/preview/' + urllib.parse.quote(str(book_id)), timeout=45)

    def download(self, book_id, start=None, end=None):
        body = {'book_id': str(book_id)}
        if start and end:
            body['range_start'] = int(start)
            body['range_end'] = int(end)
        return self._call('/api/jobs', 'POST', body)

    def jobs(self):
        return self._call('/api/jobs').get('items') or []

    def library(self):
        return self._call('/api/library')

    def web_url(self) -> str:
        return self.base

    # ------------------------------------------------------------ 本地
    def newest_book(self, after: float = 0.0):
        """books 目录里最新的一本（用于下载完成后自动打开）。"""
        if not os.path.isdir(BOOKS):
            return None
        files = [os.path.join(BOOKS, n) for n in os.listdir(BOOKS)
                 if n.lower().endswith(('.txt', '.epub'))]
        if not files:
            return None
        best = max(files, key=os.path.getmtime)
        return best if os.path.getmtime(best) >= after else None


if __name__ == '__main__':
    s = TomatoSource()
    print('running:', s.is_running())
    print('start  :', s.start())
    for it in s.search('三体')[:5]:
        print('  ', it.get('title'), '|', it.get('author'), '|', it.get('book_id'))
