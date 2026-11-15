# CSLA 安卓本地版

这是在 V4 上实现的安卓试用工程：Kotlin 原生外壳、WebView 界面、Chaquopy 内嵌 Python。手机内启动仅监听 `127.0.0.1` 的学习服务，不需要电脑、学习云后台或在线账号。

## 数据与联网

- 数据库、导入原件、讲义、习题、错题、对话和教材缓存保存在 `noBackupFilesDir/learning/`。
- API Key 由 Android Keystore 的 AES-GCM 密钥加密，密文保存在 `noBackupFilesDir/model-key.enc`。Key 不写入 SQLite，网页只能查询掩码。
- 禁止系统云备份及设备迁移备份；WebView 的其他应用存储也设置了备份排除。卸载应用会删除本地学习库。
- DeepSeek 请求由手机直接发送到官方 HTTPS API，会包含问题、对话上下文和为回答所需的资料片段。打开外部资料链接会转系统浏览器。
- 首次无 Key 可以阅读内置资料；已保存内容、已有习题与错题支持离线使用。生成与在线教材下载需要网络。
- 用户主动导出或分享会把指定文件交给系统文件选择器或分享目标，保存位置由用户选择。

## 已实现的手机流程

1. 启动进入本地资料页，使用手机本地用户，不连接 V4 账号服务。
2. 点击顶部“目录”切换资料、科目学习、对话和错题等页面。
3. 点击顶部“设置”，填写 DeepSeek API Key，保存并校验。可单独清除密钥。
4. 从系统文件选择器导入 PDF、DOCX、Markdown 和文本。导入单文件上限沿用 V4 的 32 MB；扫描 PDF 仍需要可提取文字，未新增 OCR。
5. 资料中的 PDF 使用 Android 原生阅读器，支持上下页和输入页码；引用链接可跳到对应 PDF 页。
6. 进入章节后每次生成一节。完整输出经原有结构、引用校验后保存，再按已保存讲义出题、作答、记录错题。
7. 切到后台会取消流式输出；下一次响应事件到来时停止，未完成输出不替换已保存讲义。任务记录写入 SQLite，应用重启会把运行中任务标记为中断。回到章节可重试未完成小节，首版不保证锁屏后继续生成。
8. 下载讲义、源文件或学习报告时调用系统“保存文件”，保存完成后可选择“分享”。

## 构建

要求：JDK 17、Android SDK Platform 35、Build Tools 35.0.0。最低 Android 8.0，支持 `arm64-v8a` 与 `x86_64`。手机需使用新版 Android System WebView（100 以上）。

```sh
export JAVA_HOME="<JDK17路径>"
export ANDROID_HOME="<Android SDK路径>"
./gradlew assembleDebug
```

安装包位于 `app/build/outputs/apk/debug/app-debug.apk`。首次构建下载 Gradle、Android 插件和 Chaquopy 依赖。调试签名在工程 `app/build/` 下生成；正式发布须使用团队的持久签名与发布配置。

`stagePython` 只复制 V4 的应用模块、静态资源、内置示例、中文指南和公开教材目录。不会打包旧账号库、用户资料目录、教材缓存、测试脚本、API Key 或整个工作区。

## 验证

```sh
python3 tests/test_mobile_runtime.py
python3 ../AIassistant-v4/AIassistant/app/check.py
python3 -m unittest discover -s ../AIassistant-v4/AIassistant/app -p test_lessons.py
```

浏览器验证需要安装 `playwright` 和 Chrome，再运行 `node tests/test_mobile_ui.cjs`。它会启动独立临时学习库，检查 390 像素视口下的首次离线入口、目录、设置、中文输入与页面切换，结束后删除临时数据。浏览器测试中目录按钮动作由测试外壳模拟，不能替代原生按钮真机测试。

本轮功能范围、安装包信息、构建与真机验收步骤见[安卓手机端更新说明](../文档/手机端移植/安卓手机端更新说明_2026-11-15.md)（同目录提供 Word 版）。真实 DeepSeek 生成、Keystore 的设备行为、中文输入法键盘、系统文件选择器、原生 PDF 阅读及 OEM 备份规则，需要在安卓设备上继续验收。

## 代码位置

- `app/src/main/java/cn/csla/mobile/`：原生外壳、密钥保险箱、导入导出与 PDF。
- `app/src/main/python/mobile_runtime.py`：本地角色、带随机会话凭据的环回服务、任务状态与后台取消。
- V4 `app/store.py`、`app/references.py`：可注入私有存储路径，桌面默认路径保持原有行为。
- V4 `app/static/mobile.js`、`mobile.css`：手机交互、网络说明与窄屏覆盖。
- `tests/`：临时库集成回归与浏览器操作验证。
