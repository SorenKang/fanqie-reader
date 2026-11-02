# -*- coding: utf-8 -*-
"""本地小说阅读器 — 单窗口桌面版。

用一个普通窗口读本地 txt / epub：
  · 原生窗口，拖边角就能改大小，最小化 / 最大化 / F11 全屏
  · UTF-8 / GBK 自动识别，EPUB 直接读
  · 左侧章节目录，点一下就跳过去
  · 记住每本书的进度、字号、配色和窗口大小
  · 窗口拉得很宽时正文自动居中，不会拉成一条长线

只用 Python 标准库。
"""
from __future__ import annotations

import json
import os
import queue
import re
import sys
import threading
import time
import traceback
import tkinter as tk
from tkinter import filedialog, font as tkfont, ttk

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'tools'))

import booklib  # noqa: E402
from source import TomatoSource, BOOKS as SRC_BOOKS  # noqa: E402

BOOKS_DIR = os.path.join(ROOT, 'books')
STATE_FILE = os.path.join(HERE, 'state.json')
UI_FONT = 'Microsoft YaHei UI'
MAX_LINE = 880          # 正文最大排版宽度（像素）

THEMES = {
    'light': {
        'bg': '#ffffff', 'panel': '#fafaf8', 'hover': '#efefec', 'line': '#e8e8e3',
        'fg': '#26262a', 'sub': '#8f8f88', 'sel': '#dcebe1', 'sel_fg': '#14543f',
        'acc': '#0f6f56', 'acc_fg': '#ffffff', 'acc_hover': '#0b5a45',
    },
    'sepia': {
        'bg': '#f9f3e7', 'panel': '#f2ead9', 'hover': '#e9dfc9', 'line': '#e2d6bd',
        'fg': '#3a3226', 'sub': '#9c8c72', 'sel': '#e5d5b2', 'sel_fg': '#6b4f22',
        'acc': '#8a6d3b', 'acc_fg': '#fffdf7', 'acc_hover': '#735a2f',
    },
    'dark': {
        'bg': '#1c1c1e', 'panel': '#232325', 'hover': '#2e2e31', 'line': '#343437',
        'fg': '#d2d2d4', 'sub': '#7d7d82', 'sel': '#2c4a3f', 'sel_fg': '#d9f0e6',
        'acc': '#3f9d82', 'acc_fg': '#ffffff', 'acc_hover': '#357f6a',
    },
}
THEME_ORDER = ['light', 'sepia', 'dark']
THEME_NAME = {'light': '浅色', 'sepia': '护眼', 'dark': '深色'}


class FlatButton(tk.Label):
    """自绘扁平按钮。系统主题画不出这种样式，所以自己上色。"""

    def __init__(self, master, text, command=None, kind='ghost', padx=13, **kw):
        super().__init__(master, text=text, bd=0, highlightthickness=0,
                         padx=padx, pady=6, cursor='hand2',
                         font=(UI_FONT, -13), **kw)
        self.command = command
        self.kind = kind                     # ghost | primary
        self._c = {'bg': '#fafaf8', 'fg': '#26262a', 'hover': '#efefec',
                   'hover_fg': '#26262a'}
        self.bind('<Button-1>', self._press)
        self.bind('<ButtonRelease-1>', self._release)
        self.bind('<Enter>', self._enter)
        self.bind('<Leave>', self._leave)

    def _press(self, _e):
        self.configure(bg=self._c['hover'])

    def _release(self, _e):
        self.configure(bg=self._c['hover'])
        if self.command:
            self.command()

    def _enter(self, _e):
        self.configure(bg=self._c['hover'], fg=self._c['hover_fg'])

    def _leave(self, _e):
        self.configure(bg=self._c['bg'], fg=self._c['fg'])

    def set_text(self, text):
        self.configure(text=text)

    def theme(self, t):
        if self.kind == 'primary':
            self._c = {'bg': t['acc'], 'fg': t['acc_fg'],
                       'hover': t['acc_hover'], 'hover_fg': t['acc_fg']}
        else:
            self._c = {'bg': t['panel'], 'fg': t['fg'],
                       'hover': t['hover'], 'hover_fg': t['fg']}
        self.configure(bg=self._c['bg'], fg=self._c['fg'])


class SlimScrollbar(tk.Canvas):
    """自绘细滚动条。系统滚动条在深色主题下会露出浅色底，很难看。"""

    def __init__(self, master, command, width=8, **kw):
        super().__init__(master, width=width, bd=0, highlightthickness=0, **kw)
        self.command = command
        self._a, self._b = 0.0, 1.0
        self._fg = '#cccccc'
        self.bind('<Configure>', lambda e: self._draw())
        self.bind('<Button-1>', self._jump)
        self.bind('<B1-Motion>', self._jump)

    def theme(self, fg, bg):
        self._fg = fg
        self.configure(bg=bg)
        self._draw()

    def set(self, first, last):
        try:
            self._a, self._b = float(first), float(last)
        except (TypeError, ValueError):
            return
        self._draw()

    def _draw(self):
        self.delete('all')
        h = self.winfo_height()
        w = self.winfo_width()
        if h <= 2 or w <= 2:
            return
        if self._b - self._a >= 0.999:
            return
        y1 = self._a * h
        y2 = max(y1 + 26, self._b * h)
        y2 = min(y2, h)
        self.create_rectangle(2, y1, w - 2, y2, fill=self._fg, outline='')

    def _jump(self, e):
        h = self.winfo_height()
        if h > 0:
            self.command('moveto', max(0.0, min(1.0, e.y / h)))


class Reader:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.book = None                 # {name, path, text, chapters}
        self.ch = 0
        self.fs = 18
        self.theme = 'light'
        self.auto = False
        self.speed = 8                   # 行/秒
        self.acc = 0.0
        self.toc_on = True
        self.fullscreen = False
        self.state = {}
        self._pad = 40
        self._ticks = 0
        self.source = TomatoSource()
        self._src_dlg = None

        self._load_state()
        self._build()
        self._apply_theme()
        self._bind()
        self._open_last()
        self._tick()

    # ------------------------------------------------------------------ 状态
    def _load_state(self):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as fh:
                self.state = json.load(fh)
        except Exception:
            self.state = {}
        self.fs = int(self.state.get('fs', 18))
        self.theme = self.state.get('theme', 'light')
        if self.theme not in THEMES:
            self.theme = 'light'
        self.speed = int(self.state.get('speed', 8))
        self.toc_on = bool(self.state.get('toc', True))
        self.progress = self.state.get('progress', {})   # {path: {ch, ratio}}
        self.recent = self.state.get('recent', [])

    def save_state(self):
        g = self.state.get('geom', '')
        if not self.fullscreen:
            cur = self.root.geometry()
            try:
                w = int(cur.split('x')[0])
            except Exception:
                w = 0
            if w > 200:                # 窗口还没 map 时是 1x1，别写脏数据
                g = cur
        st = {
            'fs': self.fs,
            'theme': self.theme,
            'speed': self.speed,
            'toc': self.toc_on,
            'geom': g,
            'progress': self.progress,
            'recent': self.recent[:20],
            'last': self.book['path'] if self.book else self.state.get('last', ''),
        }
        try:
            with open(STATE_FILE, 'w', encoding='utf-8') as fh:
                json.dump(st, fh, ensure_ascii=False, indent=1)
        except Exception:
            pass

    # ------------------------------------------------------------------ 界面
    def _build(self):
        r = self.root
        r.title('阅读器')
        r.minsize(520, 400)
        r.columnconfigure(0, weight=1)
        r.rowconfigure(1, weight=1)

        self.style = ttk.Style()
        for name in ('vista', 'winnative', 'clam'):
            try:
                self.style.theme_use(name)
                break
            except tk.TclError:
                continue

        # 工具栏
        self.bar = tk.Frame(r, bd=0, highlightthickness=0)
        self.bar.grid(row=0, column=0, sticky='ew')
        self.bar_line = tk.Frame(self.bar, height=1, bd=0, highlightthickness=0)
        self.bar_line.pack(side='bottom', fill='x')

        self.tools = tk.Frame(self.bar, bd=0, highlightthickness=0)
        self.tools.pack(side='top', fill='x', padx=8, pady=(8, 7))

        self._buttons = []
        self._seps = []

        def mk(text, cmd, kind='ghost', side='left', pad=(0, 0)):
            b = FlatButton(self.tools, text, cmd, kind=kind)
            b.pack(side=side, padx=pad)
            self._buttons.append(b)
            return b

        def sep():
            f = tk.Frame(self.tools, width=1, bd=0, highlightthickness=0)
            f.pack(side='left', fill='y', padx=10, pady=3)
            self._seps.append(f)

        self.btn_open = mk('打开', self.pick_file)
        self.btn_src = mk('搜书', self.open_source, kind='primary', pad=(4, 0))
        sep()
        self.btn_toc = mk('目录 ‹', self.toggle_toc)
        sep()
        mk('A-', lambda: self.set_fs(-1))
        mk('A+', lambda: self.set_fs(+1), pad=(2, 0))
        self.btn_theme = mk(THEME_NAME[self.theme], self.cycle_theme, pad=(8, 0))
        self.btn_auto = mk('自动滚动', self.toggle_auto, pad=(2, 0))

        self.btn_next = mk('下一章 ›', lambda: self.step_ch(+1), side='right')
        self.btn_prev = mk('‹ 上一章', lambda: self.step_ch(-1), side='right', pad=(0, 4))

        # 主体
        self.body = tk.Frame(r, bd=0, highlightthickness=0)
        self.body.grid(row=1, column=0, sticky='nsew')
        self.body.columnconfigure(1, weight=1)
        self.body.rowconfigure(0, weight=1)

        # 左侧目录
        self.toc_frame = tk.Frame(self.body, width=240, bd=0, highlightthickness=0)
        self.toc_frame.grid(row=0, column=0, sticky='ns')
        self.toc_frame.grid_propagate(False)
        self.toc_frame.pack_propagate(False)

        self.toc_head = tk.Label(self.toc_frame, text='目录', anchor='w', padx=16,
                                 pady=10, bd=0, font=(UI_FONT, -12, 'bold'))
        self.toc_head.pack(side='top', fill='x')

        toc_wrap = tk.Frame(self.toc_frame, bd=0, highlightthickness=0)
        toc_wrap.pack(side='top', fill='both', expand=True)
        self.toc = tk.Listbox(toc_wrap, bd=0, highlightthickness=0, activestyle='none',
                              exportselection=False, font=(UI_FONT, -14))
        self.toc.pack(side='left', fill='both', expand=True, padx=(10, 0), pady=(0, 10))
        self.toc_sb = SlimScrollbar(toc_wrap, command=self.toc.yview)
        self.toc_sb.pack(side='right', fill='y', pady=(0, 10))
        self.toc.configure(yscrollcommand=self.toc_sb.set)
        self.toc.bind('<<ListboxSelect>>', self._on_toc)

        # 正文
        self.txt_frame = tk.Frame(self.body, bd=0, highlightthickness=0)
        self.txt_frame.grid(row=0, column=1, sticky='nsew')
        self.txt_frame.rowconfigure(0, weight=1)
        self.txt_frame.columnconfigure(0, weight=1)

        self.txt = tk.Text(self.txt_frame, wrap='word', bd=0, highlightthickness=0,
                           relief='flat', insertwidth=0, cursor='xterm',
                           padx=self._pad, pady=26, spacing1=0, spacing2=0,
                           spacing3=0, tabs='')
        self.txt.grid(row=0, column=0, sticky='nsew')
        self.sb = SlimScrollbar(self.txt_frame, command=self.txt.yview)
        self.sb.grid(row=0, column=1, sticky='ns')
        self.txt.configure(yscrollcommand=self._on_yscroll)

        # 状态栏
        self.status = tk.Frame(r, bd=0, highlightthickness=0)
        self.status.grid(row=2, column=0, sticky='ew')
        self.st_left = tk.Label(self.status, anchor='w', padx=16, pady=6, bd=0,
                                font=(UI_FONT, -12))
        self.st_left.pack(side='left')
        self.st_right = tk.Label(self.status, anchor='e', padx=16, pady=6, bd=0,
                                 font=(UI_FONT, -12))
        self.st_right.pack(side='right')

        self.f_body = tkfont.Font(family=UI_FONT, size=-self.fs)
        self.f_head = tkfont.Font(family=UI_FONT, size=-(self.fs + 4), weight='bold')
        self.txt.configure(font=self.f_body)

        self._restore_geom()

        if not self.toc_on:
            self.toc_frame.grid_remove()
        self._sync_toc_btn()

    def _restore_geom(self):
        g = self.state.get('geom', '')
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        ok = False
        m = re.match(r'^(\d+)x(\d+)', g or '')
        if m:
            w, h = int(m.group(1)), int(m.group(2))
            ok = 400 <= w <= sw and 300 <= h <= sh
        if ok:
            self._geom = g
        else:
            w, h = min(940, sw - 160), min(780, sh - 140)
            self._geom = f'{w}x{h}+{(sw - w) // 2}+{max(40, (sh - h) // 3)}'
        self.apply_geom()

    def apply_geom(self):
        """窗口首次 map 之前设的 geometry 会被内容尺寸盖掉，map 后再钉一次。"""
        self.root.geometry(self._geom)
        self.root.after(30, lambda: self.root.geometry(self._geom))

    # ------------------------------------------------------------------ 配色
    def _apply_theme(self):
        t = THEMES[self.theme]
        self.root.configure(bg=t['bg'])

        self.bar.configure(bg=t['panel'])
        self.bar_line.configure(bg=t['line'])
        self.tools.configure(bg=t['panel'])
        for f in self._seps:
            f.configure(bg=t['line'], width=1)
        for b in self._buttons:
            b.theme(t)

        self.body.configure(bg=t['bg'])
        self.txt_frame.configure(bg=t['bg'])

        self.toc_frame.configure(bg=t['panel'])
        self.toc_head.configure(bg=t['panel'], fg=t['sub'])
        self.toc.configure(bg=t['panel'], fg=t['fg'], selectbackground=t['sel'],
                           selectforeground=t['sel_fg'], highlightthickness=0, bd=0)
        self.toc_sb.theme(t['line'], t['panel'])

        self.txt.configure(bg=t['bg'], fg=t['fg'],
                           selectbackground=t['sel'], selectforeground=t['sel_fg'],
                           insertbackground=t['fg'])
        self.sb.theme(t['line'], t['bg'])

        self.status.configure(bg=t['panel'])
        self.st_left.configure(bg=t['panel'], fg=t['sub'])
        self.st_right.configure(bg=t['panel'], fg=t['sub'])

        self._tags()
        self.btn_theme.set_text(THEME_NAME[self.theme])
        self._dark_titlebar(self.theme == 'dark')

    def _dark_titlebar(self, dark: bool):
        """Windows 10/11：让标题栏跟随深色配色。"""
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            v = ctypes.c_int(1 if dark else 0)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(v), 4)
        except Exception:
            pass

    def _tags(self):
        fs = self.fs
        self.txt.tag_configure(
            'p', lmargin1=fs * 2, lmargin2=0, rmargin=0,
            spacing1=int(fs * 0.28), spacing2=int(fs * 0.62), spacing3=int(fs * 0.62))
        self.txt.tag_configure(
            'h', lmargin1=0, lmargin2=0, rmargin=0,
            spacing1=int(fs * 1.5), spacing2=int(fs * 0.35), spacing3=int(fs * 0.9),
            font=self.f_head)
        self.txt.tag_configure('link', foreground=THEMES[self.theme]['acc'],
                               underline=True)
        self.txt.tag_configure('dim', foreground=THEMES[self.theme]['sub'])

    def cycle_theme(self):
        self.theme = THEME_ORDER[(THEME_ORDER.index(self.theme) + 1) % len(THEME_ORDER)]
        self._apply_theme()
        self.render(keep_ratio=True)
        self.flash('配色 · ' + THEME_NAME[self.theme])

    def set_fs(self, d):
        self.fs = max(14, min(36, self.fs + d))
        self.f_body.configure(size=-self.fs)
        self.f_head.configure(size=-(self.fs + 4))
        self._apply_theme()
        self.render(keep_ratio=True)
        self.flash(f'字号 {self.fs}')

    # ------------------------------------------------------------------ 打开
    def pick_file(self):
        p = filedialog.askopenfilename(
            title='打开小说',
            initialdir=BOOKS_DIR if os.path.isdir(BOOKS_DIR) else HERE,
            filetypes=[('小说文本', '*.txt *.epub *.md'), ('全部文件', '*.*')])
        if p:
            self.open_path(p)

    def open_source(self):
        """打开搜书面板（书源进程按需拉起）。"""
        if self._src_dlg is not None:
            try:
                if self._src_dlg.winfo_exists():
                    self._src_dlg.deiconify()
                    self._src_dlg.lift()
                    self._src_dlg.focus_force()
                    return
            except tk.TclError:
                pass
        self._src_dlg = SourceDialog(self)

    def open_path(self, path):
        self.flash('正在读取…')
        self.root.update_idletasks()
        try:
            text = booklib.load_any(path)
        except Exception as e:
            self.flash(f'读取失败：{e}')
            return
        if not text.strip():
            self.flash('文件是空的')
            return

        self.book = {
            'name': os.path.basename(path),
            'path': os.path.abspath(path),
            'text': text,
            'chapters': booklib.split_chapters(text),
        }
        pr = self.progress.get(self.book['path'], {})
        self.ch = max(0, min(len(self.book['chapters']) - 1, int(pr.get('ch', 0))))
        ratio = float(pr.get('ratio', 0.0))

        self._fill_toc()
        self.root.title(self.book['name'] + ' - 阅读器')
        self.render(ratio=ratio)
        self.flash(f'{len(self.book["chapters"])} 段 · {sum(1 for c in text if c.strip()):,} 字')

        if self.book['path'] in self.recent:
            self.recent.remove(self.book['path'])
        self.recent.insert(0, self.book['path'])
        self.save_state()

    def _open_last(self):
        last = self.state.get('last', '')
        if last and os.path.isfile(last):
            self.open_path(last)
            return
        if os.path.isdir(BOOKS_DIR):
            for n in sorted(os.listdir(BOOKS_DIR)):
                if n.lower().endswith(('.txt', '.epub', '.md')):
                    self.open_path(os.path.join(BOOKS_DIR, n))
                    return
        self.welcome()

    def welcome(self):
        self.root.title('阅读器')
        self.txt.configure(state='normal')
        self.txt.delete('1.0', 'end')
        self.txt.insert('end', '本地阅读器\n', 'h')
        self.txt.insert('end', '\n把小说放进 books 目录，或者按下面的按钮选一个文件。\n\n', 'dim')
        self.txt.insert('end', '快捷键\n', 'h')
        for line in ('    Ctrl+S      搜书 / 下载（书源）',
                     '    Ctrl+O      打开本地文件',
                     '    Ctrl+滚轮   调字号',
                     '    [  /  ]     上一章 / 下一章',
                     '    空格         翻页',
                     '    F11         全屏'):
            self.txt.insert('end', line + '\n', 'dim')
        files = []
        if os.path.isdir(BOOKS_DIR):
            files = [n for n in sorted(os.listdir(BOOKS_DIR))
                     if n.lower().endswith(('.txt', '.epub', '.md'))]
        if files:
            self.txt.insert('end', '\n书库\n', 'h')
            for n in files:
                start = self.txt.index('end-1c')
                self.txt.insert('end', '    ' + n + '\n', 'link')
                tag = f'book::{n}'
                self.txt.tag_add(tag, start, self.txt.index('end-1c'))
                self.txt.tag_bind(tag, '<Button-1>',
                                  lambda e, name=n: self.open_path(os.path.join(BOOKS_DIR, name)))
        self.txt.configure(state='normal')
        self.flash('未打开文件')

    # ------------------------------------------------------------------ 渲染
    def render(self, ratio=0.0, keep_ratio=False):
        if not self.book:
            return
        if keep_ratio:
            y0, y1 = self.txt.yview()
            ratio = y0
        ch = self.book['chapters'][self.ch]
        chunk = self.book['text'][ch['pos']:ch['end']]

        self.txt.configure(state='normal')
        self.txt.delete('1.0', 'end')
        blocks = list(booklib.iter_paragraphs(chunk))
        # 番茄那种「分隔线 + 标题行」的排版，标题行不带编号，这里补成标题样式
        if blocks and blocks[0][0] == 'p' and blocks[0][1].strip() == ch['title'].strip():
            blocks[0] = ('h', ch['title'].strip())
        for kind, text in blocks:
            self.txt.insert('end', text + '\n', 'h' if kind == 'h' else 'p')
        self.txt.yview_moveto(ratio)
        self.root.update_idletasks()
        # 光标默认停在正文末尾，窗口拿到焦点会自己滚过去，把它钉回可视区首行
        self.txt.mark_set('insert', self.txt.index('@0,0'))
        self.txt.focus_set()

        if self.toc_on and self.toc.size() > self.ch:
            self.toc.selection_clear(0, 'end')
            self.toc.selection_set(self.ch)
            self.toc.see(self.ch)
        self.update_status()
        self.save_progress()

    def _fill_toc(self):
        self.toc.delete(0, 'end')
        for c in self.book['chapters']:
            self.toc.insert('end', ' ' + c['title'])

    def _on_toc(self, _e):
        sel = self.toc.curselection()
        if not sel or not self.book:
            return
        i = int(sel[0])
        if i != self.ch:
            self.ch = i
            self.render(ratio=0.0)

    def step_ch(self, d):
        if not self.book:
            return
        n = len(self.book['chapters'])
        self.ch = max(0, min(n - 1, self.ch + d))
        self.render(ratio=0.0)

    def toggle_toc(self):
        self.toc_on = not self.toc_on
        if self.toc_on:
            self.toc_frame.grid()
        else:
            self.toc_frame.grid_remove()
        self._sync_toc_btn()
        self.save_state()

    def _sync_toc_btn(self):
        """按钮文字跟着状态走：展开时显示收起箭头，收起时显示展开箭头。"""
        try:
            self.btn_toc.set_text('目录 ‹' if self.toc_on else '目录 ›')
        except tk.TclError:
            pass

    # ------------------------------------------------------------------ 滚动
    def _on_yscroll(self, first, last):
        self.sb.set(first, last)
        if self.book:
            self.update_status()

    def update_status(self):
        if not self.book:
            self.st_left.configure(text='未打开文件')
            self.st_right.configure(text='')
            return
        try:
            y0 = float(self.txt.yview()[0])
        except Exception:
            y0 = 0.0
        n = len(self.book['chapters'])
        left = f'{self.ch + 1} / {n}'
        if self.auto:
            left += f'    ▶ {self.speed}'
        name = self.book['name']
        if len(name) > 28:
            name = name[:26] + '…'
        self.st_left.configure(text=left)
        self.st_right.configure(text=f'{int(y0 * 100)}%    {name}')

    def flash(self, msg):
        self.st_left.configure(text=str(msg))
        self.root.after(2000, self.update_status)

    def toggle_auto(self):
        self.auto = not self.auto
        self.acc = 0.0
        self.btn_auto.set_text('停止滚动' if self.auto else '自动滚动')
        self.flash('自动滚动中，按空格停下' if self.auto else '已停止')

    def _tick(self):
        if self.auto and self.book:
            self.acc += self.speed / 20.0
            if self.acc >= 1:
                step = int(self.acc)
                self.acc -= step
                self.txt.yview_scroll(step, 'units')
                if self.txt.yview()[1] >= 0.999:
                    if self.ch < len(self.book['chapters']) - 1:
                        self.ch += 1
                        self.render(ratio=0.0)
                    else:
                        self.auto = False
                        self.btn_auto.set_text('自动滚动')
        self._ticks += 1
        if self._ticks % 100 == 0:      # 每 5 秒落一次盘
            self.save_progress()
            self.save_state()
        self.root.after(50, self._tick)

    def save_progress(self):
        if not self.book:
            return
        self.progress[self.book['path']] = {
            'ch': self.ch,
            'ratio': round(float(self.txt.yview()[0]), 4),
        }

    # ------------------------------------------------------------------ 事件
    def _bind(self):
        r = self.root
        r.bind('<Control-o>', lambda e: self.pick_file())
        r.bind('<Control-s>', lambda e: self.open_source())
        r.bind('<Control-plus>', lambda e: self.set_fs(+1))
        r.bind('<Control-equal>', lambda e: self.set_fs(+1))
        r.bind('<Control-minus>', lambda e: self.set_fs(-1))
        r.bind('<F11>', lambda e: self.toggle_fullscreen())
        r.bind('<Escape>', lambda e: self.exit_fullscreen())
        r.bind('<bracketright>', lambda e: self.step_ch(+1))
        r.bind('<bracketleft>', lambda e: self.step_ch(-1))
        r.bind('<space>', self._on_space)
        r.bind('<Control-t>', lambda e: self.cycle_theme())
        r.bind('<Control-b>', lambda e: self.toggle_toc())
        r.protocol('WM_DELETE_WINDOW', self.on_close)

        self.txt.bind('<Control-MouseWheel>', self._on_ctrl_wheel)
        self.txt.bind('<Button-4>', self._on_ctrl_wheel)
        self.txt.bind('<Button-5>', self._on_ctrl_wheel)
        self.txt.bind('<Configure>', self._on_resize)
        self.txt.bind('<Key>', self._block_edit)

    def _on_space(self, e):
        if self.auto:
            self.toggle_auto()
            return 'break'

    def _block_edit(self, e):
        if e.keysym == 'space':
            if self.auto:
                self.toggle_auto()
            return 'break'
        if e.keysym in ('Up', 'Down', 'Left', 'Right', 'Prior', 'Next', 'Home', 'End',
                        'Page_Up', 'Page_Down'):
            return None
        if e.state & 0x4:          # Ctrl 组合放行，复制/全选可用
            return None
        return 'break'

    def _on_ctrl_wheel(self, e):
        delta = getattr(e, 'delta', 0)
        if delta == 0:
            delta = 120 if getattr(e, 'num', 0) == 4 else -120
        self.set_fs(1 if delta > 0 else -1)
        return 'break'

    def _on_resize(self, e):
        pad = max(26, (e.width - MAX_LINE) // 2)
        if abs(pad - self._pad) > 3:
            self._pad = pad
            self.txt.configure(padx=pad)

    def toggle_fullscreen(self):
        self.fullscreen = not self.fullscreen
        self.root.attributes('-fullscreen', self.fullscreen)

    def exit_fullscreen(self):
        if self.fullscreen:
            self.fullscreen = False
            self.root.attributes('-fullscreen', False)

    def on_close(self):
        self.save_progress()
        self.save_state()
        self.root.destroy()


class SourceDialog(tk.Toplevel):
    """搜书 / 下载面板。后端是 vendor 里的 tomato-rust（开源，MIT）。"""

    def __init__(self, app: 'Reader'):
        super().__init__(app.root)
        self.app = app
        self.src = app.source
        self.title('书源 · 番茄小说')
        self.geometry('840x580')
        self.minsize(640, 420)
        self.transient(app.root)

        self.items = []
        self.job_id = None
        self.job_book = ''
        self._t0 = 0.0
        self._q = queue.Queue()

        self._build()
        self._pump()
        self._tick()
        self.after(150, lambda: self.entry.focus_set())

    # ------------------------------------------------------------ UI
    def _build(self):
        top = ttk.Frame(self, padding=(12, 10, 12, 6))
        top.pack(fill='x')
        ttk.Label(top, text='关键字').pack(side='left')
        self.entry = ttk.Entry(top)
        self.entry.pack(side='left', fill='x', expand=True, padx=8)
        self.entry.bind('<Return>', lambda e: self.search())
        self.btn_search = ttk.Button(top, text='搜索', width=7, command=self.search)
        self.btn_search.pack(side='left')

        body = ttk.Frame(self, padding=(12, 0, 12, 0))
        body.pack(fill='both', expand=True)
        cols = ('title', 'author', 'id')
        self.tree = ttk.Treeview(body, columns=cols, show='headings', height=15)
        self.tree.heading('title', text='书名')
        self.tree.heading('author', text='作者')
        self.tree.heading('id', text='book_id')
        self.tree.column('title', width=430, anchor='w')
        self.tree.column('author', width=150, anchor='w')
        self.tree.column('id', width=190, anchor='w')
        self.tree.pack(side='left', fill='both', expand=True)
        sb = ttk.Scrollbar(body, orient='vertical', command=self.tree.yview)
        sb.pack(side='right', fill='y')
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind('<Double-1>', lambda e: self.download(False))

        bot = ttk.Frame(self, padding=(12, 8, 12, 4))
        bot.pack(fill='x')
        ttk.Button(bot, text='下载全本', width=10,
                   command=lambda: self.download(False)).pack(side='left')
        ttk.Button(bot, text='只下前 20 章', width=13,
                   command=lambda: self.download(True)).pack(side='left', padx=(6, 0))
        ttk.Button(bot, text='网页版', width=8, command=self.open_web).pack(side='right')
        ttk.Button(bot, text='书库目录', width=10,
                   command=self.open_books).pack(side='right', padx=(0, 6))

        self.status = ttk.Label(self, text='输入书名或作者，回车搜索（首次会拉起书源，约几秒）',
                                padding=(14, 2, 14, 8))
        self.status.pack(fill='x')

    # ------------------------------------------------------------ 动作
    def search(self):
        q = self.entry.get().strip()
        if not q:
            return
        self.btn_search.configure(state='disabled')
        self.status.configure(text='连接书源…')
        threading.Thread(target=self._search_worker, args=(q,), daemon=True).start()

    def _search_worker(self, q):
        try:
            if not self.src.start():
                self._q.put(('err', '书源起不来，检查 vendor\\tomato-rust.exe'))
                return
            self._q.put(('items', self.src.search(q)))
        except Exception as e:
            self._q.put(('err', str(e)))

    def download(self, partial=False):
        sel = self.tree.selection()
        if not sel:
            self.status.configure(text='先在列表里选一本')
            return
        vals = self.tree.item(sel[0], 'values')
        if len(vals) < 3:
            return
        book_id, name = str(vals[2]), str(vals[0])
        self.job_book = name
        self._t0 = time.time()
        self.status.configure(text=f'创建任务：{name}')
        threading.Thread(target=self._dl_worker, args=(book_id, partial), daemon=True).start()

    def _dl_worker(self, book_id, partial):
        try:
            if not self.src.start():
                self._q.put(('err', '书源没起来'))
                return
            r = (self.src.download(book_id, 1, 20) if partial
                 else self.src.download(book_id))
            self._q.put(('job', r))
        except Exception as e:
            self._q.put(('err', str(e)))

    def open_web(self):
        try:
            self.src.start()
        except Exception:
            pass
        try:
            os.startfile(self.src.web_url())
        except Exception as e:
            self.status.configure(text=f'打不开浏览器：{e}')

    def open_books(self):
        try:
            os.startfile(SRC_BOOKS)
        except Exception as e:
            self.status.configure(text=f'打不开目录：{e}')

    # ------------------------------------------------------------ 轮询
    def _pump(self):
        try:
            while True:
                kind, payload = self._q.get_nowait()
                if kind == 'items':
                    self.items = payload
                    self._fill(payload)
                    self.status.configure(text=f'{len(payload)} 条结果 · 双击或点按钮下载')
                    self.btn_search.configure(state='normal')
                elif kind == 'job':
                    jid = (payload or {}).get('id')
                    if jid:
                        self.job_id = jid
                        self.status.configure(text=f'已排队：{self.job_book}')
                    else:
                        self.status.configure(
                            text='创建任务失败：' + json.dumps(payload, ensure_ascii=False)[:120])
                elif kind == 'err':
                    self.status.configure(text='出错：' + payload)
                    self.btn_search.configure(state='normal')
        except queue.Empty:
            pass
        self.after(120, self._pump)

    def _tick(self):
        if self.job_id is not None:
            try:
                for j in self.src.jobs():
                    if j.get('id') != self.job_id:
                        continue
                    pr = j.get('progress') or {}
                    saved = pr.get('saved_chapters', 0)
                    total = pr.get('chapter_total', 0)
                    state = (j.get('state') or '').lower()
                    self.status.configure(text=f'{self.job_book} · {state} · {saved}/{total}')
                    if state in ('done', 'failed', 'canceled', 'partial'):
                        self._finish(state)
                    break
            except Exception:
                pass
        self.after(2000, self._tick)

    def _finish(self, state):
        self.job_id = None
        if state == 'done':
            path = self.src.newest_book(self._t0)
            if path:
                self.status.configure(text='已入库 · ' + os.path.basename(path))
                self.app.open_path(path)
            else:
                self.status.configure(text='下载完成，但 books 里没找到新文件')
        else:
            self.status.configure(text='任务结束：' + state)

    def _fill(self, items):
        for i in self.tree.get_children():
            self.tree.delete(i)
        for it in items:
            self.tree.insert('', 'end', values=(
                it.get('title', ''), it.get('author', ''), it.get('book_id', '')))


def main():
    root = tk.Tk()
    Reader(root)

    def on_error(exc, val, tb):
        """任何回调里的异常都落到 error.log，避免 pythonw 静默退出。"""
        try:
            with open(os.path.join(HERE, 'error.log'), 'a', encoding='utf-8') as fh:
                fh.write(f'--- {time.strftime("%Y-%m-%d %H:%M:%S")}\n')
                traceback.print_exception(exc, val, tb, file=fh)
        except Exception:
            pass

    root.report_callback_exception = on_error
    root.mainloop()


if __name__ == '__main__':
    main()
