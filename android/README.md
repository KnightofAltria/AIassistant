# CSLA 安卓本地版

这是在 V4 上实现的安卓本地学习工程：Kotlin 原生外壳、WebView 界面、Chaquopy 内嵌 Python。手机内启动仅监听 `127.0.0.1` 的学习服务，不需要电脑、学习云后台或在线账号。0.2.0 已迁移现有本地学习与资料管理功能；桌面云账号、远程管理员功能继续不启用。

## 数据与联网

- 数据库、导入原件、讲义、习题、错题、对话和教材缓存保存在 `noBackupFilesDir/learning/`。
- API Key 由 Android Keystore 的 AES-GCM 密钥加密，密文保存在 `noBackupFilesDir/model-key.enc`。Key 不写入 SQLite，网页只能查询掩码。
- 禁止系统云备份及设备迁移备份；WebView 的其他应用存储也设置了备份排除。卸载应用会删除本地学习库。
- DeepSeek 请求由手机直接发送到官方 HTTPS API，会包含问题、对话上下文和为回答所需的资料片段。打开外部资料链接会转系统浏览器。
- 首次无 Key 可以阅读内置资料、管理本地资料、创建科目与手工章节；已保存内容、已有习题与错题支持离线使用。模型生成需要 Key 和网络，在线教材下载需要网络。
- 用户主动导出或分享会把指定文件交给系统文件选择器或分享目标，保存位置由用户选择。

## 已实现的手机流程

1. 首次启动进入首页，使用手机本地用户，不连接 V4 账号服务。后续恢复上次页面、科目/章节、对话、草稿和资料位置；已删除对象会退回可用列表。偏好与页面状态写入本地 SQLite，不依赖每次启动变化的环回端口。
2. 点击顶部“目录”切换资料、科目学习、对话和错题等页面。
3. 点击顶部“设置”，填写 DeepSeek API Key，保存并校验。可单独清除密钥。
4. 从系统文件选择器导入 PDF、DOCX、Markdown 和文本。手机采用带一次性凭据的二进制传输，支持传输阶段进度与取消，避免把大文件转成网页 Base64。进入本机解析后需等待完成。导入单文件上限沿用 V4 的 32 MB；扫描 PDF 仍需要可提取文字，未新增 OCR。
5. 资料中的 PDF 使用 Android 原生阅读器，支持上下页和输入页码；引用链接可跳到对应 PDF 页。系统重建阅读页时恢复资料、页码与滚动位置，并先初始化本地学习库。
6. 无 Key 时可创建科目与手工章节。填写 Key 后生成大纲、默认生成下一节，或选择生成全部未完成小节；完整输出经原有结构、引用校验后保存，再按已保存讲义出题、作答、记录错题。已保存讲义可以重读、续学和导出。
7. 切到后台会取消本次模型请求；在下一次响应或网络超时后停止。流式大纲、讲义和同步响应都检查中断，未完成输出不替换已保存内容。任务记录写入 SQLite，应用重启会把运行中任务标记为中断。删除章节或科目会清理相关任务。回到章节可重试未完成小节，首版不保证锁屏后继续生成。
8. 下载讲义、源文件或学习报告时调用系统“保存文件”，保存完成后可选择“分享”。
9. 顶部返回和系统返回先收起目录或弹窗，再按章节、章节列表、科目列表逐层返回；首页再返回退出。
10. 手机本地用户可管理个人资料和共享资料：文件夹、导入、编辑、审核、排序、批量移动/删除、来源刷新及参考文献目录、章节映射。该权限独立于桌面管理员身份，手机仍拒绝账号管理接口。
11. 已提供个人信息与头像裁剪、对话历史及重命名/删除、中文输入法组合输入保护、章节总结、视频推荐、错题变式与费曼反馈、学习看板、复习、知识图谱列表、全局搜索、使用统计和本地记录清理。模型生成结果的自动回归使用替代响应，真实模型需另行验收。
12. 学习报告通过系统文件选择器保存为 Word（`.docx`）；资料原件和讲义下载沿用相同的原生保存与分享流程。新增原生输入弹窗和外部链接处理，适配手机 WebView。

## 构建

要求：JDK 17、Android SDK Platform 35、Build Tools 35.0.0。最低 Android 8.0，支持 `arm64-v8a` 与 `x86_64`。手机需使用新版 Android System WebView（100 以上）。

```sh
export JAVA_HOME="<JDK17路径>"
export ANDROID_HOME="<Android SDK路径>"
./gradlew assembleDebug
```

安装包位于 `app/build/outputs/apk/debug/app-debug.apk`，当前版本为 0.2.0（versionCode 3）。首次构建下载 Gradle、Android 插件和 Chaquopy 依赖。

调试签名保存在工程 `android/.signing/debug.keystore`，不会被 `clean` 删除，也不会进入 Git。配置构建时发现旧 `app/build/debug.keystore` 会先迁移；已有安装使用的签名必须保留。可通过 `-PcslaDebugKeystore=/绝对路径/debug.keystore` 或 `CSLA_DEBUG_KEYSTORE` 指定已有签名；显式指定不存在的文件会报错。不同电脑首次生成的签名仍可能不同，跨机器覆盖安装必须使用同一签名。正式发布须使用团队的发布签名和发布配置。

`stagePython` 只复制 V4 的应用模块、静态资源、内置示例、中文指南和公开教材目录。不会打包旧账号库、用户资料目录、教材缓存、测试脚本、API Key 或整个工作区。

## 验证

```sh
python3 tests/test_mobile_runtime.py
python3 tests/test_model_cancellation.py
python3 tests/test_full_migration.py
python3 ../AIassistant-v4/AIassistant/app/check.py
python3 -m unittest discover -s ../AIassistant-v4/AIassistant/app -p test_lessons.py
```

浏览器验证需要安装 `playwright` 和 Chrome，再运行 `node tests/test_mobile_ui.cjs` 与 `node tests/test_full_mobile_ui.cjs`。两者使用独立临时学习库，完整回归还检查导入、参考目录、对话、讲义、练习、错题、报告下载、头像裁剪和状态恢复，以及 360/390/768 像素视口的主要页面。模型响应使用测试替代数据，结束后删除临时库。浏览器测试直接调用与原生按钮共用的网页返回函数，不能替代原生按钮真机测试。

2026-11-21 验证：手机后端 21/21 通过；V4 共享回归 80 项中 77 项通过，3 项因官方 PDF 未缓存而跳过；轻量检查 9/9 通过；两套网页回归通过；`assembleDebug` 与 `lintDebug` 通过，Lint 0 错误、11 条警告。安装包内应用模块及资源逐文件与当前源码匹配。

## 连接手机调试

手机开启开发者选项和 USB 调试，用数据线连接 Mac，在手机上允许 USB 调试授权。`adb devices` 显示 `device` 后，可以用 Android Studio 打开本目录，选择手机运行；也可用 `adb install -r app/build/outputs/apk/debug/app-debug.apk` 覆盖安装。

调试构建允许在 Mac Chrome 的 `chrome://inspect/#devices` 中检查应用 WebView；release 构建关闭这项能力。本地学习服务运行在手机内，调试时不需要启动电脑 Python 服务或设置端口反向代理。

完整的 USB、无线调试、日志查看、安装故障处理和验收步骤见[安卓手机连接与调试指南](../文档/手机端移植/安卓手机连接与调试指南_2026-11-21.md)（同目录提供 Word 版）。

本轮功能范围、安装包信息、验证依据及真机验收步骤见[安卓全功能迁移说明](../文档/手机端移植/安卓全功能迁移说明_2026-11-21.md)（同目录提供 Word 版）。真实 DeepSeek 生成、Keystore 的设备行为、中文输入法键盘、系统文件选择器、原生 PDF 阅读及 OEM 备份规则，需要在安卓设备上继续验收。

## 代码位置

- `app/src/main/java/cn/csla/mobile/`：原生外壳、密钥保险箱、导入导出与 PDF。
- `app/src/main/python/mobile_runtime.py`：本地角色、带随机会话凭据的环回服务、任务状态与后台取消。
- V4 `app/store.py`、`app/references.py`：可注入私有存储路径，桌面默认路径保持原有行为。
- V4 `app/static/mobile.js`、`mobile.css`：手机交互、网络说明与窄屏覆盖。
- `tests/`：临时库集成回归与浏览器操作验证。
