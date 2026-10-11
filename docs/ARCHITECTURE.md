# Ubuntu 字典软件 - 技术架构设计文档

> 版本：v1.0
> 日期：2026-10-07
> 对应 PRD：v1.0

## 1. 技术选型

### 1.1 技术栈总览

| 层级 | 技术 | 说明 |
|------|------|------|
| 语言 | Python 3.10+ | 开发效率高，生态丰富 |
| GUI 框架 | PyQt6 | 原生体验，组件丰富，跨 Windows/X11/Wayland |
| OCR 引擎 | Tesseract 5.x + pytesseract | 开源成熟，英文识别率高 |
| PDF 解析 | PyMuPDF (fitz) | 性能最佳，支持文本层 + 渲染 |
| 截图 | mss (Windows/X11) / grim (Wayland) | 跨显示服务器截图 |
| 全局输入 | Windows API / python-xlib (X11) / wl-clipboard (Wayland) | 鼠标/剪贴板监听 |
| 本地存储 | SQLite (stdlib sqlite3) | 历史记录、生词本、缓存 |
| 本地词典 | ECDICT (SQLite) | 30 万词条离线英汉词典 |
| HTTP | httpx (async) | 异步请求翻译 API |
| 打包 | PyInstaller + Inno Setup (Windows) / dpkg-deb | 生成 Windows 安装程序和 .deb |

### 1.2 依赖清单

```
# requirements.txt
PyQt6>=6.6
pytesseract>=0.3.10
PyMuPDF>=1.23
mss>=9.0
python-xlib>=0.33
httpx>=0.27
pydantic>=2.0
loguru>=0.7
```

**系统依赖**（apt 安装）：
```
tesseract-ocr
tesseract-ocr-eng
espeak-ng
python3-pyqt6.qtmultimedia
gstreamer1.0-plugins-ugly
libx11-dev
libxtst-dev
libxi-dev
```

---

## 2. 系统架构

### 2.1 整体架构图

```
┌─────────────────────────────────────────────────────────┐
│                    UbDict 应用进程                       │
│                                                         │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐│
│  │  取词引擎     │   │  翻译服务     │   │  UI 层       ││
│  │  (Capture)   │   │  (Translate) │   │  (UI)        ││
│  │              │   │              │   │              ││
│  │ ┌──────────┐ │   │ ┌──────────┐ │   │ ┌──────────┐ ││
│  │ │文本取词  │ │   │ │必应适配器│ │   │ │翻译窗口  │ ││
│  │ └──────────┘ │   │ └──────────┘ │   │ └──────────┘ ││
│  │ ┌──────────┐ │   │ ┌──────────┐ │   │ ┌──────────┐ ││
│  │ │图片取词  │ │   │ │有道适配器│ │   │ │主窗口    │ ││
│  │ └──────────┘ │   │ └──────────┘ │   │ └──────────┘ ││
│  │ ┌──────────┐ │   │ ┌──────────┐ │   │ ┌──────────┐ ││
│  │ │PDF取词   │ │   │ │本地词典  │ │   │ │设置窗口  │ ││
│  │ └──────────┘ │   │ └──────────┘ │   │ └──────────┘ ││
│  └──────┬───────┘   └──────┬───────┘   └──────┬───────┘│
│         │                  │                  │         │
│  ┌──────┴──────────────────┴──────────────────┴───────┐│
│  │              事件总线 (EventBus)                    ││
│  └────────────────────────────────────────────────────┘│
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐│
│  │  存储层       │   │  平台抽象层   │   │  配置管理    ││
│  │  (Storage)   │   │  (Platform)  │   │  (Config)    ││
│  └──────────────┘   └──────────────┘   └──────────────┘│
└─────────────────────────────────────────────────────────┘
```

### 2.2 模块职责

| 模块 | 职责 | 关键类 |
|------|------|--------|
| Capture | 监听选区并执行图片或外部 PDF 屏幕 OCR | TextCapture, ImageCapture |
| Translate | 翻译服务，调用各翻译源并降级 | TranslateService, BingAdapter, LocalAdapter |
| UI | 用户界面 | DictWindow, MainWindow, SettingsDialog |
| EventBus | 模块间解耦通信 | EventBus (Qt signals) |
| Storage | 本地数据持久化 | HistoryStore, WordbookStore, CacheStore |
| Platform | X11/Wayland 抽象 | PlatformBackend, X11Backend, WaylandBackend |
| Config | 配置读写 | ConfigManager |

### 2.3 数据流

**文本取词流程**：
```
用户选中文本
  → PlatformBackend 监听到 PRIMARY selection 变化
  → TextCapture 获取选中文本（去抖 300ms）
  → EventBus 发出 "word_captured" 事件
  → TranslateService 查询（缓存 → 网络 → 本地降级）
  → EventBus 发出 "translate_result" 事件
  → DictWindow 显示浮窗；MainWindow 更新匹配的查询详情
```

**图片 / 外部 PDF 悬停取词流程**：
```
托盘选择图片或 PDF 悬停 OCR 模式（共用 ImageCapture，互斥）
  → 鼠标移动 → ImageCapture 重置 3s 计时器
  → 计时器触发 → 截取鼠标周围区域
  → Tesseract OCR 识别 → 只接受光标所在 OCR 词框
  → EventBus 发出 "word_captured" 事件
  → （后续同文本流程）
```
第三方 PDF 模式不读取 PDF 文件或窗口内容，只对当前屏幕区域执行 OCR。Wayland 合成器若不提供全局指针坐标，则该悬停流程不可用。

翻译浮窗的“在主窗口显示更多”按钮把当前 Translation 对象直接传给 MainWindow，不发起重复查询。主窗口按可用数据呈现必应词典的简明与详细英汉释义、例句、词形、常用搭配、反义词、音标和词典来源；外部文献数据不在当前模型范围内。旧版必应缓存会尝试刷新，刷新失败时保留旧结果。

---

## 3. 目录结构

```
ubuntu-dict/
├── docs/                      # 文档
│   ├── PRD.md                 # 产品需求文档
│   ├── ARCHITECTURE.md        # 技术架构（本文件）
│   └── DESIGN.md              # UI 设计稿
├── src/
│   └── ubdict/
│       ├── __init__.py
│       ├── main.py            # 入口
│       ├── app.py             # QApplication 装配
│       ├── core/              # 核心业务
│       │   ├── __init__.py
│       │   ├── event_bus.py   # 事件总线
│       │   ├── capture/       # 取词引擎
│       │   │   ├── __init__.py
│       │   │   ├── base.py    # 取词基类
│       │   │   ├── text.py    # 文本取词
│       │   │   ├── image.py   # 图片取词（OCR）
│       │   │   └── pdf.py     # PDF 取词
│       │   ├── translate/     # 翻译服务
│       │   │   ├── __init__.py
│       │   │   ├── service.py # 翻译调度
│       │   │   ├── base.py    # 适配器基类
│       │   │   ├── bing.py    # 必应适配器
│       │   │   ├── youdao.py  # 有道适配器
│       │   │   └── local.py   # 本地词典适配器
│       │   └── models.py      # 数据模型（Word, Translation）
│       ├── platform/          # 平台抽象层
│       │   ├── __init__.py
│       │   ├── base.py        # 后端基类
│       │   ├── x11.py         # X11 实现
│       │   ├── wayland.py     # Wayland 实现
│       │   └── windows.py     # Windows 剪贴板、指针和截图
│       ├── storage/           # 存储层
│       │   ├── __init__.py
│       │   ├── db.py          # SQLite 连接
│       │   ├── history.py     # 历史记录
│       │   ├── wordbook.py    # 生词本
│       │   └── cache.py       # 翻译缓存
│       ├── ui/                # UI 层
│       │   ├── __init__.py
│       │   ├── dict_window.py # 翻译浮窗
│       │   ├── main_window.py # 主窗口
│       │   ├── settings.py    # 设置窗口
│       │   ├── tray.py        # 系统托盘
│       │   └── resources/     # 图标、qss 样式
│       └── config.py          # 配置管理
├── config/
│   ├── default.toml           # 默认配置
│   └── ecdict.db              # 本地词典（源码运行时下载；.deb 内置）
├── tests/
│   ├── unit/
│   └── integration/
├── assets/                    # 图标、应用图标
├── pyproject.toml
├── requirements.txt
└── README.md
```

---

## 4. 关键技术设计

### 4.1 平台抽象层（Windows / X11 / Wayland）

```python
# platform/base.py
class PlatformBackend(ABC):
    @abstractmethod
    def get_mouse_position(self) -> tuple[int, int]: ...

    @abstractmethod
    def get_selection_text(self) -> str | None: ...

    @abstractmethod
    def capture_region(self, x, y, w, h) -> bytes: ...

    @abstractmethod
    def register_hotkey(self, key, callback) -> None: ...
```

运行时自动检测：
```python
def detect_backend() -> PlatformBackend:
    session = os.environ.get("XDG_SESSION_TYPE", "x11")
    if session == "wayland":
        return WaylandBackend()
    return X11Backend()
```

**X11 实现**：`python-xlib` 监听 PRIMARY selection、`mss` 截图
**Wayland 实现**：`wl-copy`/`wl-paste` 取选中文本、`grim` 截图（注：Wayland 安全策略限制全局鼠标位置监听，需通过 `wlr-foreign-toplevel` 协议或降级为快捷键触发）
**Windows 实现**：剪贴板序号变化触发复制文本查询，`GetCursorPos` + `mss` 支持图片和外部 PDF 悬停 OCR，`RegisterHotKey` 注册全局热键；离线发音使用系统 SAPI。

### 4.2 翻译服务降级链

```python
# core/translate/service.py
class TranslateService:
    def __init__(self, adapters: list[TranslateAdapter], cache: CacheStore):
        self.adapters = adapters  # 按优先级排序
        self.cache = cache

    async def translate(self, word: str) -> Translation:
        # 1. 查缓存
        if cached := self.cache.get(word):
            return cached
        # 2. 按优先级尝试各适配器
        for adapter in self.adapters:
            try:
                result = await adapter.translate(word)
                if result:
                    self.cache.set(word, result)
                    return result
            except Exception as e:
                logger.warning(f"{adapter.name} 失败: {e}")
                continue
        # 3. 全部失败
        return Translation.empty(word)
```

### 4.3 必应词典适配器

必应词典无官方公开 API，采用 Web 页面解析方式：
- 请求 `https://cn.bing.com/dict/search?q={word}`
- 解析 HTML 提取：音标、词性释义、例句
- 使用 `selectolax` 或 `BeautifulSoup` 解析
- 遵守 robots.txt，加请求间隔（≥ 500ms）

### 4.4 图片取词 OCR 流程

```python
# core/capture/image.py
class ImageCapture:
    HOVER_DELAY = 3.0  # 秒

    def on_mouse_move(self, x, y):
        self.timer.restart()  # 重置 3s 计时器
        self.last_pos = (x, y)

    def on_hover_timeout(self):
        x, y = self.last_pos
        # 截取鼠标周围 200x80 区域
        img = self.platform.capture_region(x - 100, y - 40, 200, 80)
        # OCR 识别
        text = pytesseract.image_to_string(img, lang="eng")
        # 取距离鼠标最近的单词
        word = self._nearest_word(text, x, y)
        if word:
            self.event_bus.emit("word_captured", word)
```

### 4.5 翻译浮窗（无边框 + 失焦关闭）

```python
# ui/dict_window.py
class DictWindow(QWidget):
    def __init__(self):
        super().__init__(flags=Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowOpacity(0.95)

    def show_near(self, pos: QPoint, result: Translation):
        self._update_content(result)
        target = self._avoid_edge(pos)  # 智能避让屏幕边缘
        self.move(target)
        self.show()

    def focusOutEvent(self, event):
        QTimer.singleShot(8000, self.close)  # 鼠标离开后延迟关闭
```

### 4.6 事件总线

基于 Qt 信号槽，保证线程安全：
```python
# core/event_bus.py
class EventBus(QObject):
    word_captured = pyqtSignal(str)        # 取到单词
    translate_result = pyqtSignal(object)  # 翻译完成
    translate_error = pyqtSignal(str)      # 翻译失败

bus = EventBus()  # 全局单例
```

### 4.7 本地词典（ECDICT）

使用开源 [ECDICT](https://github.com/skywind3000/ECDICT)（30 万词条 SQLite）：
- 启动时加载 `ecdict.db`
- 包含：单词、音标、释义、词性、例句
- 作为网络翻译失败时的兜底
- `.deb` 构建时将数据库直接打包到 `/usr/share/ubdict/config/ecdict.db`，安装及离线查询时不访问 GitHub。

---

## 5. 数据模型

```python
# core/models.py
from __future__ import annotations
from pydantic import BaseModel, Field

class Example(BaseModel):
    en: str = ""
    zh: str = ""

class Definition(BaseModel):
    pos: str = ""
    meaning: str = ""
    usage: str = ""
    english_meaning: str = ""
    examples: list[Example] = Field(default_factory=list)

class PhraseGroup(BaseModel):
    label: str = ""
    phrases: list[str] = Field(default_factory=list)

class Translation(BaseModel):
    word: str
    phonetic_us: str | None = None    # 美音音标
    phonetic_uk: str | None = None    # 英音音标
    definitions: list[Definition] = Field(default_factory=list)
    detailed_definitions: list[Definition] = Field(default_factory=list)
    examples: list[Example] = Field(default_factory=list)
    word_forms: list[str] = Field(default_factory=list)
    collocations: list[PhraseGroup] = Field(default_factory=list)
    antonyms: list[str] = Field(default_factory=list)
    bing_details_loaded: bool = False
    source: str = ""                    # 来源
    audio_us_url: str | None = None
    audio_uk_url: str | None = None
```

---

## 6. 数据库 Schema

### 6.1 历史记录
```sql
CREATE TABLE history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    word TEXT NOT NULL,
    queried_at INTEGER NOT NULL,  -- unix timestamp
    source TEXT
);
CREATE INDEX idx_history_time ON history(queried_at DESC);
```

### 6.2 生词本
```sql
CREATE TABLE wordbook (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    word TEXT UNIQUE NOT NULL,
    added_at INTEGER NOT NULL,
    note TEXT
);
```

### 6.3 翻译缓存
```sql
CREATE TABLE cache (
    word TEXT PRIMARY KEY,
    translation_json TEXT NOT NULL,
    cached_at INTEGER NOT NULL
);
```

---

## 7. 打包与分发

### 7.1 .deb 打包
- `pyproject.toml` 配置 setuptools
- 用 `fpm` 将 Python 包转为 `.deb`
- 桌面入口文件 `ubdict.desktop`
- 系统依赖声明（tesseract-ocr 等）

### 7.2 .desktop 文件
```ini
[Desktop Entry]
Type=Application
Name=UbDict
Comment=Intelligent English-Chinese Dictionary
Exec=ubdict
Icon=ubdict
Categories=Utility;Dictionary;
StartupNotify=true
```

---

## 8. 风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| Wayland 限制全局鼠标监听 | 图片取词在 Wayland 下不可用 | 检测到 Wayland 时降级为快捷键触发截图取词 |
| 必应词典页面结构变更 | 翻译适配器失效 | 多源降级 + 本地词典兜底 |
| Tesseract 识别率不足 | 图片取词准确率低 | 限制触发条件（清晰区域）+ 后续可接入 PaddleOCR |
| OCR 截图频繁触发 | CPU 占用高 | 3 秒停留 + 移动去抖 + 识别失败冷却 10 秒 |

---

## 9. 测试策略

- **单元测试**：翻译适配器解析、OCR 结果处理、缓存逻辑
- **集成测试**：取词 → 翻译 → 显示全链路（mock 平台层）
- **手动测试**：X11/Wayland 双环境、各 PDF 阅读器、各浏览器
- **测试框架**：pytest + pytest-qt
