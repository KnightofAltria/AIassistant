#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""轻量检查：不调模型、不动用户数据，几秒钟跑完。

会用一个**临时库**做审核隔离与索引版本的回归，跑完立即删除，不碰 data/ 里的真实数据。

日常改完代码用它；只有在交付前或改动涉及模型链路时，才需要跑 selftest.py。

    python check.py                 # 静态 + 只读接口
    python check.py --base http://127.0.0.1:8737

与 selftest.py 的分工：
    check.py    零成本，随时跑：语法、静态资源、只读接口、页面关键元素
    selftest.py 有成本（会调用模型、写测试数据），只在交付前跑一次
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

APP = Path(__file__).resolve().parent
STATIC = APP / "static"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{('  ' + detail) if detail else ''}")


def get(base: str, path: str, timeout: float = 10.0):
    with urllib.request.urlopen(base + path, timeout=timeout) as resp:
        return resp.status, resp.read()


# ---------------------------------------------------------------- 静态检查
def check_python_syntax() -> None:
    bad = []
    for path in sorted(APP.glob("*.py")) + sorted((APP.parent / "auth_server").glob("*.py")):
        proc = subprocess.run([sys.executable, "-m", "py_compile", str(path)],
                              capture_output=True)
        if proc.returncode != 0:
            bad.append(path.name)
    check("Python 语法", not bad, "全部通过" if not bad else f"失败：{bad}")


def check_js_syntax() -> None:
    node = shutil.which("node")
    if not node:
        check("JavaScript 语法", True, "未安装 node，跳过")
        return
    bad = []
    for path in sorted(STATIC.glob("*.js")):
        proc = subprocess.run([node, "--check", str(path)], capture_output=True)
        if proc.returncode != 0:
            bad.append(path.name)
    check("JavaScript 语法", not bad, "全部通过" if not bad else f"失败：{bad}")


def check_no_duplicate_decls() -> None:
    """防止再次出现"整段代码被写入两遍"导致白屏。"""
    import re
    seen: dict[str, str] = {}
    dup = []
    for path in sorted(STATIC.glob("*.js")):
        js = path.read_text(encoding="utf-8")
        for m in re.finditer(r"^(?:async )?function (\w+)|^const (\w+)\s*=", js, re.M):
            name = m.group(1) or m.group(2)
            if name in seen and seen[name] != path.name:
                dup.append(f"{name}({seen[name]}/{path.name})")
            seen[name] = path.name
    check("前端无重复声明", not dup, "无" if not dup else "；".join(dup))


def check_html_balance() -> None:
    import re
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    opens = len(re.findall(r"<div\b", html))
    closes = len(re.findall(r"</div>", html))
    check("HTML div 配平", opens == closes, f"{opens}/{closes}")


def check_store_extensions() -> None:
    """零成本回归：审核隔离 + 索引版本失效。

    用临时库和临时资料目录，跑完删干净，不碰用户的 data/。
    这两条对应 GPT 独立测试报出的两个真实缺陷，留成回归防止改回去。
    """
    import shutil as _shutil
    import tempfile

    import rag as rag_mod
    import store as store_mod

    tmp = Path(tempfile.mkdtemp(prefix="csla-check-"))
    old_dir = store_mod.MATERIAL_DIR
    store_mod.MATERIAL_DIR = tmp / "materials"
    try:
        st = store_mod.Store(tmp / "t.db")
        mat = st.add_material("审核隔离测试", "alphaunique", ext=".md")
        st.replace_chunks(mat["id"], ["alphaunique"])
        visible_before = any(c["material_id"] == mat["id"] for c in st.all_chunks())
        rev_approved = st.rev()

        st.set_material_status(mat["id"], "pending")
        hidden = not any(c["material_id"] == mat["id"] for c in st.all_chunks())
        check("待审核资料不进检索索引", visible_before and hidden,
              f"通过时可见={visible_before}，待审核时可见={not hidden}")
        check("审核状态变化使索引版本递增", st.rev() > rev_approved,
              f"{rev_approved} -> {st.rev()}")

        st.set_material_status(mat["id"], "approved")
        rev_before_replace = st.rev()
        # 切片数量不变、内容完全换掉：按"数量"判缓存的老实现察觉不到
        st.replace_chunks(mat["id"], ["betaunique"])
        check("内容变更但切片数不变也使版本递增", st.rev() > rev_before_replace,
              f"{rev_before_replace} -> {st.rev()}")

        old_hit = bool(rag_mod.Retriever(st.all_chunks()).search("alphaunique"))
        new_hit = bool(rag_mod.Retriever(st.all_chunks()).search("betaunique"))
        check("重建索引后命中新内容、不再命中旧内容", new_hit and not old_hit,
              f"新内容命中={new_hit}，旧内容仍命中={old_hit}")

        server_src = (APP / "server.py").read_text(encoding="utf-8")
        check("检索缓存按索引版本失效（非切片数）", "STORE.rev()" in server_src,
              "get_retriever 使用 rev()" if "STORE.rev()" in server_src else "仍在用切片数量")
    finally:
        store_mod.MATERIAL_DIR = old_dir
        _shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- 只读接口
def login_state(base: str) -> tuple[bool, dict]:
    """返回（是否已进入账号数据，/api/state 里的 auth 字段）。"""
    _, body = get(base, "/api/state")
    auth = json.loads(body or b"{}").get("auth") or {}
    return bool(auth.get("logged_in", True)), auth


def check_auth_gate(base: str) -> None:
    """未登录时：账号数据接口一律 401 auth_required，开放接口照常可用。"""
    for path in ("/api/subjects", "/api/materials", "/api/profile", "/api/conversations"):
        try:
            status, _ = get(base, path)
            check(f"未登录 GET {path} 被拦截", False, f"返回了 {status}")
        except urllib.error.HTTPError as exc:
            code = (json.loads(exc.read() or b"{}").get("error") or {}).get("code", "")
            check(f"未登录 GET {path} 被拦截", exc.code == 401 and code == "auth_required",
                  f"{exc.code} {code}")
        except urllib.error.URLError as exc:
            check(f"未登录 GET {path} 被拦截", False, f"服务未启动？{exc.reason}")
            return
    try:
        status, body = get(base, "/api/auth/status")
        auth = json.loads(body or b"{}")
        check("GET /api/auth/status", status == 200 and auth.get("enabled") is True,
              f"认证服务 {auth.get('auth_server', '')}")
    except urllib.error.URLError as exc:
        check("GET /api/auth/status", False, str(exc))


def check_api(base: str) -> None:
    endpoints = [
        ("/api/state", "状态"),
        ("/api/subjects", "科目树"),
        ("/api/materials", "资料与文件夹"),
        ("/api/conversations", "会话列表"),
        ("/api/summaries", "总结列表"),
        ("/api/mistakes", "错题列表"),
        ("/api/profile", "学习者档案"),
        ("/api/dashboard", "学习看板"),
        ("/api/review", "复习队列"),
        ("/api/usage", "用量统计"),
        ("/api/search?q=%E4%B8%AD%E6%96%AD", "全文检索"),
        ("/api/materials/pending", "待审核资料"),
        ("/api/graph", "知识图谱"),
        ("/api/activity", "学习热力图"),
    ]
    for path, name in endpoints:
        try:
            status, body = get(base, path)
            ok = status == 200 and bool(json.loads(body or b"{}"))
            check(f"GET {path}（{name}）", ok, f"{len(body)} 字节")
        except urllib.error.URLError as exc:
            check(f"GET {path}（{name}）", False, f"服务未启动？{exc.reason}")
            return


def check_assets(base: str) -> None:
    for path in ("/", "/app.js", "/extras.js", "/agent.js", "/landing.js",
                 "/keepalive.js", "/auth.js", "/style.css"):
        try:
            status, body = get(base, path)
            check(f"GET {path}", status == 200 and len(body) > 200, f"{len(body)} 字节")
        except urllib.error.URLError:
            check(f"GET {path}", False, "服务未启动")
            return


def check_page_markers(base: str) -> None:
    try:
        _, body = get(base, "/")
    except urllib.error.URLError:
        check("首页关键元素", False, "服务未启动")
        return
    html = body.decode("utf-8", "replace")
    markers = {
        "欢迎界面": 'id="landing"',
        "粒子画布": 'id="particles"',
        "开始学习按钮": 'id="btn-start"',
        "首页入口": 'id="view-home"',
        "个人信息页": 'id="view-profile"',
        "资料管理": 'id="view-materials"',
        "总结放大弹窗": 'id="modal-summary-view"',
        "侧边栏五项": 'data-view="materials"',
        "学习看板": 'id="view-dashboard"',
        "看板KPI": 'id="dash-kpi"',
        "复习队列": 'id="review-box"',
        "全文检索": 'id="search-form"',
        "费曼弹窗": 'id="modal-feynman"',
        "变式题弹窗": 'id="modal-variant"',
        "待审核条": 'id="pending-bar"',
        "报告导出": 'id="btn-export-report"',
        "回答风格": 'id="chat-style"',
        "学习热力图": 'id="heatmap-box"',
        "知识图谱": 'id="graph-canvas"',
        "能力雷达": 'id="radar-canvas"',
        "复习预测": 'id="forecast-box"',
        "登录注册页": 'id="auth"',
        "修改密码弹窗": 'id="modal-password"',
        "退出登录按钮": 'id="btn-logout"',
        "移动资料弹窗": 'id="modal-move"',
        "头像上传": 'id="avatar-file"',
        "修改显示名": 'id="btn-edit-name"',
    }
    missing = [k for k, v in markers.items() if v not in html]
    check("首页关键元素", not missing, "齐全" if not missing else f"缺少：{missing}")
    check("侧边栏不含主界面项", 'data-view="home"' not in html, "")


def check_data_health(base: str) -> None:
    """数据体检：不写库，只看有没有明显异常。"""
    try:
        _, body = get(base, "/api/materials")
        data = json.loads(body)
    except Exception as exc:                       # noqa: BLE001
        check("数据体检", False, str(exc))
        return
    materials = data.get("materials", [])
    folders = data.get("folders", [])
    titles = [m["title"] for m in materials]
    dup = {t for t in titles if titles.count(t) > 1}
    small = [m["title"] for m in materials if m["bytes"] < 400]
    shared = [f for f in folders if f.get("is_shared")]
    issues = []
    if dup:
        issues.append(f"重复资料 {len(dup)} 组")
    if small:
        issues.append(f"过小资料 {len(small)} 份")
    if len(shared) != 1:
        issues.append(f"核心文件夹数量异常 {len(shared)}")
    check("数据体检", not issues, "健康" if not issues else "；".join(issues))


def main() -> int:
    ap = argparse.ArgumentParser(description="轻量检查：不调模型、不写库")
    ap.add_argument("--base", default="http://127.0.0.1:8737")
    args = ap.parse_args()
    base = args.base.rstrip("/")

    print("== 静态检查 ==")
    check_python_syntax()
    check_js_syntax()
    check_no_duplicate_decls()
    check_html_balance()
    check_store_extensions()

    print("\n== 服务与接口 ==")
    try:
        urllib.request.urlopen(base + "/api/state", timeout=5)
        print("== 静态资源与页面 ==")
        check_assets(base)
        check_page_markers(base)
        logged_in, auth = login_state(base)
        if logged_in:
            check_api(base)
            check_data_health(base)
        else:
            print("（尚未登录：只检查登录拦截；登录后重跑可检查账号数据接口）")
            check_auth_gate(base)
    except urllib.error.URLError:
        print("（服务没启动，跳过接口与页面检查；启动后重跑能看到全貌）")

    total = len(results)
    passed = sum(1 for _, ok, _ in results if ok)
    print("\n" + "=" * 56)
    print(f"轻量检查：{passed}/{total} 通过")
    if passed != total:
        print("失败项：")
        for name, ok, detail in results:
            if not ok:
                print(f"  - {name}: {detail}")
    print("=" * 56)
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
