# CSLA 桌面应用安装包 · 2026-11-22

此分支保存 Windows x64 和 macOS arm64 软件包。源码、构建方法、安装说明及当天日志在 [fix/android-reliability 分支](https://github.com/KnightofAltria/AIassistant/tree/fix/android-reliability/desktop)。此安装包分支无需合并到 main。

## 下载 Windows 版

1. 在 GitHub 页面点击 **Code → Download ZIP**，下载整个分支并完整解压。请保留 `windows-parts` 文件夹及所有分片。
2. 在 Windows 10 22H2 / Windows 11 x64 上，双击 `Restore-Windows.cmd`。
3. 脚本会逐片检查 SHA256、恢复完整 ZIP、核对最终 SHA256，再解压到 `Windows-Application`。
4. 打开 `Windows-Application/CSLA-Windows-x64`，双击 `CSLA.exe`。保留 EXE 同级的 `internal` 文件夹；也可运行其中的桌面快捷方式和自检脚本。

完整 Windows ZIP 为 458,365,880 字节，GitHub 普通提交限制单文件 100 MB，因此以 10 个小于 50 MB 的分片保存。分片已在构建机上重新合并，完整 SHA256 与原交付 ZIP 一致：

`768fbd083dd07e5f39c4dad35fab30e2badfeca87b6bdc5ca6b750f55b273a36`

恢复脚本使用 Windows 自带 PowerShell 5.1，无需另装 Python、Node 或压缩工具。保留已恢复 ZIP 时，请不要重复运行恢复脚本；更新时先将上一份恢复结果移到别处。

## 下载 Mac 版

打开 `macOS` 文件夹，下载其中的 DMG；或同样下载整个分支后打开 DMG，将应用复制到 Applications。目标为 Apple Silicon，不是 Intel Mac。

## 说明与验证范围

软件内置运行环境，AI 功能需要用户自己的 DeepSeek API Key 和网络；本机首账号为管理员，后续账号为学生。软件包不包含开发者 Key、私人数据库、会话或下载书库。

`说明与验证` 保存两套安装说明、构建记录及校验文件。Windows 已完成 x64 GUI EXE 交叉构建、包检查和完整 ZIP 校验，尚未 Windows 实机运行；恢复脚本也未在 Windows 执行。Mac 实际 WKWebView 自动检查 13 项通过，DMG 挂载与启动检查通过。真实模型调用未验收，Mac 未公证，Windows 未商业签名。

本次 GitHub 账号授权请求超时，因此通过已验证可用的项目 SSH 身份上传此独立分支。之后可将原始完整 ZIP 与 DMG 转为 Releases 附件。
