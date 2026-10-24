#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""内置科目与章节种子数据。

设计文档 5.1：暂定四个科目（计算机组成原理、计算机网络、操作系统、数据结构），
按章节划分，每章有大纲讲解与题目。大纲先内置一份可用的骨架，
配置 API Key 后可以逐章让模型扩写成完整讲解；题目按需调用模型生成并缓存在本地。
"""

from __future__ import annotations

from pathlib import Path

from store import new_id

SUBJECTS = [
    {
        "slug": "co", "name": "计算机组成原理",
        "chapters": [
            ("数据表示与运算", [
                "定点数与浮点数的表示：原码、补码、IEEE 754",
                "补码运算为什么能把减法变加法",
                "溢出判断与移位运算",
                "浮点加减法：对阶、尾数运算与规格化",
            ]),
            ("存储系统", [
                "存储器层次：寄存器—Cache—主存—辅存",
                "Cache 的三种映射方式与替换算法",
                "局部性原理如何决定命中率",
                "虚拟存储器与页表、TLB 的关系",
            ]),
            ("指令系统", [
                "指令格式与寻址方式",
                "CISC 与 RISC 的设计取舍",
                "指令流水线的三类冲突",
                "数据冒险的转发与停顿",
            ]),
            ("CPU 与总线", [
                "单周期与多周期数据通路",
                "控制器：硬布线 vs 微程序",
                "总线的仲裁与定时",
                "中断与 DMA 的区别",
            ]),
        ],
    },
    {
        "slug": "cn", "name": "计算机网络",
        "chapters": [
            ("分层模型", [
                "OSI 七层与 TCP/IP 四层的对应关系",
                "封装与解封装的过程",
                "每层负责什么、不负责什么",
                "为什么分层能简化设计",
            ]),
            ("链路层与物理层", [
                "编码、调制与信道容量",
                "以太网帧结构与 MAC 地址",
                "CSMA/CD 与交换机的自学习",
                "差错检测：奇偶校验与 CRC",
            ]),
            ("网络层", [
                "IPv4 地址、子网掩码与 CIDR",
                "IP 分片与 MTU",
                "路由表与最长前缀匹配",
                "NAT 与 ARP 的工作方式",
            ]),
            ("传输层", [
                "TCP 三次握手与四次挥手",
                "滑动窗口、流量控制与拥塞控制",
                "UDP 的适用场景",
                "为什么 TCP 建立连接要三次而不是两次",
            ]),
            ("应用层", [
                "HTTP 报文结构与状态码",
                "HTTP/1.1、HTTP/2 与 HTTP/3 的差别",
                "DNS 递归查询与迭代查询",
                "HTTPS 中 TLS 握手做了什么",
            ]),
        ],
    },
    {
        "slug": "os", "name": "操作系统",
        "chapters": [
            ("进程与线程", [
                "进程控制块与进程状态转换",
                "线程共享与独享的资源",
                "上下文切换的代价",
                "用户级线程与内核级线程",
            ]),
            ("调度", [
                "FCFS、SJF、优先级、时间片轮转",
                "周转时间与响应时间的权衡",
                "多级反馈队列为什么实用",
                "抢占式与非抢占式的区别",
            ]),
            ("同步与死锁", [
                "临界区与互斥的四个必要条件",
                "信号量与 PV 操作",
                "死锁的四个必要条件与处理策略",
                "银行家算法的思路",
            ]),
            ("内存管理", [
                "分页、分段与段页式",
                "页面置换：FIFO、LRU、OPT",
                "Belady 异常为什么会发生",
                "缺页中断的处理流程",
            ]),
            ("文件系统", [
                "inode 与目录项",
                "连续、链接、索引三种分配方式",
                "磁盘调度：FCFS、SSTF、SCAN",
                "日志文件系统如何保证一致性",
            ]),
        ],
    },
    {
        "slug": "ds", "name": "数据结构",
        "chapters": [
            ("线性表", [
                "顺序表与链表的存储差异",
                "单链表、双链表、循环链表",
                "头结点带来的便利",
                "插入删除的复杂度分析",
            ]),
            ("栈与队列", [
                "栈的 LIFO 特性与典型应用",
                "队列与循环队列的判空判满",
                "表达式求值与括号匹配",
                "用两个栈实现队列",
            ]),
            ("树", [
                "二叉树的三种遍历与递归本质",
                "二叉搜索树的查找、插入、删除",
                "平衡二叉树与 AVL 旋转",
                "堆与优先队列",
            ]),
            ("图", [
                "邻接矩阵与邻接表的取舍",
                "DFS 与 BFS 的应用场景",
                "最小生成树：Prim 与 Kruskal",
                "最短路径：Dijkstra 与 Floyd",
            ]),
            ("排序与查找", [
                "比较排序的下界为什么是 O(n log n)",
                "快排的分区与最坏情况",
                "归并排序与外部排序",
                "哈希冲突处理与装填因子",
            ]),
        ],
    },
]


def seed(store) -> None:
    """只在空库时写入，避免覆盖用户后来的修改。"""
    if store.subjects():
        return
    for s_ord, subject in enumerate(SUBJECTS):
        sid = new_id()
        store.conn.execute(
            "INSERT INTO subjects(id, slug, name, ord) VALUES(?,?,?,?)",
            (sid, subject["slug"], subject["name"], s_ord))
        for c_ord, (title, outline_items) in enumerate(subject["chapters"]):
            outline = "\n".join(f"- {item}" for item in outline_items)
            store.conn.execute(
                "INSERT INTO chapters(id, subject_id, title, ord, outline) VALUES(?,?,?,?,?)",
                (new_id(), sid, title, c_ord, outline))
    store.conn.commit()

SAMPLE_DIR = Path(__file__).resolve().parent / "samples"

# 资料目录结构：一个共识文件夹 + 四个学科文件夹。
# 共识文件夹放跨科目通用材料（不推荐用户修改，但允许改）。
FOLDERS = [
    {"slug": "shared", "name": "共识资料", "is_shared": True,
     "desc": "跨科目通用材料：课程地图、学习方法、基础概念速查"},
    {"slug": "co", "name": "计算机组成原理", "is_shared": False, "desc": "计组课件、笔记、习题"},
    {"slug": "cn", "name": "计算机网络", "is_shared": False, "desc": "计网课件、笔记、习题"},
    {"slug": "os", "name": "操作系统", "is_shared": False, "desc": "操作系统课件、笔记、习题"},
    {"slug": "ds", "name": "数据结构", "is_shared": False, "desc": "数据结构课件、笔记、习题"},
]


def ensure_folders(store) -> int:
    """建立/补齐五个标准文件夹，返回新建数量。"""
    created = 0
    for i, f in enumerate(FOLDERS):
        if store.folder_by_slug(f["slug"]):
            continue
        store.add_folder(name=f["name"], slug=f["slug"],
                         is_shared=f["is_shared"], ord=i)
        created += 1
    return created


def seed_samples(store) -> int:
    """库里还没有任何资料时，导入内置示例资料，保证首次启动就能演示检索与引用。"""
    import rag

    if store.list_materials() or not SAMPLE_DIR.exists():
        return 0
    count = 0
    shared_folder = store.folder_by_slug("shared") or {}
    folders = {f["slug"]: f for f in store.list_folders()}
    subjects = {s["name"]: s["slug"] for s in store.subjects()}

    # 共识资料：samples/shared/*.md
    shared_dir = SAMPLE_DIR / "shared"
    if shared_dir.exists():
        for path in sorted(shared_dir.glob("*.md")):
            text = path.read_text(encoding="utf-8", errors="replace")
            title = path.stem.replace("共识-", "")
            material = store.add_material(
                title=f"共识 · {title}", text=text, subject="",
                folder_id=shared_folder.get("id", ""),
                source_url="内置示例资料（可删除）", ext=".md")
            store.replace_chunks(material["id"], rag.chunk_text(text))
            count += 1

    # 学科资料：samples/*.md，文件名前缀是科目
    for path in sorted(SAMPLE_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        subject, _, topic = path.stem.partition("-")
        folder = folders.get(subjects.get(subject, ""), {})
        material = store.add_material(
            title=f"{subject} · {topic or path.stem}", text=text, subject=subject,
            folder_id=folder.get("id", ""),
            source_url="内置示例资料（可删除）", ext=".md")
        store.replace_chunks(material["id"], rag.chunk_text(text))
        count += 1
    return count


def reorganize(store) -> int:
    """把散落在根目录的资料按科目归位，返回移动数量。"""
    return store.assign_orphan_materials()

def import_shared_samples(store) -> int:
    """导入 samples/shared 下的共识资料（按标题去重，可重复调用）。"""
    import rag

    shared_dir = SAMPLE_DIR / "shared"
    folder = store.folder_by_slug("shared")
    if not shared_dir.exists() or not folder:
        return 0
    existing = {m["title"] for m in store.list_materials()}
    count = 0
    for path in sorted(shared_dir.glob("*.md")):
        title = f"共识 · {path.stem.replace('共识-', '')}"
        if title in existing:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        material = store.add_material(
            title=title, text=text, subject="", folder_id=folder["id"],
            source_url="内置示例资料（可删除）", ext=".md")
        store.replace_chunks(material["id"], rag.chunk_text(text))
        count += 1
    return count
