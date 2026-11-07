#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按《附录C-2 项目计划》模板自身的格式生成填写版（.docx 与 .md 同源）。

模板结构（从 附录C-2 项目计划.doc 转 docx 后逐项比对得到）：
    封面：{ 项目名称 } / 项目计划 / 4×3 表格（文件状态纵向合并 + 文件标识/当前版本/作者/完成日期）
    版 本 历 史：5 列表（版本/状态 · 作者 · 参与者 · 起止日期 · 备注）
    目 录：TOC 域
    0. 文档介绍 … 7. 下属计划（标题带句点，Heading 1 / Heading 2）
    附录 机构领导审批：2 列表（检查项 · 结论）+ 审批结论 + 意见建议 + 签字
    附录C 项目计划变更控制报告：13×2 表单
另外按《九份模板逐章编写指南》要求，补上模板目录里有、正文缺失的 附录A 项目估计（A.1~A.4）。

用法：python make_plan_c2.py <输出目录>
"""

from __future__ import annotations

import sys
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

BODY = "宋体"
HEAD = "黑体"
PROJECT = "计算机课程学习助手"
VERSION = "0.3"
TODAY = "2026-10-24"
CONTENT_W = 21.0 - 2.4 - 2.4          # 版心宽度（与页边距一致）

# ---------------------------------------------------------------- 内容定义
COVER_STATUS = "文件状态：\n[√] 草稿\n[  ] 正式发布\n[  ] 正在修改"
COVER_FIELDS = [
    ("文件标识：", "CSLA-PP-PLAN"),
    ("当前版本：", VERSION),
    ("作    者：", "【姓名】"),
    ("完成日期：", TODAY),
]
HISTORY_ROWS = [
    ("版本/状态", "作者", "参与者", "起止日期", "备注"),
    ("0.1 草稿", "A", "A/B/C", "【待填】", "按计算机专业与交付优先编写初稿"),
    ("0.2 草稿", "A", "A/B/C", "【待填】", "补充本科课程与前沿范围，统一试点与验收口径"),
    ("0.3 草稿", "A", "A/B/C", "【待填】", "依已完成成品重写：技术路线、进度、估算与实际一致"),
]

BLOCKS: list[tuple] = [
    # ------------------------------ 0
    ("h1", "0. 文档介绍"),
    ("h2", "0.1 文档目的"),
    ("p", "本文档用于组织三人小组在八周内完成「计算机课程学习助手」项目的范围定义、资源安排、进度控制与变更管理，"
          "并由机构领导据此审批。本计划描述“谁、在什么时候、用什么资源、交出哪些可验收的成果”，"
          "产品功能细节见《产品需求规格说明书》（G-2），技术方案见体系结构设计报告（I-1）。"),
    ("p", "本计划不是纸面设想：编制时项目已存在可运行的成品（源码目录 AIassistant/，仓库 main 分支），"
          "文中范围、规模、工作量与进度均以该成品为依据，可逐项核验。"),
    ("h2", "0.2 文档范围"),
    ("p", "覆盖项目范围、目标、客户与开发方、制约条件、过程模型、人才与软硬件资源、财务、任务与进度、下属计划，"
          "以及项目估计（附录A）、计划审批（附录 机构领导审批）与变更控制（附录C）。"),
    ("p", "不包含：需求条目细节（见 G-2）、体系结构与模块设计（见 I-1、I-4）、数据库设计（见 I-3）、"
          "界面设计（见 I-2）、测试用例与报告（见 K-2、K-3）。"),
    ("h2", "0.3 读者对象"),
    ("p", "小组成员（执行依据）、指导教师与机构领导（评审与审批依据）、课程评审人。"),
    ("h2", "0.4 参考文献"),
    ("p", "[T-C2] 课程提供，《附录C-2 项目计划》模板。"),
    ("p", "[T-G2] 课程提供，《附录G-2 产品需求规格说明书》模板。"),
    ("p", "[CR] 课程提供，《卓越工程综合训练-2026 课程安排》。"),
    ("p", "[GUIDE] 课程材料整理，《九份模板逐章编写指南》。"),
    ("p", "[SRS] 本项目，《产品需求规格说明书》CSLA-PP-SRS，2026-10。"),
    ("p", "[CODE] 本项目源码，仓库 AIassistant/ 目录，main 分支，2026-10-24。"),
    ("h2", "0.5 术语与缩写解释"),
    ("table", [
        ("缩写、术语", "解 释"),
        ("SPP", "精简并行过程，Simplified Parallel Process"),
        ("PP", "项目规划，Project Planning"),
        ("CSLA", "计算机课程学习助手，本项目简称"),
        ("RAG", "检索增强生成：先检索本地资料，再依据资料生成回答"),
        ("人时", "一人工作一小时，工作量计量单位"),
        ("WBS", "工作分解结构，Work Breakdown Structure"),
        ("切片", "资料切分后的最小检索单元，约 400–700 token"),
        ("工具化 AI", "把软件功能封装为模型可调用的函数，实现一句话修改本地数据"),
    ]),
    # ------------------------------ 1
    ("h1", "1. 项目介绍"),
    ("h2", "1.1 项目范围"),
    ("p", "（1）是什么：一个在个人电脑本地运行的 AI 学习助手。学生填入自己的 DeepSeek API Key 后进入系统，"
          "导入课程资料即可获得带引用编号的问答；按科目与章节学习、做题、看小结；并能用一句自然语言让 AI 整理资料、"
          "增删章节。资料与数据全部保存在本机目录，模型能力通过 DeepSeek API 获取。"),
    ("p", "（2）应当包含的内容："),
    ("p", "　1) 资料管理：核心资料（core）与四学科文件夹，导入、切片建索引、点击打开源文件、删除资料与文件夹；"),
    ("p", "　2) 资料问答：检索 → 组装证据 → 流式生成 → 服务端校验引用编号是否合法；"),
    ("p", "　3) 科目学习：计算机组成原理、计算机网络、操作系统、数据结构四门课共 19 章，"
          "含大纲、讲解、单选练习、判分、错题、章节小结、推荐学习视频；"),
    ("p", "　4) 工具化 AI：15 个工具（资料增删移、按科目归类、抓取网页、科目与章节增删改、出题），删除类操作强制二次确认；"),
    ("p", "　5) 个人信息：年龄、性别、专业、需求四栏目，按月学习者档案，易错提示本；"),
    ("p", "　6) 交付件：可运行代码、九份项目文档、每日修改日志、启动脚本与安装说明。"),
    ("p", "（3）不包含的内容：登录注册与账号体系；本地大模型推理；模型微调训练；原生移动 App；OCR 与多模态；"
          "开放题自动批改；代码执行沙箱；多用户高并发；自动全网爬取资料。"),
    ("p", "（4）适用的领域：计算机专业本科课程的课后自学与练习，以本地资料为依据的问答。"),
    ("p", "（5）不适用的领域：需要权威答疑的正式教学场景、任何替代教材的场景、计算机以外学科。"),
    ("p", "（6）关于平行版本：另一 AI 产出的实现（AIassistant2/）在仓库 gpt-version 分支并行维护，"
          "作为技术路线对照，不计入本计划的 WBS 与工作量。"),
    ("h2", "1.2 项目目标"),
    ("p", "下列目标均“可实现、可验证”，验证方式在括号内给出："),
    ("table", [
        ("编号", "目标", "验证方式"),
        ("G1", "第 8 周在一台全新电脑上按 README 完成安装并启动，无需 pip install",
         "现场按文档操作，记录耗时与偏差"),
        ("G2", "任取一个课程问题，回答给出至少 1 个引用编号，且编号能对应到本地资料原文",
         "点击引用，能打开源文件对应片段"),
        ("G3", "四科 19 章均可进入，生成讲解、出题、判分、查看章节小结", "逐章抽查，记录失败章"),
        ("G4", "用一句话完成一次资料整理与一次章节修改", "演示录屏 + 服务端工具调用记录"),
        ("G5", "九份文档齐备，且范围、工具、进度与代码一致", "评审对照源码与文档描述"),
    ]),
    ("h2", "1.3 客户与最终用户介绍"),
    ("p", "本项目为课程项目，非合同项目。"),
    ("p", "客户与验收方：课程指导教师。验收依据课程安排与九份交付文档。"),
    ("p", "最终用户特征：计算机专业本科生，已在学相关课程，有至少一门专业课的电子资料，愿意自行申请并填写 API Key，"
          "以 Windows 笔记本为主要使用环境；典型场景是期末复习与课后补漏，单次使用 20–60 分钟。"),
    ("p", "需求来源：课程文档与教师要求、本项目自测与内部评审。尚未开展独立的用户访谈或问卷，"
          "涉及真实使用习惯的判断均为假设，需在第 2 周前确认。"),
    ("h2", "1.4 开发方介绍"),
    ("p", "开发方：三人课程小组，暂记 A、B、C；真实姓名、学号、班级、组长与联系方式待填写。"),
    ("p", "组长：【姓名】，联系方式：【邮箱/微信】。角色与主责见第 3 章。本版由 A 汇总编制。"),
    ("h2", "1.5 制约"),
    ("p", "（1）应当遵循的标准或规范：课程对九份文档的模板与事实性要求；HTTP/1.1 与 JSON、"
          "SSE 事件格式；OpenAI 兼容的 chat/completions 接口约定；不作未经测试的性能承诺。"),
    ("p", "（2）相关项目的影响：平行版本（gpt-version 分支）与本项目共用同一仓库与文档制度，"
          "已通过分支隔离避免相互影响；课程课件受版权限制，不得对外分发。"),
    ("p", "（3）假设与依赖："),
    ("table", [
        ("类别", "制约内容", "影响"),
        ("周期", "八周为规划基线，具体起止以教师通知为准", "进度表按周编号，不绑定日历日期"),
        ("工时", "每人每周约 9 小时为估算，尚未确认", "总容量约 216 人时，加需求须从余量中扣减"),
        ("硬件", "无 GPU，不安排本地大模型推理与训练", "技术路线锁定为 API 调用"),
        ("外部服务", "依赖 DeepSeek API，需账号与额度，按 token 计费", "无额度时只能运行离线演示模式"),
        ("网络", "校园网对 github.com:443 阻断，仓库操作走 SSH", "新成员须先配置 SSH 密钥"),
        ("技术基础", "三人均具备 Python 基础与 Git 基本操作", "若不成立，第 1 周须补培训并调整进度"),
    ]),
    # ------------------------------ 2
    ("h1", "2. 项目过程定义"),
    ("h2", "2.1 过程模型"),
    ("p", "裁剪 SPP 模型，采用每周一轮的小步迭代。每轮固定五个动作，并以下一轮的需求细化收尾："),
    ("p", "需求细化 → 设计（含接口与数据） → 实现 → 自测 → 文档与评审 → 下周计划"),
    ("p", "第 1 周：范围冻结、技术选型验证、资料清单与采集。"),
    ("p", "第 2–4 周：核心链路（检索、问答、科目学习）逐条打通。"),
    ("p", "第 5–6 周：工具化 AI、界面与动效、个人信息。"),
    ("p", "第 7–8 周：测试、安装验证、九份文档与答辩材料。"),
    ("p", "第 6 周末功能冻结，此后只做缺陷修复与文档，不新增功能。每周必须产出一个可运行、可演示的片段，"
          "避免最后一周集中联调。"),
    ("h2", "2.2 方法与工具"),
    ("table", [
        ("过程域", "方法与工具"),
        ("需求与设计", "Markdown 文档；用例与接口用文字加表格描述；接口契约用 JSON"),
        ("版本控制", "Git + GitHub（SSH 协议）；main 为本体，gpt-version 为平行版本"),
        ("实现", "Python 3.10+ 标准库（http.server、sqlite3、urllib）；前端原生 JS，无构建步骤"),
        ("数据", "SQLite 单文件数据库；资料与档案按文件落盘"),
        ("模型接入", "DeepSeek chat/completions，流式 SSE 与 function calling"),
        ("测试", "自研 check.py（20 项，零成本）与 selftest.py（44 项，全链路）"),
        ("文档", "Markdown 为主，交付件用 python-docx 生成 Word"),
        ("协作", "每周例会加周报；PR 评审；每日自动生成修改日志"),
    ]),
    ("p", "选型原则：只采用实际会用到的工具，不为展示而引入框架。因此未采用 Vue、Flask、向量数据库等方案，"
          "理由与验证记录见附录C 的 CHG-003。"),
    # ------------------------------ 3
    ("h1", "3. 人力资源计划"),
    ("table", [
        ("角色", "职责", "人员", "工作说明"),
        ("项目经理 / 需求负责人", "计划汇总、范围与验收口径、需求文档 G-2", "A", "兼问答模块主责"),
        ("问答与资料负责人", "检索、引用校验、资料导入与文件夹体系", "A", "含资料采集脚本与引用合法性校验"),
        ("科目与题库负责人", "四科 19 章、出题、判分、错题、章节小结", "B", "含内置项保护与视频推荐"),
        ("工程与测试负责人", "HTTP 服务、工具层、测试脚本、安装与分发", "C", "含 check.py、selftest.py、启动脚本"),
        ("界面负责人", "欢迎页、首页、导航、动效", "A 协调", "B、C 分别实现所属页面"),
        ("质量保证员", "交叉评审与回归测试", "全员轮值", "A 测 B、B 测 C、C 测 A"),
        ("配置管理员", "分支与标签、可运行版本留存", "C", "每周保留一个可运行提交"),
        ("技术评审负责人", "每周评审与纪要", "A", "评审结论进入周报"),
    ]),
    # ------------------------------ 4
    ("h1", "4. 软硬件资源计划"),
    ("table", [
        ("软硬件资源名称", "级别", "详细配置", "获取方式与时间", "使用说明"),
        ("开发笔记本 ×3", "关键", "Windows 10/11，8 GB 内存以上，Python 3.10+", "已经存在", "各自开发与自测"),
        ("DeepSeek API 账号", "关键", "账号与额度，deepseek-chat 模型", "需要申请，第 1 周", "全员共用，实名负责人 A"),
        ("可用网络（SSH 可达 github.com:22）", "关键", "校园网或家庭宽带", "已经存在", "仓库操作与资料采集"),
        ("浏览器", "普通", "Chrome / Edge 近两年版本", "已经存在", "界面验收"),
        ("手机 ×1", "普通", "任意可打开浏览器的机型", "可以借用", "窄屏适配抽查"),
        ("Git", "普通", "2.30 以上", "已经存在", "版本控制"),
        ("Word 或 WPS", "普通", "能打开 .docx 即可", "已经存在", "交付文档排版"),
    ]),
    ("p", "说明：本期不含模型微调，不需要 GPU。若后续追加训练，须先申请资源并在附录C 登记变更。"),
    # ------------------------------ 5
    ("h1", "5. 财务计划"),
    ("table", [
        ("开支类别", "主要开支项、用途", "金额", "时间"),
        ("设备", "使用已有笔记本，不新增采购", "0 元", "—"),
        ("模型调用", "DeepSeek API，开发调试与验收演示", "预算上限 100 元（待小组确认）", "第 1–8 周"),
        ("软件", "Python、Git、VS Code 等免费或已有授权", "0 元", "—"),
        ("合计新增现金", "—", "不超过 100 元", "—"),
    ]),
    ("p", "补充说明：上述 100 元为预算封顶，不是报价、不是已支出，实际按用量结算；"
          "人时投入单独统计（见附录A.3），不计入现金成本；达到封顶前停止非必要评测，优先保留课程演示所需调用。"),
    # ------------------------------ 6
    ("h1", "6. 任务与进度"),
    ("p", "进度表按周组织，具体日历日期以教师通知为准（“起止时间”栏在开课后补填实际日期）。"),
    ("table", [
        ("任务名称", "起止时间", "工作人员", "工作量", "预期工作成果"),
        ("需求确认、技术选型验证、资料清单", "第 1 周", "A/B/C", "24 人时", "选型对比记录、资料库可检索"),
        ("资料导入与切片、文件夹体系、检索与引用校验", "第 2 周", "A", "27 人时", "给定 5 个问题首位命中正确"),
        ("问答链路（流式输出、提示词、引用展示）", "第 3 周", "A", "30 人时", "断网可用离线模式演示"),
        ("四科 19 章、讲解、出题、判分、错题", "第 4 周", "B", "27 人时", "逐章可进入并完成一次作答"),
        ("工具化 AI（15 个工具）、章节小结、视频推荐", "第 5 周", "C", "27 人时", "一句话完成分类、移动、加章节"),
        ("个人信息与档案、易错本、界面动效；功能冻结", "第 6 周", "B", "30 人时", "首字小于 1.5 秒、引用校验可演示"),
        ("测试、安装验证、文档主体", "第 7 周", "A/B/C", "27 人时", "全量自检通过、另一台机器装成"),
        ("回归、九份文档定稿、答辩彩排", "第 8 周", "A/B/C", "24 人时", "文档与代码逐条对得上"),
        ("合计", "八周", "三人", "216 人时", "可交付版本 v0.1.0"),
    ]),
    ("p", "依赖关系：第 2 周的检索质量决定第 3 周的问答效果；第 4 周的题目质量决定第 5 周的小结能否演示。"
          "关键路径延期时，优先削减第 5 周的可选功能（动效、视频推荐），保留引用校验与评分链路。"),
    ("p", "216 人时相当于每人约 72 小时，不等于八周全职；其中约 30 人时为返工余量，不另行叠加。"),
    # ------------------------------ 7
    ("h1", "7. 下属计划"),
    ("table", [
        ("下属计划的名称", "建议负责人", "预计产生时间"),
        ("《配置管理计划》", "配置管理员（C）", "第 2 周"),
        ("《质量保证计划》", "质量保证员（全员轮值）", "第 3 周起"),
        ("《技术评审计划》", "项目经理（A）", "每周"),
        ("《测试计划》（K-1）", "工程与测试负责人（C）", "第 7 周"),
        ("《测试用例》《测试报告》（K-2、K-3）", "工程与测试负责人（C）", "第 7–8 周"),
        ("《沟通计划》：每周例会与周报", "项目经理（A）", "第 1 周"),
        ("《风险计划》：见下表", "项目经理（A）", "第 1 周"),
    ]),
    ("table", [
        ("编号", "风险", "可能性", "影响", "应对措施"),
        ("R1", "DeepSeek 无额度或限流", "中", "高", "保留离线演示模式；预算封顶前置审批"),
        ("R2", "校园网阻断仓库访问", "高", "中", "统一走 SSH；按协作指南配置"),
        ("R3", "三人可用工时低于估算", "中", "高", "第 1 周核实；不足则削减第 5 周可选功能"),
        ("R4", "资料版权受限不能公开", "中", "中", "公开仓库不展示课件；必要时清理历史"),
        ("R5", "演示机器缺 Python", "低", "高", "启动脚本自动探测；README 给下载链接"),
        ("R6", "两套版本改动同一分支造成冲突", "中", "中", "已按 main 与 gpt-version 分离"),
    ]),
    # ------------------------------ 附录A
    ("h1", "附录A 项目估计"),
    ("h2", "A.1 产品的WBS"),
    ("p", "WBS 覆盖软件与文档，叶子任务均可独立跟踪、有明确交付物。"),
    ("table", [
        ("编号", "任务", "交付物", "负责人", "人时"),
        ("1.1", "范围与需求确认", "G-2 需求基线 v1", "A", "9"),
        ("1.2", "技术选型与可行性验证", "选型对比记录", "C", "15"),
        ("2.1", "资料采集与切片", "crawl.py、切片规则、资料库", "A", "12"),
        ("2.2", "检索与引用", "BM25 检索、科目路由、引用校验", "A", "15"),
        ("2.3", "资料管理界面", "文件夹体系、打开源文件、两种删除", "A", "12"),
        ("3.1", "问答链路", "流式输出、提示词、引用展示", "A", "15"),
        ("3.2", "科目与章节", "4 科 19 章、增删改、内置保护", "B", "15"),
        ("3.3", "练习与小结", "出题、判分、错题、章节小结", "B", "12"),
        ("4.1", "工具化 AI", "15 个工具与两个指令框", "C", "18"),
        ("4.2", "个人信息与档案", "四栏目、按月档案、易错提示本", "B", "18"),
        ("5.1", "界面与动效", "欢迎页、首页、返回导航", "A", "15"),
        ("5.2", "安装与分发", "启动脚本、README、自动停服", "C", "12"),
        ("6.1", "测试", "check.py 20 项、selftest.py 44 项", "C", "18"),
        ("6.2", "九份文档", "含本计划在内九份", "全员", "36"),
        ("6.3", "答辩材料", "PPT 与演示脚本", "A", "9"),
        ("合计", "—", "—", "—", "216"),
    ]),
    ("h2", "A.2 产品规模估计"),
    ("p", "以仓库 main 分支 AIassistant/ 实测（2026-10-24），代码类文件合计约 5.9 KLOC："),
    ("table", [
        ("类型", "文件数", "行数"),
        ("后端 Python（app/*.py）", "11", "3,410"),
        ("前端 JS（app/static/*.js）", "4", "1,522"),
        ("样式 CSS", "1", "578"),
        ("页面 HTML", "1", "340"),
        ("内置示例资料（.md）", "8", "183"),
        ("代码合计", "25", "约 5,900"),
    ]),
    ("p", "配套数据（不计入代码规模）：外部导入资料 22 篇、切片 264 个；四科 19 章；SQLite 表 13 张。"),
    ("h2", "A.3 工作量估计"),
    ("p", "估算方法：按 WBS 叶子任务逐项估计后汇总，再与“8 周 × 3 人 × 9 小时 = 216 人时”的容量上限对齐与压缩。"),
    ("table", [
        ("阶段", "人时", "依据"),
        ("需求与选型（第 1 周）", "24", "三人各 8–9 小时"),
        ("核心功能（第 2–4 周）", "84", "检索、问答、科目三块"),
        ("工具化与界面（第 5–6 周）", "57", "15 个工具、动效、个人信息"),
        ("测试与文档（第 7–8 周）", "51", "九份文档为大头"),
        ("合计", "216", "含约 30 人时返工余量"),
    ]),
    ("h2", "A.4 成本估计"),
    ("table", [
        ("项目", "数量", "单价", "金额", "说明"),
        ("现金支出", "—", "—", "不超过 100 元", "仅 API 调用，预算封顶待确认"),
        ("人时投入", "216 人时", "不计现金", "—", "学生项目按 0 元计价但单独统计"),
        ("设备与软件", "已有", "—", "0 元", "不新增采购"),
    ]),
    # ------------------------------ 附录 机构领导审批
    ("h1", "附录 机构领导审批"),
    ("p", "（1）机构领导根据“项目计划检查表”认真审批《项目计划》。"),
    ("p", "（2）本项目为课程项目，无客户审批环节。"),
    ("p", "（3）本计划尚未评审，下表“结论”列留空，不得预填为通过。"),
    ("table", [
        ("项目计划检查表", "结论"),
        ("项目的目标明确吗？可以验证吗？", "待评审"),
        ("项目的范围清楚吗？", "待评审"),
        ("对项目的规模和复杂性的估计可信吗？", "待评审"),
        ("对项目的工作量估计可信吗？", "待评审"),
        ("对项目的成本估计可信吗？", "待评审"),
        ("项目的过程控制方案合理吗？", "待评审"),
        ("项目所有角色的职责清楚吗？人员安排合理吗？", "待评审"),
        ("项目所需的软件硬件资源合理吗？", "待评审"),
        ("项目开支计划合理吗？", "待评审"),
        ("任务分配合理吗？进度合理吗？", "待评审"),
        ("审批结论", "[  ] 批准该计划\n[  ] 不批准"),
        ("意见建议", "\n\n\n"),
        ("机构领导签字", "\n\n"),
    ]),
    # ------------------------------ 附录C
    ("h1", "附录C 项目计划变更控制报告"),
    ("p", "本表登记本项目已发生的计划变更；审批栏留空，待评审后填写。"),
    ("table_form", [
        ("项目计划的变更申请", ""),
        ("申请变更的《项目计划》", "名称：计算机课程学习助手项目计划\n版本：0.3\n完成日期：2026-10-24"),
        ("需要变更的内容及其理由",
         "CHG-001 范围由“多学科通用助手”改为“计算机专业交付版”。理由：三人八周内无法覆盖多学科的资料与量规。\n"
         "CHG-002 试点由“三学科各一章”改为“四门计算机课共 19 章”。理由：与专业方向一致，验收更可展示。\n"
         "CHG-003 技术路线由“Vue + 本地模型 + 微调”改为“纯 Python 标准库 + DeepSeek API”。"
         "理由：受限网络无法稳定安装依赖，无 GPU 无法本地推理与训练，课程允许使用 API。\n"
         "CHG-004 追加平行版本 AIassistant2/，置于 gpt-version 分支。理由：技术路线对照，不影响本体交付。\n"
         "CHG-005 仓库由私有转为公开。理由：便于教师查看进度；课程课件受版权限制，需从公开内容中排除。"),
        ("评估计划变更将对项目造成的影响",
         "CHG-001、CHG-002 收窄了范围但增加了题库与资料工作量，已通过 WBS 与人时重新分配吸收；\n"
         "CHG-003 删除微调与本地推理任务，新增 API 接入与工具层，总量仍在 216 人时容量内；\n"
         "CHG-004 不影响本计划的工作量与进度；\n"
         "CHG-005 带来版权暴露风险，已登记为风险 R4。"),
        ("项目经理签字", "\n\n"),
        ("变更申请的审批意见", ""),
        ("高级经理审批", "审批意见：\n\n\n签字，日期"),
        ("客户代表审批（合同项目）", "本项目非合同项目，不适用。"),
        ("更改项目计划", ""),
        ("变更后的《项目计划》", "名称：计算机课程学习助手项目计划\n版本：0.3（变更后）\n完成日期：2026-10-24"),
        ("项目经理签字", "\n\n"),
        ("重新审批项目计划", ""),
        ("高级经理审批", "审批意见：\n\n\n签字，日期"),
    ]),
]


# ---------------------------------------------------------------- 通用工具
def set_font(run, name: str, size: float | None = None, bold: bool | None = None) -> None:
    run.font.name = name
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = rpr.makeelement(qn("w:rFonts"), {})
        rpr.append(rfonts)
    for attr in ("w:ascii", "w:hAnsi", "w:eastAsia"):
        rfonts.set(qn(attr), name)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold


def cell_text(cell, text: str, size: float = 9.5, bold: bool = False) -> None:
    cell.text = ""
    lines = text.split("\n")
    para = cell.paragraphs[0]
    for i, line in enumerate(lines):
        if i:
            para = cell.add_paragraph()
        para.paragraph_format.space_after = Pt(1)
        para.paragraph_format.line_spacing = 1.15
        run = para.add_run(line)
        set_font(run, BODY, size, bold)


def shade(cell, hex_fill: str = "EDF1F8") -> None:
    tcpr = cell._tc.get_or_add_tcPr()
    tcpr.append(tcpr.makeelement(qn("w:shd"), {qn("w:val"): "clear",
                                               qn("w:color"): "auto",
                                               qn("w:fill"): hex_fill}))


def set_widths(table, weights: list[float], total_cm: float = CONTENT_W) -> None:
    tblpr = table._tbl.tblPr
    for tag in ("w:tblW", "w:tblLayout"):
        old = tblpr.find(qn(tag))
        if old is not None:
            tblpr.remove(old)
    tblw = OxmlElement("w:tblW")
    tblw.set(qn("w:type"), "dxa")
    tblw.set(qn("w:w"), str(int(total_cm / 2.54 * 1440)))
    tblpr.append(tblw)
    layout = OxmlElement("w:tblLayout")
    layout.set(qn("w:type"), "fixed")
    tblpr.append(layout)
    total = sum(weights) or 1.0
    for idx, col in enumerate(table.columns):
        cm = Cm(total_cm * weights[idx] / total)
        col.width = cm
        for cell in col.cells:
            cell.width = cm


def add_table(document, rows, weights=None, header: bool = True):
    cols = max(len(r) for r in rows)
    table = document.add_table(rows=len(rows), cols=cols)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    if weights is None:
        weights = []
        for j in range(cols):
            longest = max(len(r[j]) if j < len(r) else 0 for r in rows)
            weights.append(min(3.2, max(1.0, longest / 7 + 0.7)))
    set_widths(table, weights)
    for i, row in enumerate(rows):
        for j in range(cols):
            cell = table.cell(i, j)
            cell_text(cell, row[j] if j < len(row) else "", 9.5, header and i == 0)
            if header and i == 0:
                shade(cell)
    if header:
        trpr = table.rows[0]._tr.get_or_add_trPr()
        trpr.append(trpr.makeelement(qn("w:tblHeader"), {qn("w:val"): "true"}))
    document.add_paragraph()
    return table


def add_field(paragraph, instr: str, placeholder: str = "") -> None:
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    run._r.append(begin)
    run2 = paragraph.add_run()
    instr_el = OxmlElement("w:instrText")
    instr_el.set(qn("xml:space"), "preserve")
    instr_el.text = instr
    run2._r.append(instr_el)
    run3 = paragraph.add_run()
    sep = OxmlElement("w:fldChar")
    sep.set(qn("w:fldCharType"), "separate")
    run3._r.append(sep)
    if placeholder:
        set_font(paragraph.add_run(placeholder), BODY, 10)
    run4 = paragraph.add_run()
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run4._r.append(end)


# ---------------------------------------------------------------- 生成 docx
def build_docx(path: Path) -> None:
    document = Document()
    section = document.sections[0]
    section.page_width, section.page_height = Cm(21.0), Cm(29.7)
    section.top_margin = Cm(2.2)
    section.bottom_margin = Cm(2.2)
    section.left_margin = Cm(2.4)
    section.right_margin = Cm(2.4)

    normal = document.styles["Normal"]
    normal.font.name = BODY
    normal.font.size = Pt(10.5)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), BODY)
    normal.paragraph_format.line_spacing = 1.4
    normal.paragraph_format.space_after = Pt(3)

    # 页眉：与模板一致
    header_p = section.header.paragraphs[0]
    header_p.text = ""
    set_font(header_p.add_run(f"{PROJECT}，《项目计划》"), BODY, 9)
    header_p.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # 页脚：第 X 页 共 Y 页
    footer_p = section.footer.paragraphs[0]
    footer_p.text = ""
    footer_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_font(footer_p.add_run("第 "), BODY, 9)
    add_field(footer_p, " PAGE ", "1")
    set_font(footer_p.add_run(" 页  共 "), BODY, 9)
    add_field(footer_p, " NUMPAGES ", "1")
    set_font(footer_p.add_run(" 页"), BODY, 9)

    # ---------------- 封面
    for _ in range(4):
        document.add_paragraph()
    p = document.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_font(p.add_run(PROJECT), HEAD, 26, True)
    document.add_paragraph()
    p = document.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_font(p.add_run("项目计划"), HEAD, 26, True)
    for _ in range(5):
        document.add_paragraph()

    cover = document.add_table(rows=4, cols=3)
    cover.style = "Table Grid"
    cover.alignment = WD_TABLE_ALIGNMENT.CENTER
    cover.autofit = False
    set_widths(cover, [2.2, 1.4, 3.0])
    merged = cover.cell(0, 0).merge(cover.cell(3, 0))
    cell_text(merged, COVER_STATUS, 10)
    for i, (label, value) in enumerate(COVER_FIELDS):
        cell_text(cover.cell(i, 1), label, 10)
        cell_text(cover.cell(i, 2), value, 10)

    # ---------------- 版本历史
    document.add_paragraph()
    p = document.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_font(p.add_run("版 本 历 史"), HEAD, 14, True)
    add_table(document, HISTORY_ROWS, weights=[1.5, 0.9, 1.1, 1.4, 3.4])

    # ---------------- 目录
    document.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
    p = document.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_font(p.add_run("目　录"), HEAD, 16, True)
    toc_p = document.add_paragraph()
    add_field(toc_p, r' TOC \o "1-3" \h \z \u ',
              "（在本处右键 →“更新域”即可生成带页码的目录）")

    # ---------------- 正文
    document.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
    for block in BLOCKS:
        kind = block[0]
        if kind == "h1":
            h = document.add_heading(level=1)
            run = h.add_run(block[1])
            set_font(run, HEAD, 15, True)
            run.font.color.rgb = RGBColor(0x00, 0x00, 0x00)
            h.paragraph_format.space_before = Pt(16)
            h.paragraph_format.space_after = Pt(8)
        elif kind == "h2":
            h = document.add_heading(level=2)
            run = h.add_run(block[1])
            set_font(run, HEAD, 12.5, True)
            run.font.color.rgb = RGBColor(0x00, 0x00, 0x00)
            h.paragraph_format.space_before = Pt(10)
            h.paragraph_format.space_after = Pt(5)
        elif kind == "p":
            para = document.add_paragraph()
            set_font(para.add_run(block[1]), BODY, 10.5)
        elif kind == "table":
            rows = [tuple(r) for r in block[1]]
            rows = [tuple(c for c in r) for r in rows]
            add_table(document, rows)
        elif kind == "table_form":
            rows = block[1]
            table = document.add_table(rows=len(rows), cols=2)
            table.style = "Table Grid"
            table.alignment = WD_TABLE_ALIGNMENT.CENTER
            table.autofit = False
            set_widths(table, [1.0, 2.2])
            for i, (label, value) in enumerate(rows):
                left, right = table.cell(i, 0), table.cell(i, 1)
                if label in ("项目计划的变更申请", "变更申请的审批意见",
                             "更改项目计划", "重新审批项目计划"):
                    merged = left.merge(right)
                    cell_text(merged, label, 10, True)
                    shade(merged)
                else:
                    cell_text(left, label, 9.5)
                    cell_text(right, value, 9.5)
            document.add_paragraph()

    document.save(path)


# ---------------------------------------------------------------- 生成 md
def build_md(path: Path) -> None:
    out: list[str] = []
    out.append(f"# {PROJECT}项目计划\n")
    out.append(f"文件标识：CSLA-PP-PLAN　｜　版本：{VERSION}　｜　状态：草稿，待评审　｜　完成日期：{TODAY}\n")
    out.append("> 本文件与同目录下的同名 `.docx` 同源，按《附录C-2 项目计划》模板格式填写。\n")
    out.append("**版 本 历 史**\n")
    out.append("| " + " | ".join(HISTORY_ROWS[0]) + " |")
    out.append("|" + "---|" * len(HISTORY_ROWS[0]))
    for row in HISTORY_ROWS[1:]:
        out.append("| " + " | ".join(row) + " |")
    out.append("")
    for block in BLOCKS:
        kind = block[0]
        if kind == "h1":
            out.append(f"\n## {block[1]}\n")
        elif kind == "h2":
            out.append(f"\n### {block[1]}\n")
        elif kind == "p":
            out.append(block[1])
        elif kind == "table":
            rows = [tuple(r) for r in block[1]]
            cols = max(len(r) for r in rows)
            out.append("| " + " | ".join(rows[0]) + " |")
            out.append("|" + "---|" * cols)
            for row in rows[1:]:
                out.append("| " + " | ".join(list(row) + [""] * (cols - len(row))) + " |")
            out.append("")
        elif kind == "table_form":
            for label, value in block[1]:
                if value:
                    out.append(f"**{label}**：{value.replace(chr(10), ' / ')}")
                else:
                    out.append(f"**{label}**")
            out.append("")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    docx_path = out_dir / "附录C-2 项目计划（填写版）.docx"
    md_path = out_dir / "附录C-2 项目计划（填写版）.md"
    build_docx(docx_path)
    build_md(md_path)
    print(f"已生成：{docx_path.name}（{docx_path.stat().st_size/1024:.1f} KB）")
    print(f"已生成：{md_path.name}（{md_path.stat().st_size/1024:.1f} KB）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
