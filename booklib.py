# -*- coding: utf-8 -*-
"""文本处理共用库：编码探测 / EPUB 抽取 / 章节切分。仅用标准库。

调用方：
    desktop/reader.py    桌面阅读器
    tools/build_shelf.py 生成网页版书架
"""
from __future__ import annotations

import html as _html
import re
import zipfile
from urllib.parse import unquote

# 章标题特征：第12章 / 第三回 / 卷五 / Chapter 7 / 序章 / 楔子 / 番外 …
CHAPTER_PATTERN = re.compile(
    r'^\s*(?:第[\d零一二三四五六七八九十百千两]{1,12}\s*[章回节卷篇集]'
    r'|Chapter\s*\d{1,4}'
    r'|卷[\d零一二三四五六七八九十百]{1,6}'
    r'|序章|序言|楔子|引子|尾声|后记|番外|终章)'
)

ENCODINGS = ('utf-8-sig', 'utf-8', 'gb18030', 'big5', 'utf-16')


def read_text(path: str) -> str:
    """按常见编码依次尝试解码，失败回退 gb18030。"""
    with open(path, 'rb') as fh:
        raw = fh.read()
    for enc in ENCODINGS:
        try:
            s = raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
        if '\ufffd' not in s:
            return _norm(s)
    return _norm(raw.decode('gb18030', 'replace'))


def _norm(s: str) -> str:
    return s.replace('\r\n', '\n').replace('\r', '\n').replace('\u3000', '\u3000')


def html_to_text(src: str) -> str:
    src = re.sub(r'(?is)<(script|style|svg)\b.*?</\1>', '', src)
    src = re.sub(r'(?i)<br\s*/?>', '\n', src)
    src = re.sub(r'(?i)</(p|div|h[1-6]|li|tr|blockquote|section|article)>', '\n', src)
    src = re.sub(r'(?s)<[^>]+>', '', src)
    src = _html.unescape(src).replace('\u00a0', ' ')
    src = re.sub(r'[ \t]+\n', '\n', src)
    src = re.sub(r'\n{3,}', '\n\n', src)
    return src.strip()


def epub_text(path: str) -> str:
    """按 spine 顺序抽取 EPUB 正文。"""
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        lower = {n.lower(): n for n in names}

        rootpath = None
        cont = lower.get('meta-inf/container.xml')
        if cont:
            m = re.search(r'full-path\s*=\s*"([^"]+)"', z.read(cont).decode('utf-8', 'ignore'))
            if m:
                rootpath = m.group(1)
        if not rootpath:
            rootpath = next((n for n in names if n.lower().endswith('.opf')), None)
        if not rootpath:
            raise RuntimeError('EPUB 缺少 opf 清单')

        opf = z.read(rootpath).decode('utf-8', 'ignore')
        base = rootpath.rsplit('/', 1)[0] + '/' if '/' in rootpath else ''

        items = {}
        for m in re.finditer(r'<item(?=[\s/>])[^>]*>', opf):
            tag = m.group(0)
            i = re.search(r'\bid\s*=\s*"([^"]+)"', tag)
            h = re.search(r'\bhref\s*=\s*"([^"]+)"', tag)
            if i and h:
                items[i.group(1)] = h.group(1)

        order = re.findall(r'<itemref\b[^>]*\bidref\s*=\s*"([^"]+)"', opf) or list(items)

        parts = []
        for ref in order:
            href = items.get(ref)
            if not href:
                continue
            rel = unquote(href.split('#')[0]).lstrip('/')
            target = re.sub(r'/+', '/', base + rel) if base else rel
            real = None
            for n in names:
                if n == target or n.lower() == target.lower():
                    real = n
                    break
            if real is None:
                continue
            try:
                raw = z.read(real).decode('utf-8', 'ignore')
            except Exception:
                continue
            t = html_to_text(raw)
            if t:
                parts.append(t)

        if not parts:
            raise RuntimeError('EPUB 未提取到正文')
        return '\n\n'.join(parts)


def load_any(path: str) -> str:
    return epub_text(path) if path.lower().endswith('.epub') else read_text(path)


SEPARATOR_PATTERN = re.compile(r'^[-=*_·—~]{8,}$')


def split_chapters(text: str, max_title_len: int = 45):
    """返回 [{title,pos,end}]。

    兼容两种常见排版：
      1. 分隔线 + 标题行（番茄导出：`--------` 空行 标题）
      2. 标题行自带编号（`第一章 xxx` / `Chapter 3`）
    都不匹配时整本作为一章。
    """
    lines = text.split('\n')
    starts = []
    off = 0
    for ln in lines:
        starts.append(off)
        off += len(ln) + 1

    marks = []          # [(pos, title)]
    i, n = 0, len(lines)
    while i < n:
        s = lines[i].strip()
        if SEPARATOR_PATTERN.match(s):
            j = i + 1
            while j < n and not lines[j].strip():
                j += 1
            if j < n:
                title = lines[j].strip()
                if title and len(title) <= max_title_len and not SEPARATOR_PATTERN.match(title):
                    marks.append((starts[i], title))
                    i = j + 1
                    continue
        elif (s and len(s) <= max_title_len and CHAPTER_PATTERN.match(s)
              and not re.search(r'[。！？；]', s)):
            marks.append((starts[i], s))
        i += 1

    if not marks:
        return [{'title': '正文', 'pos': 0, 'end': len(text)}]

    out = []
    if marks[0][0] > 0 and text[:marks[0][0]].strip():
        out.append({'title': '前言', 'pos': 0, 'end': marks[0][0]})
    for k, (pos, title) in enumerate(marks):
        end = marks[k + 1][0] if k + 1 < len(marks) else len(text)
        out.append({'title': title, 'pos': pos, 'end': end})
    return out


SENTENCE_END = re.compile(r'[。！？…”』」）\)\.\!\?"\'\u2019]$')


def iter_paragraphs(chunk: str, max_len: int = 460):
    """产出 (kind, text)，kind 为 'h' 或 'p'。

    规则与网页版一致：单换行的小说按句末标点断段，空行也是硬分隔；
    长段落超过 max_len 强制断开，避免整章挤成一坨。
    """
    buf = ''

    def take():
        nonlocal buf
        if buf.strip():
            out = buf.strip()
            buf = ''
            return ('p', out)
        buf = ''
        return None

    for raw in chunk.split('\n'):
        s = raw.strip()
        if not s:
            t = take()
            if t:
                yield t
            continue
        if SEPARATOR_PATTERN.match(s):      # 分隔线不参与排版
            continue
        if len(s) <= 45 and CHAPTER_PATTERN.match(s):
            t = take()
            if t:
                yield t
            yield 'h', s
            continue
        buf += s
        if len(buf) > max_len or (len(buf) >= 2 and SENTENCE_END.search(buf)):
            t = take()
            if t:
                yield t
    t = take()
    if t:
        yield t
