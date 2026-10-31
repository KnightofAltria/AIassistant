#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从文字版 PDF 里抽取文字 —— 只用标准库（zlib 解压 + 自己解析 PDF 对象）。

能处理：普通文字版 PDF（Word / PPT / LaTeX 导出）、对象流（PDF 1.5+）、FlateDecode /
ASCIIHex / ASCII85 压缩、带 ToUnicode 映射的中文字体、表单 XObject 里的文字。
不能处理（给出明确的中文提示）：加密 PDF、扫描件 / 纯图片 PDF（本项目不做 OCR）、
字体没带文字映射导致抽不出可读文字的 PDF。

抽出的文字按页输出，每页前面加"## 第 N 页"，阅读页与检索引用可以据此定位。
"""

from __future__ import annotations

import base64
import re
import unicodedata
import zlib


class PdfError(ValueError):
    """PDF 无法导入，message 是给用户看的中文说明。"""


# ---------------------------------------------------------------- 基本对象
class Name(str):
    pass


class Ref(tuple):
    def __new__(cls, num: int, gen: int):
        return super().__new__(cls, (num, gen))


class Keyword(str):
    pass


class Stream:
    def __init__(self, attrs: dict, raw: bytes):
        self.attrs = attrs
        self.raw = raw

    def get(self, key, default=None):
        return self.attrs.get(key, default)


WHITESPACE = b" \t\r\n\x0c\x00"
DELIMS = b"()<>[]{}/%"
_NUM_RE = re.compile(rb"[+-]?(\d+\.?\d*|\.\d+)$")


class Lexer:
    def __init__(self, data: bytes, pos: int = 0):
        self.data = data
        self.pos = pos

    def skip_ws(self) -> None:
        data, n = self.data, len(self.data)
        while self.pos < n:
            c = data[self.pos]
            if c in WHITESPACE:
                self.pos += 1
            elif c == 0x25:                                   # % 注释到行尾
                while self.pos < n and data[self.pos] not in b"\r\n":
                    self.pos += 1
            else:
                break

    def token(self):
        """返回下一个记号；读到末尾返回 None。"""
        self.skip_ws()
        data, n = self.data, len(self.data)
        if self.pos >= n:
            return None
        c = data[self.pos:self.pos + 1]
        if c == b"/":
            end = self.pos + 1
            while end < n and data[end] not in WHITESPACE and data[end] not in DELIMS:
                end += 1
            raw = data[self.pos + 1:end]
            self.pos = end
            raw = re.sub(rb"#([0-9A-Fa-f]{2})", lambda m: bytes([int(m.group(1), 16)]), raw)
            return Name(raw.decode("latin-1"))
        if c == b"(":
            return self._literal()
        if c == b"<":
            if data[self.pos + 1:self.pos + 2] == b"<":
                self.pos += 2
                return Keyword("<<")
            end = data.find(b">", self.pos)
            end = n if end < 0 else end
            hexs = re.sub(rb"[^0-9A-Fa-f]", b"", data[self.pos + 1:end])
            self.pos = end + 1
            if len(hexs) % 2:
                hexs += b"0"
            return bytearray(bytes.fromhex(hexs.decode("ascii")))     # 十六进制串
        if c == b">":
            self.pos += 2 if data[self.pos + 1:self.pos + 2] == b">" else 1
            return Keyword(">>")
        if c in (b"[", b"]", b"{", b"}"):
            self.pos += 1
            return Keyword(c.decode())
        end = self.pos
        while end < n and data[end] not in WHITESPACE and data[end] not in DELIMS:
            end += 1
        if end == self.pos:                                   # 落单的 ) 之类，跳过
            self.pos += 1
            return Keyword(c.decode("latin-1"))
        raw = data[self.pos:end]
        self.pos = end
        if _NUM_RE.match(raw):
            return float(raw) if b"." in raw else int(raw)
        return Keyword(raw.decode("latin-1"))

    def _literal(self) -> bytes:
        data, n = self.data, len(self.data)
        out = bytearray()
        depth, i = 1, self.pos + 1
        escapes = {ord("n"): b"\n", ord("r"): b"\r", ord("t"): b"\t", ord("b"): b"\b",
                   ord("f"): b"\f", ord("("): b"(", ord(")"): b")", ord("\\"): b"\\"}
        while i < n:
            c = data[i]
            if c == 0x5C:                                     # 反斜杠转义
                i += 1
                if i >= n:
                    break
                e = data[i]
                if e in escapes:
                    out += escapes[e]
                    i += 1
                elif 0x30 <= e <= 0x37:
                    j = i
                    while j < n and j < i + 3 and 0x30 <= data[j] <= 0x37:
                        j += 1
                    out.append(int(data[i:j], 8) & 0xFF)
                    i = j
                elif e in b"\r\n":                            # 续行
                    i += 2 if data[i:i + 2] == b"\r\n" else 1
                else:
                    out.append(e)
                    i += 1
                continue
            if c == 0x28:
                depth += 1
            elif c == 0x29:
                depth -= 1
                if depth == 0:
                    i += 1
                    break
            out.append(c)
            i += 1
        self.pos = i
        return bytes(out)

    def parse(self, tok=None):
        """读一个完整的 PDF 值：数字后跟 "G R" 时组成间接引用。"""
        tok = self.token() if tok is None else tok
        if isinstance(tok, Keyword):
            if tok == "<<":
                d = {}
                while True:
                    key = self.token()
                    if key is None or key == ">>":
                        return d
                    if isinstance(key, Name):
                        d[str(key)] = self.parse()
            if tok == "[":
                arr = []
                while True:
                    t = self.token()
                    if t is None or t == "]":
                        return arr
                    arr.append(self.parse(t))
            if tok == "true":
                return True
            if tok == "false":
                return False
            if tok == "null":
                return None
            return tok
        if isinstance(tok, int):
            save = self.pos
            gen = self.token()
            if isinstance(gen, int):
                r = self.token()
                if r == "R":
                    return Ref(tok, gen)
            self.pos = save
        return tok


# ---------------------------------------------------------------- 文档
def _decode_stream(stream: Stream, doc: "PdfDoc") -> bytes:
    data = stream.raw
    filters = doc.resolve(stream.get("Filter"))
    filters = filters if isinstance(filters, list) else ([filters] if filters else [])
    for f in filters:
        f = str(doc.resolve(f))
        if f in ("FlateDecode", "Fl"):
            try:
                data = zlib.decompress(data)
            except zlib.error:
                data = zlib.decompressobj().decompress(data)      # 尾部损坏时尽量取前面
        elif f in ("ASCIIHexDecode", "AHx"):
            hexs = re.sub(rb"[^0-9A-Fa-f]", b"", data.split(b">")[0])
            data = bytes.fromhex((hexs + b"0" * (len(hexs) % 2)).decode())
        elif f in ("ASCII85Decode", "A85"):
            body = data.strip()
            body = body[2:] if body.startswith(b"<~") else body
            body = body.split(b"~>")[0]
            data = base64.a85decode(re.sub(rb"\s", b"", body))
        else:
            raise PdfError(f"PDF 使用了暂不支持的压缩方式 {f}")
    return data


class PdfDoc:
    def __init__(self, data: bytes):
        if not data.lstrip()[:5] == b"%PDF-":
            raise PdfError("不是有效的 PDF 文件（文件头不是 %PDF）")
        self.data = data
        self.objects: dict[int, object] = {}
        self.trailers: list[dict] = []
        self._scan()
        self._expand_object_streams()

    def _scan(self) -> None:
        data = self.data
        covered = 0
        for m in re.finditer(rb"(\d+)\s+(\d+)\s+obj\b", data):
            if m.start() < covered:                           # 落在上一个流的二进制里
                continue
            lex = Lexer(data, m.end())
            try:
                value = lex.parse()
            except (ValueError, IndexError, RecursionError):
                continue
            lex.skip_ws()
            if isinstance(value, dict) and data.startswith(b"stream", lex.pos):
                start = lex.pos + 6
                if data[start:start + 2] == b"\r\n":
                    start += 2
                elif data[start:start + 1] in (b"\n", b"\r"):
                    start += 1
                length = value.get("Length")
                end = start + length if isinstance(length, int) else -1
                if end < 0 or b"endstream" not in data[end:end + 20]:
                    end = data.find(b"endstream", start)
                    end = len(data) if end < 0 else end
                    while end > start and data[end - 1] in b"\r\n":
                        end -= 1
                value = Stream(value, data[start:end])
                covered = end
                if value.get("Type") == "XRef":
                    self.trailers.append(value.attrs)
            else:
                covered = lex.pos
            self.objects[int(m.group(1))] = value
        for m in re.finditer(rb"trailer\s*<<", data):
            lex = Lexer(data, m.end() - 2)
            try:
                t = lex.parse()
            except (ValueError, IndexError, RecursionError):
                continue
            if isinstance(t, dict):
                self.trailers.append(t)

    def _expand_object_streams(self) -> None:
        for obj in list(self.objects.values()):
            if not (isinstance(obj, Stream) and obj.get("Type") == "ObjStm"):
                continue
            try:
                raw = _decode_stream(obj, self)
            except (PdfError, ValueError, zlib.error):
                continue
            n, first = obj.get("N"), obj.get("First")
            if not isinstance(n, int) or not isinstance(first, int):
                continue
            head = Lexer(raw[:first])
            pairs = [head.token() for _ in range(2 * n)]
            for i in range(0, len(pairs) - 1, 2):
                num, off = pairs[i], pairs[i + 1]
                if not isinstance(num, int) or not isinstance(off, int) or num in self.objects:
                    continue
                try:
                    self.objects[num] = Lexer(raw, first + off).parse()
                except (ValueError, IndexError, RecursionError):
                    continue

    def resolve(self, value, depth: int = 0):
        while isinstance(value, Ref) and depth < 32:
            value = self.objects.get(value[0])
            depth += 1
        return value

    def dict_of(self, value) -> dict:
        value = self.resolve(value)
        if isinstance(value, Stream):
            return value.attrs
        return value if isinstance(value, dict) else {}

    @property
    def encrypted(self) -> bool:
        return any("Encrypt" in t for t in self.trailers)

    def pages(self) -> list[tuple[dict, dict]]:
        """按阅读顺序返回 [(页面字典, 继承来的资源字典)]。"""
        root = None
        for t in reversed(self.trailers):
            root = self.dict_of(t.get("Root"))
            if root:
                break
        if not root:
            root = next((o for o in self.objects.values()
                         if isinstance(o, dict) and o.get("Type") == "Catalog"), {})
        out: list[tuple[dict, dict]] = []
        seen: set[int] = set()

        def walk(ref, resources, depth=0):
            if depth > 64:
                return
            if isinstance(ref, Ref):
                if ref[0] in seen:
                    return
                seen.add(ref[0])
            node = self.dict_of(ref)
            res = node.get("Resources", resources)
            kids = self.resolve(node.get("Kids"))
            if isinstance(kids, list):
                for kid in kids:
                    walk(kid, res, depth + 1)
            elif node.get("Type") == "Page" or "Contents" in node:
                out.append((node, self.dict_of(res)))

        walk(root.get("Pages"), {})
        if not out:                                           # 页面树坏了：按对象号兜底
            for num in sorted(self.objects):
                o = self.objects[num]
                if isinstance(o, dict) and o.get("Type") == "Page":
                    out.append((o, self.dict_of(o.get("Resources"))))
        return out


# ---------------------------------------------------------------- 字体：字节 → 文字
_GLYPHS = {"space": " ", "period": ".", "comma": ",", "colon": ":", "semicolon": ";",
           "hyphen": "-", "minus": "-", "parenleft": "(", "parenright": ")",
           "bracketleft": "[", "bracketright": "]", "braceleft": "{", "braceright": "}",
           "quoteright": "’", "quoteleft": "‘", "quotedbl": '"', "quotesingle": "'",
           "quotedblleft": "“", "quotedblright": "”", "slash": "/", "backslash": "\\",
           "underscore": "_", "bullet": "•", "endash": "–", "emdash": "—", "plus": "+",
           "equal": "=", "less": "<", "greater": ">", "percent": "%", "ampersand": "&",
           "asterisk": "*", "at": "@", "numbersign": "#", "dollar": "$", "exclam": "!",
           "question": "?", "bar": "|", "asciitilde": "~", "asciicircum": "^", "grave": "`",
           "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
           "six": "6", "seven": "7", "eight": "8", "nine": "9", "fi": "fi", "fl": "fl"}


def _glyph(name: str) -> str:
    if name in _GLYPHS:
        return _GLYPHS[name]
    if len(name) == 1:
        return name
    m = re.fullmatch(r"uni([0-9A-Fa-f]{4,6})", name) or re.fullmatch(r"u([0-9A-Fa-f]{4,6})", name)
    if m:
        try:
            return chr(int(m.group(1), 16))
        except ValueError:
            return ""
    return ""


def _utf16(b: bytes) -> str:
    return bytes(b).decode("utf-16-be", "ignore")


class FontDecoder:
    def __init__(self, font: dict, doc: PdfDoc):
        self.map: dict[bytes, str] = {}
        self.ranges: list[tuple[int, int, int]] = []          # (字节数, 下界, 上界)
        self.type0 = font.get("Subtype") == "Type0"
        self.utf16 = False
        self.simple: dict[int, str] = {}
        self.unmapped = 0
        self.mapped = 0
        tu = doc.resolve(font.get("ToUnicode"))
        if isinstance(tu, Stream):
            try:
                self._parse_cmap(_decode_stream(tu, doc))
            except (PdfError, ValueError, zlib.error):
                pass
        enc = doc.resolve(font.get("Encoding"))
        if self.type0 and isinstance(enc, str) and re.search(r"UCS2|UTF16", enc):
            self.utf16 = True                                 # 编码本身就是 Unicode
        if not self.type0:
            for code in range(256):
                ch = bytes([code]).decode("cp1252", "ignore")
                if ch:
                    self.simple[code] = ch
            diffs = doc.dict_of(enc).get("Differences") if isinstance(
                doc.resolve(enc), dict) else None
            if isinstance(diffs, list):
                code = 0
                for item in diffs:
                    item = doc.resolve(item)
                    if isinstance(item, int):
                        code = item
                    elif isinstance(item, str):
                        self.simple[code] = _glyph(str(item))
                        code += 1
        if not self.ranges:
            self.ranges = [(2, 0, 0xFFFF)] if self.type0 else [(1, 0, 0xFF)]

    def _parse_cmap(self, data: bytes) -> None:
        lex = Lexer(data)
        toks = []
        while True:
            t = lex.token()
            if t is None:
                break
            if t == "[":
                toks.append(lex.parse(t))
            else:
                toks.append(t)
        mode, buf = "", []
        for t in toks:
            if t in ("begincodespacerange", "beginbfchar", "beginbfrange"):
                mode, buf = t, []
            elif t in ("endcodespacerange", "endbfchar", "endbfrange"):
                if mode == "begincodespacerange":
                    for lo, hi in zip(buf[0::2], buf[1::2]):
                        if isinstance(lo, bytearray) and isinstance(hi, bytearray):
                            self.ranges.append((len(lo), int.from_bytes(lo, "big"),
                                                int.from_bytes(hi, "big")))
                elif mode == "beginbfchar":
                    for src, dst in zip(buf[0::2], buf[1::2]):
                        if isinstance(src, bytearray):
                            self.map[bytes(src)] = _utf16(dst) if isinstance(dst, bytearray) \
                                else _glyph(str(dst))
                elif mode == "beginbfrange":
                    for lo, hi, dst in zip(buf[0::3], buf[1::3], buf[2::3]):
                        if not (isinstance(lo, bytearray) and isinstance(hi, bytearray)):
                            continue
                        a, b, width = int.from_bytes(lo, "big"), int.from_bytes(hi, "big"), len(lo)
                        if b < a or b - a > 0xFFFF:
                            continue
                        for i in range(b - a + 1):
                            key = (a + i).to_bytes(width, "big")
                            if isinstance(dst, list):
                                if i < len(dst) and isinstance(dst[i], bytearray):
                                    self.map[key] = _utf16(dst[i])
                            elif isinstance(dst, bytearray) and dst:
                                base = int.from_bytes(dst, "big") + i
                                self.map[key] = _utf16(base.to_bytes(len(dst), "big"))
                mode = ""
            elif mode:
                buf.append(t)
        self.ranges.sort()

    def decode(self, data: bytes) -> str:
        data = bytes(data)
        if self.utf16:
            return _utf16(data)
        out, i, n = [], 0, len(data)
        while i < n:
            width = self.ranges[0][0]
            for w, lo, hi in self.ranges:
                if i + w <= n and lo <= int.from_bytes(data[i:i + w], "big") <= hi:
                    width = w
                    break
            code = data[i:i + width]
            i += width
            if code in self.map:
                out.append(self.map[code])
                self.mapped += 1
            elif not self.type0 and len(code) == 1 and code[0] in self.simple:
                out.append(self.simple[code[0]])
                self.mapped += 1
            else:
                self.unmapped += 1
        return "".join(out)


# ---------------------------------------------------------------- 内容流：排出文字
def _mul(a: list, b: list) -> list:
    return [a[0] * b[0] + a[1] * b[2], a[0] * b[1] + a[1] * b[3],
            a[2] * b[0] + a[3] * b[2], a[2] * b[1] + a[3] * b[3],
            a[4] * b[0] + a[5] * b[2] + b[4], a[4] * b[1] + a[5] * b[3] + b[5]]


IDENTITY = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]


GAP = "\u0000"          # 同一行内的跳格标记


def _fix_radicals(text: str) -> str:
    """不少中文字体把"文""人"之类映射到康熙部首（U+2F00 起），看着一样但搜不到，换回常用字。"""
    return re.sub("[\u2e80-\u2fdf]", lambda m: unicodedata.normalize("NFKC", m.group()), text)


def _is_word_char(ch: str) -> bool:
    return bool(ch) and ch.isascii() and (ch.isalnum() or ch in ".,;:!?)")


class TextSink:
    """收集文字：换行看基线 y 有没有变，同一行内英文单词之间补空格。"""

    def __init__(self):
        self.parts: list[str] = []
        self.last_y: float | None = None
        self.images = 0

    def emit(self, text: str, y: float, size: float, gap: bool = False) -> None:
        if not text:
            return
        if self.last_y is not None and abs(y - self.last_y) > max(size * 0.5, 1.0):
            self.parts.append("\n")
        elif gap:
            self.parts.append(GAP)
        self.parts.append(text)
        self.last_y = y

    def text(self) -> str:
        raw = "".join(self.parts)
        # 跳格只在两个英文/数字之间变成空格，中文之间直接连上
        raw = re.sub(f"{GAP}+", lambda m: " " if _is_word_char(raw[m.start() - 1:m.start()])
                     and _is_word_char(raw[m.end():m.end() + 1]) else "", raw)
        lines = [re.sub(r"[ \t\u00a0]+", " ", line).strip() for line in _fix_radicals(raw).split("\n")]
        out, blank = [], 0
        for line in lines:
            if line:
                out.append(line)
                blank = 0
            elif out and blank == 0:
                out.append("")
                blank = 1
        return "\n".join(out).strip()


class ContentReader:
    def __init__(self, doc: PdfDoc):
        self.doc = doc
        self.fonts: dict[int, FontDecoder] = {}

    def font(self, resources: dict, name: str) -> FontDecoder | None:
        fonts = self.doc.dict_of(resources.get("Font"))
        ref = fonts.get(name)
        key = ref[0] if isinstance(ref, Ref) else id(ref)
        if key not in self.fonts:
            font = self.doc.dict_of(ref)
            if not font:
                return None
            self.fonts[key] = FontDecoder(font, self.doc)
        return self.fonts[key]

    def run(self, data: bytes, resources: dict, sink: TextSink, ctm: list,
            depth: int = 0, seen: frozenset = frozenset()) -> None:
        lex = Lexer(data)
        ops: list = []
        stack: list[list] = []
        tm, tlm = IDENTITY[:], IDENTITY[:]
        font, size, leading = None, 0.0, 0.0
        n = len(data)

        def show(text: str, gap: bool = False) -> None:
            m = _mul(tm, ctm)
            scale = (m[2] ** 2 + m[3] ** 2) ** 0.5 or 1.0
            sink.emit(text, m[5], abs(size) * scale, gap)

        def newline() -> None:
            nonlocal tlm, tm
            tlm = _mul([1, 0, 0, 1, 0, -leading], tlm)
            tm = tlm[:]

        while lex.pos < n:
            tok = lex.token()
            if tok is None:
                break
            if not isinstance(tok, Keyword) or tok in ("<<", "["):
                ops.append(lex.parse(tok) if isinstance(tok, Keyword) else tok)
                continue
            op = str(tok)
            try:
                if op == "q":
                    stack.append(ctm[:])
                elif op == "Q":
                    ctm = stack.pop() if stack else ctm
                elif op == "cm" and len(ops) >= 6:
                    ctm = _mul([float(x) for x in ops[-6:]], ctm)
                elif op == "BT":
                    tm, tlm = IDENTITY[:], IDENTITY[:]
                elif op == "Tf" and len(ops) >= 2:
                    font = self.font(resources, str(ops[-2]))
                    size = float(ops[-1])
                elif op == "TL" and ops:
                    leading = float(ops[-1])
                elif op in ("Td", "TD") and len(ops) >= 2:
                    tx, ty = float(ops[-2]), float(ops[-1])
                    if op == "TD":
                        leading = -ty
                    tlm = _mul([1, 0, 0, 1, tx, ty], tlm)
                    tm = tlm[:]
                    if ty == 0 and tx > 0:
                        sink.parts.append(GAP)                # 同一行内的跳格，稍后按两侧字符处理
                elif op == "Tm" and len(ops) >= 6:
                    tlm = [float(x) for x in ops[-6:]]
                    tm = tlm[:]
                elif op == "T*":
                    newline()
                elif op in ("Tj", "'", '"') and ops and font:
                    if op != "Tj":
                        newline()
                    if isinstance(ops[-1], (bytes, bytearray)):
                        show(font.decode(ops[-1]))
                elif op == "TJ" and ops and isinstance(ops[-1], list) and font:
                    gap = False
                    for item in ops[-1]:
                        if isinstance(item, (bytes, bytearray)):
                            show(font.decode(item), gap)
                            gap = False
                        elif isinstance(item, (int, float)) and item < -200:
                            gap = True
                elif op == "Do" and ops:
                    self._xobject(resources, str(ops[-1]), sink, ctm, depth, seen)
                elif op == "BI":
                    m = re.compile(rb"\sID\s").search(data, lex.pos)
                    e = re.compile(rb"\sEI(\s|$)").search(data, m.end() if m else lex.pos)
                    lex.pos = e.end() if e else n
                    sink.images += 1
            except (TypeError, ValueError, IndexError):
                pass
            ops = []

    def _xobject(self, resources, name, sink, ctm, depth, seen) -> None:
        ref = self.doc.dict_of(resources.get("XObject")).get(name)
        obj = self.doc.resolve(ref)
        if not isinstance(obj, Stream):
            return
        if obj.get("Subtype") == "Image":
            sink.images += 1
            return
        key = ref[0] if isinstance(ref, Ref) else id(obj)
        if obj.get("Subtype") != "Form" or depth > 6 or key in seen:
            return
        try:
            data = _decode_stream(obj, self.doc)
        except (PdfError, ValueError, zlib.error):
            return
        matrix = self.doc.resolve(obj.get("Matrix"))
        inner = _mul([float(x) for x in matrix], ctm) if isinstance(matrix, list) \
            and len(matrix) == 6 else ctm
        res = self.doc.dict_of(obj.get("Resources")) or resources
        self.run(data, res, sink, inner, depth + 1, seen | {key})


# ---------------------------------------------------------------- 对外接口
MAX_PAGES = 2000


def pdf_to_text(data: bytes) -> tuple[str, dict]:
    """返回（按页拼好的文字，统计信息）。导入不了时抛 PdfError，消息可直接给用户看。"""
    try:
        doc = PdfDoc(data)
    except RecursionError:
        raise PdfError("PDF 结构嵌套过深，无法解析") from None
    if doc.encrypted:
        raise PdfError("这份 PDF 已加密（设了打开密码或权限保护），读不出文字。"
                       "请在阅读器里另存为不加密的 PDF 后再导入")
    pages = doc.pages()
    if not pages:
        raise PdfError("PDF 结构无法识别：没有找到任何页面，文件可能已损坏")
    if len(pages) > MAX_PAGES:
        raise PdfError(f"PDF 超过 {MAX_PAGES} 页，请拆分后再导入")
    reader = ContentReader(doc)
    blocks, text_pages, images, content_bytes = [], 0, 0, 0
    for index, (page, resources) in enumerate(pages, 1):
        contents = doc.resolve(page.get("Contents"))
        streams = contents if isinstance(contents, list) else [contents]
        raw = b""
        for s in streams:
            s = doc.resolve(s)
            if isinstance(s, Stream):
                try:
                    raw += _decode_stream(s, doc) + b"\n"
                except (PdfError, ValueError, zlib.error):
                    continue
        content_bytes += len(raw.strip())
        sink = TextSink()
        reader.run(raw, resources, sink, IDENTITY[:])
        images += sink.images
        text = sink.text()
        if text:
            text_pages += 1
            blocks.append(f"## 第 {index} 页\n\n{text}")
    mapped = sum(f.mapped for f in reader.fonts.values())
    unmapped = sum(f.unmapped for f in reader.fonts.values())
    info = {"pages": len(pages), "text_pages": text_pages, "images": images,
            "unmapped": unmapped}
    if not blocks:
        if not content_bytes:
            raise PdfError("PDF 页面内容缺失，文件可能已损坏或没有下载完整")
        if unmapped:
            raise PdfError("这份 PDF 的字体没有提供文字映射（ToUnicode），抽不出可读文字。"
                           "可以用 Word 或 WPS 打开后另存为 .docx / .txt 再导入")
        raise PdfError("这份 PDF 没有文字层，可能是扫描件或纯图片，本系统不做文字识别（OCR）。"
                       "请导入文字版 PDF，或先转成 TXT / MD / Word")
    if unmapped > mapped:
        raise PdfError("这份 PDF 大部分文字的字体没有提供文字映射，抽出来会是乱码。"
                       "可以用 Word 或 WPS 打开后另存为 .docx / .txt 再导入")
    return "\n\n".join(blocks) + "\n", info
