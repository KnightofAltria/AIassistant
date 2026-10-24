# 项目约定（常驻指令，给 AI 助手看）

> 这个文件每次会话都会自动读取。里面的规则不用用户重复交代。

## 一、每日修改日志（必须执行）

用户要求：**每天在 `日志/` 目录下生成一份全新的 Word 文档，记录当天的修改日志。**

规则：

1. 文件名固定格式：`日志/YYYY-MM-DD 修改日志.docx`，日期用当天真实日期（例：`2026-10-24 修改日志.docx`）。
2. **每天一份新文件**。同一天内如果继续干活，更新当天那一份，不要新建第二份；绝不要往旧日期的文件里追加或覆盖。
3. 内容一律中文，至少包含：
   - 标题、日期、项目名、记录人
   - 今日变更清单（表格：时间 / 提交哈希 / 类型 / 说明 / 文件变化）
   - 数据来源必须是 `git log --since="当天 00:00" --reverse --pretty --shortstat` 和 `git status`，**不允许凭印象编写，不允许编造未发生的事**
   - 仓库当前状态：提交总数、今日提交数、跟踪文件数、是否与远端同步
   - 问题与处理、遗留与下一步
4. 项目**未开发的功能不要写成已完成**，未跑的测试写成未执行——错一天的日志比没有日志更糟。
5. 生成工具：`文档/_文档生成/make_daily_log.py`（python-docx）。中文字体必须同时设置 `run.font.name` 与 `w:eastAsia`，否则渲染成方框。
6. 生成后跑校验再提交：

   ```powershell
   & "C:\Users\Administrator\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe" `
     "C:\Users\Administrator\AppData\Local\Programs\DeepSeek Harness\resources\runtime\office-skills\scripts\check_office.py" `
     "日志\YYYY-MM-DD 修改日志.docx" --out checks.json
   ```

7. 日志文件要提交并推送，日志本身就是给老师看的过程证据。

## 二、仓库约定

- 远程：`git@github.com:KnightofAltria/AIassistant.git`，**只走 SSH**。本机直连 `github.com:443` 被阻断（`Connection was reset` / 21 秒超时），HTTPS + PAT 走不通，别再尝试。
- 推送偶发 `Connection reset by ... port 22`，**重试 2–3 次即可**，不是权限问题。
- Git 身份：`KnightofAltria <2356925182@qq.com>`。
- `main` 保持可交付状态；新改动走分支 + Pull Request，合并前至少一人 Review。

## 三、目录结构与提交规范

```
AIassistant/   项目代码（当前仅需求简述，源码待开发）
文档/          课程要求、交付文档初稿、设计方案、文档生成脚本
日志/          每日修改日志（.docx）
```

- 提交信息：`<类型>: <说明>`，类型限 `feat` / `fix` / `docs` / `chore` / `refactor` / `test`。
- `.gitignore` 已忽略：`__pycache__/`、`~$*`（Office 锁文件）、`*.zip`、`Thumbs.db`、`.vscode/` 等。
- 空目录 Git 不记录；需要保留就在里面放 `.gitkeep`。
- 大文件（课件 PDF、压缩包）不要反复提交新副本。

## 四、文档事实约束

- 项目是课程作业版本（简称 CSLA），目标是"功能具备、流程能演示、代码能安装、文档与实际一致"。
- 当前**尚未**实现源代码、未训练模型、未收集正式数据。写任何文档都不得声称已实现或已通过测试。
