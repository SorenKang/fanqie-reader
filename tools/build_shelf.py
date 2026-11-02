# -*- coding: utf-8 -*-
"""扫描 books 目录，生成网页版书架清单。

做三件事：
  1. 把 .epub 预转成纯文本放进 web/cache/（浏览器端不必再解压）
  2. 统计字数、编码
  3. 写出 web/shelf.json，网页版启动时自动读取

用法：  python tools\\build_shelf.py
"""
from __future__ import annotations

import json
import os
import sys
from urllib.parse import quote

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import booklib  # noqa: E402

BOOKS = os.path.join(ROOT, 'books')
WEB = os.path.join(ROOT, 'web')
CACHE = os.path.join(WEB, 'cache')
SHELF = os.path.join(WEB, 'shelf.json')


def main():
    os.makedirs(BOOKS, exist_ok=True)
    os.makedirs(CACHE, exist_ok=True)

    files = [f for f in os.listdir(BOOKS)
             if f.lower().endswith(('.txt', '.epub', '.md'))]
    files.sort(key=lambda f: os.path.getmtime(os.path.join(BOOKS, f)), reverse=True)

    items = []
    for name in files:
        src = os.path.join(BOOKS, name)
        stem = os.path.splitext(name)[0]
        try:
            if name.lower().endswith('.epub'):
                text = booklib.epub_text(src)
                out = os.path.join(CACHE, stem + '.txt')
                with open(out, 'w', encoding='utf-8', newline='\n') as fh:
                    fh.write(text)
                rel = 'cache/' + quote(stem + '.txt')
            else:
                text = booklib.read_text(src)
                rel = '../books/' + quote(name)
            chars = sum(1 for c in text if c.strip())
            print(f'  ok  {name}  {chars:,} 字')
        except Exception as e:
            print(f'  !!  {name}  {e}')
            continue
        items.append({
            'name': name,
            'path': rel,
            'chars': chars,
            'mtime': int(os.path.getmtime(src)),
        })

    with open(SHELF, 'w', encoding='utf-8') as fh:
        json.dump(items, fh, ensure_ascii=False, indent=1)

    print(f'\n书架已生成：{SHELF}  共 {len(items)} 本')
    if not items:
        print('提示：把 .txt / .epub 放进 books 目录后重跑本脚本')


if __name__ == '__main__':
    main()
