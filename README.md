# UbDict — 跨平台智能英汉词典

一款面向 Linux 和 Windows 的即指即译桌面词典，支持文本取词、图片取词（OCR）、PDF 取词，翻译来源以必应词典为主，本地 ECDICT 兜底。

## 当前状态

文本取词 + 图片取词（OCR）+ PDF 取词 + 生词本 + 设置中心 + 全局热键 + Linux `.deb` 和 Windows 安装包构建。

> M5（Wayland 适配完善 + 性能优化）为后续优化。

## 功能特性

- **文本取词**：Linux 选中单词后自动取词；Windows 选中后按 `Ctrl+C` 取词
- **图片取词（OCR）**：鼠标悬停在图片英文上停留 3 秒，自动 OCR 识别并翻译
- **第三方 PDF 悬停取词**：在外部 PDF 阅读器中启用 OCR 悬停取词，无需在 UbDict 内打开 PDF
- **生词本**：翻译浮窗或主窗口中一键加入，打开生词本时自动刷新，支持 CSV 导出
- **单词发音**：优先通过普通 HTTPS 网络播放 DictionaryAPI 提供的自然发音；网络或词条音频不可用时，自动使用 espeak-ng 离线发音，不读取系统代理设置
- **设置中心**：取词开关、停留时长、透明度、快捷键等可视化配置
- **全局热键**：Ctrl+Shift+T/D/O/P 快速操作（X11 和 Windows）
- **翻译降级链**：必应词典 → 本地 ECDICT（340万词条），离线也能查
- **翻译浮窗**：无边框不透明背景、智能避让屏幕边缘，鼠标停留时保持显示，离开后延迟关闭
- **系统托盘**：开关文本/图片/PDF 悬停取词、打开各窗口、退出
- **主窗口**：手动输入查询、历史记录；必应词条支持简明/详细英汉释义、例句、词形、常用搭配和反义词
- **翻译缓存**：LRU + SQLite 持久化，避免重复请求
- **跨显示服务器**：自动检测 X11 / Wayland
- **.deb 打包**：一键构建 Debian 安装包

## 系统要求

- Ubuntu 20.04 / 22.04 / 24.04 LTS
- Windows 10/11 x64（通过 Windows 安装包）
- Python 3.10+
- X11 或 Wayland 桌面
- 系统工具：`xclip`（X11）或 `wl-clipboard`（Wayland）
- OCR（图片取词）：`tesseract-ocr` + `tesseract-ocr-eng`
- 离线语音：`espeak-ng`

## 安装

### 1. 安装系统依赖

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv xclip
# 图片取词 OCR：
sudo apt install -y tesseract-ocr tesseract-ocr-eng
# 单词离线发音：
sudo apt install -y espeak-ng
# Wayland 用户额外安装：
sudo apt install -y wl-clipboard
```

### 2. 创建虚拟环境并安装

```bash
cd ubuntu-dict
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 使用 `.deb` 安装包

运行 `python3 scripts/build_deb.py` 会在构建时打包 Python 运行依赖和 `config/ecdict.db` 离线词典；构建时需要可访问 PyPI 的网络。生成的包位于 `dist/ubdict_0.1.12_<架构>.deb`，应在对应架构的 Ubuntu 机器上安装：

```bash
sudo apt install ./dist/ubdict_0.1.12_amd64.deb
```

由于 `.deb` 内含依赖 Python 次版本 ABI 的原生扩展，安装包只兼容构建时所用的 Python 主、次版本；包元数据会限制到对应版本范围。请使用目标 Ubuntu 系统的 Python 环境构建，以便 apt 能选择兼容的 Python 运行时。apt 会自动安装 PyQt6/Qt Multimedia、Qt XCB、OCR、截图、离线语音（espeak-ng）、在线音频解码、X11 与 Wayland 剪贴板依赖；应用的 Python 运行库和离线词典已包含在 `.deb` 中，不会在安装或运行时访问 PyPI 或 GitHub。在线发音只直接连接普通 HTTPS 服务，不使用 VPN 或系统代理；网络连接失败时会自动回退到本地语音。安装时 apt 仍需能访问系统配置的 Ubuntu 软件源。Wayland 的全局鼠标坐标受合成器安全策略限制；不提供全局指针坐标的合成器不支持悬停 OCR。

### Windows 安装包

Windows 版安装包由 Windows 构建环境生成，以保证 PyQt、OCR 和其他原生依赖使用正确的 Windows ABI。项目的 Windows CI 构建完成后，可从 Actions 的构建产物下载 `UbDictSetup-0.1.12-x64.exe`。也可在 Windows 10/11 上安装 Python 3.12、Tesseract OCR 和 Inno Setup 6 后运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
```

Windows 支持托盘、全局热键、在线/离线查词、主窗口、生词本、图片及第三方 PDF 悬停 OCR。Windows 没有 X11 的选区机制，文本取词通过在其他程序中选中文字后按 `Ctrl+C` 触发；离线发音使用 Windows 系统语音。设置和数据分别保存在 `%APPDATA%\UbDict` 与 `%LOCALAPPDATA%\UbDict`。

### 3.（源码运行时）下载本地词典 ECDICT

用 `.deb` 安装时，离线词典已随安装包自动安装。若从源码运行且尚无本地词典，可运行内置下载脚本：

```bash
python3 scripts/download_ecdict.py
```

```bash
# 示例：从 stardict.7.0 仓库获取
wget -O config/ecdict.db <ecdict 下载链接>
```

未放置时程序仍可运行，仅在网络断开时无法离线查词。

## 运行

```bash
source .venv/bin/activate
ubdict
```

或直接运行模块：

```bash
python -m ubdict.main
```

启动后：
- 系统托盘出现 "D" 图标
- 在任意应用中用鼠标选中英文单词 → 自动弹出翻译浮窗
- 托盘右键 → 勾选"图片取词"或"PDF 悬停取词" → 在对应内容上停留 3 秒 → OCR 识别并翻译。PDF 模式可用于任意第三方阅读器；在不支持全局鼠标坐标的 Wayland 桌面（例如标准 GNOME Wayland）中，悬停 OCR 不可用。
- 浮窗的"在主窗口显示更多"可查看必应词典的简明/详细释义、英汉例句、词形、常用搭配、反义词和词典来源；"加入生词本"可保存当前词条。已缓存的旧必应结果会在下次查询时尝试更新为详细内容，离线时继续显示缓存结果
- 点击音标旁的 🔊 优先播放在线自然读音；网络不可用或词条无音频时自动切换为离线读音
- 点击托盘"主窗口"可手动输入查询、查看历史和翻译详情

## 使用说明

| 操作 | 效果 |
|------|------|
| 选中英文单词 | 300ms 后弹出翻译浮窗 |
| 鼠标在图片英文上停留 3 秒 | OCR 识别后弹出翻译浮窗（需开启图片取词） |
| 在第三方 PDF 中的英文上停留 3 秒 | OCR 识别后弹出翻译浮窗（需开启 PDF 悬停取词；依赖桌面提供全局鼠标坐标） |
| 浮窗 → 在主窗口显示更多 | 在主窗口查看详细英汉释义、例句、词形、搭配、反义词与词典来源（以词典实际返回内容为准） |
| 浮窗 → 加入生词本 | 保存当前单词；重复添加会提示已存在 |
| 鼠标悬停在翻译浮窗上 | 保持显示；鼠标离开后约 8 秒自动关闭 |
| 按 Esc | 关闭浮窗 |
| 托盘 → 文本取词 | 开关文本取词 |
| 托盘 → 图片取词 | 开关图片取词（OCR） |
| 托盘 → PDF 悬停取词 | 开关第三方 PDF 阅读器内 OCR 悬停取词（与图片取词共用 OCR，两个模式互斥） |
| 托盘 → 主窗口 | 打开手动查询窗口 |
| 托盘 → 退出 | 退出程序 |

## 项目结构

```
ubuntu-dict/
├── docs/                  # PRD + 架构文档
├── src/ubdict/
│   ├── main.py            # 入口
│   ├── app.py             # 应用装配
│   ├── core/
│   │   ├── models.py      # 数据模型
│   │   ├── event_bus.py   # 事件总线
│   │   ├── capture/       # 取词引擎（text/image/pdf）
│   │   └── translate/     # 翻译适配器（bing/local）+ 服务
│   ├── platform/          # X11/Wayland 抽象
│   ├── storage/           # SQLite：历史/缓存/生词本
│   └── ui/                # 翻译浮窗/主窗口/托盘
├── config/                # 默认配置 + ecdict.db
└── tests/                 # 单元/集成测试
```

## 开发

```bash
# 安装开发依赖
pip install -e ".[dev]"
pytest
```

## 后续路线图

- **M3**：PDF 取词 + 生词本
- **M4**：设置中心 + 全局热键 + .deb 打包
- **M5**：Wayland 适配完善 + 性能优化

## 许可证

MIT
