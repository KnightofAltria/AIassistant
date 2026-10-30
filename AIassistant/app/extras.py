#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""扩展能力：间隔重复调度、docx 读写、学习报告生成。

这一层故意不依赖任何第三方库：
  · SRS 调度是纯函数，方便单测；
  · docx 读 = zipfile + ElementTree 解 word/document.xml；
  · docx 写 = 手工拼最小 OOXML 包（[Content_Types].xml + _rels/.rels + word/document.xml）。

学习报告写成 Word，是为了和课程交付文档体系（python-docx 那套）保持同一种产物形态，
但本模块自身不依赖 python-docx，保证 app 目录仍然可以"拷走就能跑"。
"""

from __future__ import annotations

import base64
import io
import re
import zipfile
from datetime import datetime, timedelta
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

# ---------------------------------------------------------------- 间隔重复（SRS）
# 阶段 → 间隔天数。0 表示"刚学会，今天再看一次"。
SRS_INTERVALS = (0, 1, 3, 7, 15, 30)
MAX_STAGE = len(SRS_INTERVALS) - 1


def srs_next(stage: int, quality: str, now: datetime | None = None) -> tuple[int, datetime]:
    """根据评分算出下一个阶段与到期时间。

    quality：
        again  没想起来 —— 退回上一阶段，10 分钟后再看
        good   想起来了 —— 前进一阶段
        easy   太简单   —— 前进两阶段
    """
    stage = max(0, min(int(stage or 0), MAX_STAGE))
    now = now or datetime.now()
    if quality == "again":
        stage = max(0, stage - 1)
        return stage, now + timedelta(minutes=10)
    if quality == "easy":
        stage = min(MAX_STAGE, stage + 2)
    else:
        stage = min(MAX_STAGE, stage + 1)
    return stage, now + timedelta(days=SRS_INTERVALS[stage] or 1)


def srs_label(stage: int) -> str:
    days = SRS_INTERVALS[max(0, min(int(stage or 0), MAX_STAGE))]
    return f"{days} 天后" if days else "今天"


# ---------------------------------------------------------------- docx 读取
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def docx_to_text(data: bytes) -> str:
    """把 .docx 的正文抽成纯文本：段落之间空一行，表格单元格用空格连接。"""
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = set(zf.namelist())
        if "word/document.xml" not in names:
            raise ValueError("不是有效的 .docx（缺少 word/document.xml）")
        xml = zf.read("word/document.xml")
    root = ET.fromstring(xml)
    lines: list[str] = []
    for p in root.iter(_W + "p"):
        texts = [(t.text or "") for t in p.iter(_W + "t")]
        line = "".join(texts).strip()
        if line:
            lines.append(line)
    return "\n\n".join(lines)


# ---------------------------------------------------------------- docx 写出
def _run(text: str, bold: bool = False, size: int = 21, color: str = "") -> str:
    """一个 w:r。size 单位是半磅（21 = 10.5pt 五号）。中文字体必须同时给 eastAsia。"""
    rpr = ['<w:rFonts w:ascii="Microsoft YaHei" w:hAnsi="Microsoft YaHei" '
           'w:eastAsia="Microsoft YaHei"/>']
    if bold:
        rpr.append("<w:b/>")
    if color:
        rpr.append(f'<w:color w:val="{color}"/>')
    rpr.append(f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>')
    return (f'<w:r><w:rPr>{"".join(rpr)}</w:rPr>'
            f'<w:t xml:space="preserve">{escape(text)}</w:t></w:r>')


def _para(text: str = "", style: str = "", bold: bool = False, size: int = 21,
          color: str = "", bullet: bool = False, align: str = "") -> str:
    ppr = []
    if style:
        ppr.append(f'<w:pStyle w:val="{style}"/>')
    if bullet:
        ppr.append('<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>')
    if align:
        ppr.append(f'<w:jc w:val="{align}"/>')
    ppr.append('<w:spacing w:before="60" w:after="60" w:line="300" w:lineRule="auto"/>')
    body = _run(text, bold=bold, size=size, color=color) if text else ""
    return f"<w:p><w:pPr>{''.join(ppr)}</w:pPr>{body}</w:p>"


def _table(rows: list[list[str]], header: bool = True) -> str:
    if not rows:
        return ""
    cols = max(len(r) for r in rows)
    width = int(9000 / cols)
    grid = "".join(f'<w:gridCol w:w="{width}"/>' for _ in range(cols))
    out = ['<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/>'
           '<w:tblW w:w="9000" w:type="dxa"/><w:tblBorders>'
           '<w:top w:val="single" w:sz="6" w:color="BFBFBF"/>'
           '<w:left w:val="single" w:sz="6" w:color="BFBFBF"/>'
           '<w:bottom w:val="single" w:sz="6" w:color="BFBFBF"/>'
           '<w:right w:val="single" w:sz="6" w:color="BFBFBF"/>'
           '<w:insideH w:val="single" w:sz="6" w:color="BFBFBF"/>'
           '<w:insideV w:val="single" w:sz="6" w:color="BFBFBF"/>'
           '</w:tblBorders></w:tblPr>', f"<w:tblGrid>{grid}</w:tblGrid>"]
    for ri, row in enumerate(rows):
        cells = []
        for ci in range(cols):
            text = row[ci] if ci < len(row) else ""
            shade = ('<w:shd w:val="clear" w:fill="EEF3FA"/>'
                     if header and ri == 0 else "")
            cells.append(
                f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/>{shade}</w:tcPr>'
                f'{_para(str(text), bold=(header and ri == 0), size=19)}</w:tc>')
        out.append(f"<w:tr>{''.join(cells)}</w:tr>")
    out.append("</w:tbl>")
    return "".join(out)


def build_docx(title: str, blocks: list[tuple]) -> bytes:
    """blocks 元素：("h1"|"h2"|"h3"|"p"|"small"|"bullet"|"table", 内容)。"""
    body: list[str] = []
    body.append(_para(title, bold=True, size=36, align="center"))
    for kind, content in blocks:
        if kind == "h1":
            body.append(_para(str(content), bold=True, size=28, color="1F4E79"))
        elif kind == "h2":
            body.append(_para(str(content), bold=True, size=24, color="2E75B6"))
        elif kind == "h3":
            body.append(_para(str(content), bold=True, size=21))
        elif kind == "small":
            body.append(_para(str(content), size=18, color="808080"))
        elif kind == "bullet":
            body.append(_para(str(content), bullet=True))
        elif kind == "table":
            body.append(_table(content))
        else:
            body.append(_para(str(content)))

    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W_NS}" xmlns:r="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships"><w:body>'
        + "".join(body)
        + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
          '<w:pgMar w:top="1440" w:right="1300" w:bottom="1440" w:left="1300" '
          'w:header="851" w:footer="992" w:gutter="0"/></w:sectPr>'
          '</w:body></w:document>'
    )
    numbering = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:numbering xmlns:w="{W_NS}"><w:abstractNum w:abstractNumId="0">'
        '<w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="bullet"/>'
        '<w:lvlText w:val="•"/><w:lvlJc w:val="left"/><w:pPr>'
        '<w:ind w:left="420" w:hanging="240"/></w:pPr></w:lvl></w:abstractNum>'
        '<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num></w:numbering>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
        'relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.'
        'openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/numbering.xml" ContentType="application/vnd.'
        'openxmlformats-officedocument.wordprocessingml.numbering+xml"/>'
        '</Types>'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/'
        '2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>'
    )
    doc_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/'
        '2006/relationships/numbering" Target="numbering.xml"/></Relationships>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("word/document.xml", document)
        zf.writestr("word/_rels/document.xml.rels", doc_rels)
        zf.writestr("word/numbering.xml", numbering)
    return buf.getvalue()


# ---------------------------------------------------------------- 学习报告
def build_report(store, usage_days: int = 14) -> bytes:
    """把掌握度、错题、复习计划、用量拼成一份可直接交给老师的 Word 报告。"""
    stats = store.stats()
    mastery = store.mastery()
    mistakes = store.list_mistakes()[:12]
    due = store.list_due_reviews(limit=20)
    usage = store.usage_stats(days=usage_days)
    streak = store.streak()
    title = f"学习报告 · {datetime.now():%Y-%m-%d}"
    blocks: list[tuple] = [
        ("small", f"生成时间：{datetime.now():%Y-%m-%d %H:%M}　·　"
                  f"连续学习 {streak['days']} 天　·　资料 {stats['materials']} 份"
                  f"　·　切片 {stats['chunks']} 段"),
        ("h1", "一、掌握度总览"),
        ("table", [["科目 / 章节", "作答", "正确率", "状态"]] + [
            [m["label"], str(m["attempts"]), f"{m['rate']}%", m["status"]]
            for m in mastery["chapters"][:20]]),
        ("small", "状态口径：未练习（0 次作答）／薄弱（正确率 < 60%）／"
                  "巩固中（60%~84%）／已掌握（≥ 85%）。"),
        ("h1", "二、今日复习队列"),
    ]
    if due:
        blocks.append(("table", [["题目", "科目", "到期", "阶段"]] + [
            [d["stem"][:40], d.get("subject", ""), d["due_at"][:16], srs_label(d["stage"])]
            for d in due]))
    else:
        blocks.append(("p", "当前没有到期需要复习的条目。做完练习或积累错题后会自动排入。"))
    blocks.append(("h1", "三、错题与薄弱点"))
    if mistakes:
        blocks.append(("table", [["科目", "题干", "你的答案", "正确答案"]] + [
            [m.get("subject", ""), m["stem"][:36], m.get("my_answer", ""),
             m.get("right_answer", "")] for m in mistakes]))
    else:
        blocks.append(("p", "错题本为空。"))
    blocks.append(("h1", "四、模型调用与耗时"))
    blocks.append(("table", [["指标", "数值"], ["调用次数", str(usage["calls"])],
                             ["估算 token", str(usage["tokens_est"])],
                             ["平均首字延迟", f"{usage['avg_first_ms']} ms"],
                             ["平均总耗时", f"{usage['avg_total_ms']} ms"]]))
    blocks.append(("h1", "五、数据来源说明"))
    blocks.append(("p", "本报告由本地程序根据 SQLite 库中的作答记录、错题记录与调用日志自动生成，"
                        "未做任何人工润色；若某项为 0，表示确实没有数据，而非未统计。"))
    return build_docx(title, blocks)


def b64decode(text: str) -> bytes:
    """前端上传 docx 时用的是 base64；容忍 dataURL 前缀。"""
    text = (text or "").strip()
    if text.startswith("data:") and "," in text:
        text = text.split(",", 1)[1]
    text = re.sub(r"\s+", "", text)
    return base64.b64decode(text + "=" * (-len(text) % 4))
