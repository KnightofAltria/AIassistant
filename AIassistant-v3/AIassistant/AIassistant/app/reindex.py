#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重建全部资料的检索索引（切片）。

改过切片规则（例如升级了 rag.chunk_text）之后跑一次：
    python reindex.py

服务运行中也能跑，但建议先停服务，避免数据库写锁。
"""

from __future__ import annotations

import sys

import rag
from store import Store


def main() -> int:
    store = Store()
    materials = store.list_materials()
    if not materials:
        print("没有资料，无需重建。")
        return 0
    for m in materials:
        text = store.get_material_text(m["id"])
        if not text:
            print(f"[跳过] {m['title']}：文件不存在")
            continue
        chunks = rag.chunk_text(text)
        store.replace_chunks(m["id"], chunks)
        print(f"[OK] {m['title']} → {len(chunks)} 片")
    total = store.stats()["chunks"]
    print(f"\n完成，共 {len(materials)} 份资料、{total} 个切片。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
