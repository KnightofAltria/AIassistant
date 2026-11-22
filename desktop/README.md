# CSLA 桌面版

将 `AIassistant-v4/AIassistant` 的完整桌面界面封装为 macOS Cocoa / WKWebView 应用，以及 Windows WinForms / WebView2 应用。双击 `.app` 或 `CSLA.exe` 自动启动内置学习服务和本地账号服务，退出窗口时一起停止。不需要用户安装 Python、Node 或手工启动服务器。

安装包下载入口：[desktop-packages-20261122 分支](https://github.com/KnightofAltria/AIassistant/tree/desktop-packages-20261122)。在该页面选择 **Code → Download ZIP** 并完整解压；Windows 双击 `Restore-Windows.cmd` 合并 10 个分片、校验 SHA256 并解压软件，再双击恢复目录中的 `CSLA.exe`；Mac 打开 `macOS/` 中的 DMG。安装包分支独立保存本次交付文件，无需合并到 main。

## 使用

- macOS 目标架构：Apple Silicon（arm64）；声明最低 macOS 12，实测环境为 macOS 26.6.2。未构建 Intel Mac 版本，未在旧版 macOS 实机验证。
- Windows 目标：Windows 10 22H2 / Windows 11 x64；完整便携包内置 CPython 3.13.17、Windows 依赖与固定 WebView2 158.0.4370.33。使用系统自带 .NET Framework 4.6.2 以上。已完成交叉构建及包检查，未在 Windows 实机运行。
- 本机首次注册账号成为管理员，随后注册账号为学生；规则仅适用于桌面版独立的本地账号库。不同账号的学习数据隔离。
- 配置页提供“暂不配置，先阅读资料”；AI 对话、讲解、出题、总结等功能需要联网与用户自己的 DeepSeek API Key。
- Word 学习报告、档案和原资料下载通过系统保存对话框；外部网页用默认浏览器打开；源文件用默认阅读程序打开。
- 数据、Key、会话和缓存保存在 `~/Library/Application Support/CSLA Desktop/`。应用菜单可打开该目录。更换应用文件保留数据。
- Windows 数据保存在 `%LOCALAPPDATA%\CSLA Desktop\`；先解压整个 ZIP，再双击 `CSLA.exe`，保留同级 `internal`。随包提供桌面快捷方式和临时数据自检工具。
- 不打包开发目录中的用户数据、Key、账号数据库或下载的参考书缓存。桌面本地账号与原网页/安卓实例的账号库独立，不自动同步。

## 构建

在 macOS arm64 上，使用 Python 3.12 的独立虚拟环境：

```sh
python3.12 -m venv .venv-desktop
.venv-desktop/bin/python -m pip install -r desktop/requirements-macos.txt
.venv-desktop/bin/python -m unittest discover -s desktop -p 'test_runtime.py' -v
.venv-desktop/bin/python desktop/build_macos.py --output /绝对路径/交付目录
```

`CSLA.spec` 使用资源白名单，图标来自已有 CSLA 标识；PyInstaller 内置 Python、Cocoa 依赖及证书。构建默认采用临时签名，商业分发所需的 Developer ID 签名与 Apple 公证尚未完成。

## 验证

`test_runtime.py` 在临时目录验证访问保护、本机首账号权限、资料导入、Word 报告生成、跨随机端口的会话恢复、单实例及关闭清理。用完自动删除临时账号与学习数据，不调用模型。

```sh
CSLA学习助手.app/Contents/MacOS/CSLA --headless-check --data-dir /private/tmp/csla-desktop-test
CSLA学习助手.app/Contents/MacOS/CSLA --data-dir /private/tmp/csla-desktop-webkit-test --ui-check-dir /private/tmp/csla-desktop-evidence
```

`--ui-check-dir` 只用于以 `csla-desktop-` 开头的测试目录，运行真实 WKWebView 的登录、免 Key 阅读、各页面切换及系统文件对话框打开/取消验证，生成 PNG 和 JSON 后退出。测试后应删除测试数据目录。

实际模型调用、旧版系统兼容性和人工鼠标交互仍需用户环境验收。

## Windows 构建

`build_windows.py` 可在 macOS / Linux 上交叉构建 x64 PE，构建环境需要 Pillow、packaging、ziglang；这些是开发依赖，不是最终用户的安装要求。将官方 Python 嵌入式 ZIP、完整 WebView2 x64 CAB 及记录 URL、字节数、SHA256 的 `runtime-sources.json` 放入工作目录的 `downloads/`，将 `requirements-windows.txt` 指定的 Windows CPython 3.13 轮子放入 `wheels/`。

开发工具的固定版本见 `requirements-build-windows.txt`，运行环境下载来源见 `runtime-sources-windows.json`；将该文件复制为构建缓存中的 `downloads/runtime-sources.json`。本次交付的安装说明与 SHA256 记录见 [`distribution/2026-11-22/`](distribution/2026-11-22/)。

跨平台下载轮子时使用 `--platform win_amd64 --python-version 313 --implementation cp --abi cp313 --only-binary=:all: --no-deps`，避免 pip 按构建主机的环境标记误选 Cocoa 依赖。`proxy_tools` 只有源码发行时，先单独构建通用 wheel。构建器会检查全部 Windows 依赖是否闭合、校验运行环境哈希，并仅复制生产模块和资源。

```sh
python desktop/build_windows.py --work /绝对路径/构建缓存 --output /绝对路径/交付目录
```

`windows_launcher.c` 使用 Unicode 路径和绝对 Python 路径、GUI 子系统、图标与版本资源；Windows JobObject 管理内置服务进程。数据库、账号、Key、开发缓存和下载书库不进入交付 ZIP。随包 `运行自检.cmd` 导入 .NET / WebView2 并在自动清理的临时目录启动服务；它不替代 Windows 界面和真实模型验收。
