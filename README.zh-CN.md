<div align="center">

# Claude Status Bar

**一眼看清你的 Claude Code 用量。**
5 小时 / 7 天限额进度条、重置倒计时、当前模型、上下文窗口、prompt 缓存新鲜度，
直接显示在 Claude Code 的状态栏里，或者以悬浮 HUD 挂在桌面端应用上。

[![PyPI](https://img.shields.io/pypi/v/claude-statusbar.svg?color=2b7)](https://pypi.org/project/claude-statusbar/)
[![Downloads](https://static.pepy.tech/badge/claude-statusbar/month)](https://pepy.tech/project/claude-statusbar)
[![Python](https://img.shields.io/pypi/pyversions/claude-statusbar.svg)](https://pypi.org/project/claude-statusbar/)
[![CI](https://github.com/leeguooooo/claude-code-usage-bar/actions/workflows/ci.yml/badge.svg)](https://github.com/leeguooooo/claude-code-usage-bar/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/leeguooooo/claude-code-usage-bar?style=social)](https://github.com/leeguooooo/claude-code-usage-bar/stargazers)

[English](README.md) · **简体中文** · [安装](docs/install.md) · [文档](#文档)

![claude-statusbar 演示](docs/images/hero.gif)

</div>

Claude Code 几乎不告诉你离限额还有多远。`claude-statusbar` 把真正要紧的数字压进终端底部
一行。你不用再切到另一个窗口，去问「我还剩多少额度、什么时候重置」。

## 功能

- **官方 5h / 7d 用量**：就是 Claude Code 实际执行的那套限额数字，带重置倒计时和窗口末尾预测（`→NN%`），不是本地拍脑袋估的。
- **模型与上下文窗口**：当前模型，以及上下文塞了多满（`Opus 4.8 · 350k/1M`）。
- **prompt 缓存倒计时**：看清缓存还能热多久（`cache 4m23s`），也就知道下一轮什么时候要按原价重算。
- **花费与余额**：可选显示单会话花费；掉额度的中转/API 场景下还能显示实时余额。
- **两处都能显示**：终端 `statusLine` 里内联，或者给桌面端 Claude 应用挂一个置顶悬浮 HUD（macOS）。
- **3 种样式 × 9 套主题**：一条命令换整套外观，电量条、胶囊、细线随你挑。
- **生来就快**：可选的常驻进程即便按每秒刷新，CPU 占用也远低于 1%。
- **想要才加**：git 分支与增删行、会话活跃度、AgentParty/Codex 在场、雅思写作陪练进度，每一项都可单独开关。
- **零依赖安装**：一个预编译二进制（不需要 Python），或一个 `pip` 包。自动更新。

## 安装

### Claude Code（终端）

**一行搞定，不需要 Python、不需要 pip。** 它会按你的平台（macOS Apple Silicon、Linux x86_64）
下载预编译好的二进制，并把状态栏接好：

```bash
curl -fsSL https://raw.githubusercontent.com/leeguooooo/claude-code-usage-bar/main/install.sh | bash
```

<sub>谨慎的话，先下下来读一遍，脚本开头写清了它会碰哪些东西。没有预编译二进制的平台会自动回退到 pip。</sub>

习惯 pip / uv，或者要装桌面 HUD？那就装 Python 包：

```bash
pip install claude-statusbar     # 或：uv tool install / pipx install
cs --setup                       # 接好 statusLine 钩子，并装上 skill
```

重启 Claude Code，状态栏就出现在底部了。其余安装方式（只装 skill、插件市场、Codex/AgentParty
桥接）都在 **[安装指南](docs/install.md)** 里。

> **延伸阅读：**[`cache 4m23s` 这行到底准不准？prompt 缓存倒计时是怎么算出来的](https://blog.leeguoo.com/posts/claude-statusbar-cache-countdown/)

### Claude 桌面端（macOS）· `cs hud`

桌面端应用没有状态栏，所以 `cs hud` 给它挂一个置顶悬浮面板，显示同一套**官方** 5h / 7d 用量
（由桌面端应用自己采样，不是估算），以及你正在用的 AgentParty 频道。

```bash
pip install 'claude-statusbar[hud]'   # 装 PyObjC（macOS 的 GUI 依赖）
cs hud install                        # launchd：登录自启 + 保活
```

<div align="center">
<img width="209" alt="收起的 HUD 药丸" src="https://github.com/user-attachments/assets/4bcf4c8d-e919-416a-8356-daa4d5c1a966" />
<img width="620" alt="展开的 HUD 面板" src="https://github.com/user-attachments/assets/fcdea929-5e85-4f1a-982e-ba431d8a80d1" />
</div>

收起时是个小药丸，点一下展开，随手拖到任意位置；桌面端没开时它自动隐藏。细节看
**[桌面 HUD 指南](docs/desktop-hud.md)**。

## 显示什么

默认样式的状态栏，`classic` 样式、`graphite` 主题：

![默认状态栏](docs/images/classic-graphite.svg)

完整刷新时最多三行，每一段都可以单独关掉：

| 行 | 内容 |
|---|---|
| **用量** | 5h / 7d 限额进度条、重置倒计时、窗口末尾预测（`→NN%`）、模型与上下文窗口、prompt 缓存倒计时、可选的单会话花费或中转余额 |
| **项目** | 项目名、git 分支、本次会话的 `+/−` 行数、时长、版本 |
| **模式** | 会话的 effort / thinking / fast / style |

每个图标、每档配色阈值、每个开关都写在 **[逐段参考](docs/segments.md)** 里；九套主题、三种样式在
**[样式与主题](docs/styles-and-themes.md)**。

## 文档

| 指南 | 讲什么 |
|-------|---------------|
| [安装](docs/install.md) | 二进制、PyPI、一键脚本、只装 skill、插件、Codex 桥接 |
| [显示什么](docs/segments.md) | 完整的逐段参考表 |
| [样式与主题](docs/styles-and-themes.md) | 3 样式 × 9 主题、预览、slash 命令 |
| [配置](docs/configuration.md) | 配置文件、全部 `show_*` 键、环境变量、JSON 输出、CLI 速查 |
| [桌面 HUD（`cs hud`）](docs/desktop-hud.md) | 给桌面端 Claude 应用用的 macOS 悬浮面板 |
| [快速模式（常驻）](docs/daemon.md) | CPU 占用低于 1% 的常驻进程，launchd / systemd 自启 |
| [无额度模式](docs/no-quota-mode.md) | 中转 / Bedrock / Vertex 布局、上下文电量条、余额 |
| [AgentParty / Codex 桥接](docs/agentparty.md) | 本地工作区在场行 |
| [缓存倒计时](docs/cache-countdown.md) | 数据来源 + `cache 4m23s` 的算法 |
| [排障](docs/troubleshooting.md) | `cs doctor`、常见问题、升级 |

## 对比

好用的 Claude Code 用量监控有好几个。它们解决的问题彼此重叠又各有侧重。看你想在**哪里**看到
这些信息，就挑对应的那个。

| 工具 | 长在哪 | 擅长什么 |
|---|---|---|
| **claude-statusbar（`cs`）** | Claude Code 的 `statusLine`（底部一行） | 干活时扫一眼就够，零切换成本 |
| [ccusage](https://github.com/ryoppippi/ccusage) | 单独终端窗口里的 TUI | 长周期用量分析、按周的花费拆解 |
| [Claude Code Usage Monitor](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor) | 带燃烧速率预测的独立 TUI | 付费套餐的实时燃烧速率预测 |

`cs` 就是刻意做成一行颜色、每秒一个判断。想要带图表、按天按周汇总、燃烧速率预测的仪表盘，那就
在侧边窗格开个 TUI，两者并存得很好。

## 集成

装上 **[prompt-language-coach](https://github.com/leeguooooo/prompt-language-coach)** 插件就能
跟踪雅思分数变化。之后状态栏会自动带出你的写作水平和趋势（不用配置，`~/.claude/language-progress.json`
存在时自动出现）：

```
... | Opus 4.8(350k/1M) | EN:6.0↑ JA:5.0→
```

`↑` 比上次会话进步 · `↓` 退步 · `→` 持平。

## 参与贡献

欢迎 PR。**[CONTRIBUTING.md](CONTRIBUTING.md)** 有完整的贡献指南：本地环境、测试命令、架构地图、
代码约定、发版流程。安全问题看 **[SECURITY.md](SECURITY.md)**。

```bash
git clone https://github.com/leeguooooo/claude-code-usage-bar
cd claude-code-usage-bar
uv sync
PYTHONPATH=src uv run pytest tests/   # 900+ 个测试，约 3 秒
```

渲染路径是热路径（`refreshInterval: 1` 时每分钟最多跑 60 次）。`tests/test_import_perf.py`
钉死了哪些模块不能在这条快路径上导入。加依赖之前先读 CONTRIBUTING.md。

每个版本的改动：**[CHANGELOG.md](CHANGELOG.md)** · [GitHub Releases](https://github.com/leeguooooo/claude-code-usage-bar/releases)。

## 致谢

- [@marcwimmer](https://github.com/marcwimmer)：最初的 `show_cache_age` 组件（[#9](https://github.com/leeguooooo/claude-code-usage-bar/pull/9)）
- [claude-monitor](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor)：用作可选快路径数据源的 token 用量分析库

<a href="https://github.com/leeguooooo/claude-code-usage-bar/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=leeguooooo/claude-code-usage-bar" alt="Contributors" />
</a>

## Star 历史

<a href="https://star-history.com/#leeguooooo/claude-code-usage-bar&Date">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/images/star-history-dark.svg">
    <img alt="Star history" src="docs/images/star-history.svg">
  </picture>
</a>

<sub>静态快照截于 v3.3.x；<a href="https://star-history.com/#leeguooooo/claude-code-usage-bar&Date">点开看实时图</a>。</sub>

---

<div align="center">
<sub>MIT © <a href="https://github.com/leeguooooo">leeguooooo</a> · 为长在 Claude Code 里的人而做。</sub>
</div>
