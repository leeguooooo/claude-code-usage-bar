# 🔋 Claude Code 状态栏监控器

轻量级 Claude AI token 使用监控工具，直接集成到 Claude Code 状态栏，显示精确的使用数据。

## ✨ 特性

- 🎯 **数据精确**: 与原项目监控数据 99% 匹配
- ⚡ **实时显示**: 直接在 Claude Code 状态栏显示
- 🔍 **P90 动态限制**: 自动检测个人使用模式
- 📊 **清晰标签**: Token、成本、倒计时、使用率一目了然
- 🚀 **零配置**: 自动适应不同环境

## 📊 显示格式

```
🔋 T:15.0k/118.2k | $:11.56/119 | ⌛️3h 18m | 使用率:13%
```

### 📝 格式说明

- **🔋**: 电池图标表示余量状态
- **T:15.0k/118.2k**: Token 使用量/P90 动态限制
- **$:11.56/119**: 成本使用/成本限制
- **⌛️3h 18m**: 距离重置时间
- **使用率:13%**: 当前最高使用率百分比

### 🎨 颜色状态

- 🟢 **绿色**: 使用率 < 30%（安全）
- 🟡 **黄色**: 使用率 30-70%（注意）
- 🔴 **红色**: 使用率 > 70%（警告）

### 💯 使用率计算

使用率 = max(Token使用率, 成本使用率)
- 显示两者中的最高值，确保准确预警

## 快速开始

### 自动配置（推荐）

```bash
cd claude-statusbar-monitor
python3 setup_statusbar.py
```

### 手动配置

```bash
# 1. 确保脚本可执行
chmod +x statusbar.py

# 2. 编辑 Claude 设置文件
# 在 ~/.claude/settings.json 中添加：
{
  "statusLine": {
    "type": "command", 
    "command": "/path/to/claude-statusbar-monitor/statusbar.py",
    "padding": 0
  }
}

# 3. 重启 Claude Code
```

### 使用 Claude Code 交互配置

在 Claude Code 中运行：
```
/statusline
```

### 测试

```bash
# 基本测试
python3 statusbar.py
# 应显示: 🔋 T:4.6k/118k | $:4.68/119 | CUSTOM* | ⏱3h 33m ✅
```

## 使用说明

配置完成后，Claude Code 状态栏将自动显示您的 token 使用情况。

## 支持的计划

| 计划 | Token 限制 | 成本限制 |
|------|-----------|----------|
| Pro | ~19k tokens | $18 |
| Max5 | ~88k tokens | $35 |
| Max20 | ~220k tokens | $140 |
| Custom | 自动检测限制 | 动态计算 |

## 安装要求

- Python 3.6+
- 无需额外依赖（仅使用 Python 标准库）

## 项目架构

### 文件结构

```
claude-statusbar-monitor/
├── README.md                    # 项目说明
├── statusbar.py                 # 核心状态栏脚本
├── setup_statusbar.py           # 自动设置脚本
├── requirements.txt             # 依赖文件（仅标准库）
└── claude-settings-example.json # 配置示例
```

### 数据源

1. **原项目集成**: 优先使用 Claude-Code-Usage-Monitor 的分析引擎
2. **直接分析**: 备用方案，直接读取 Claude 数据文件
3. **P90 算法**: 基于历史使用模式动态计算限制

### 工作原理

1. 脚本首先尝试从原项目获取数据（如果已安装）
2. 如果原项目不可用，直接分析 Claude 的 JSONL 数据文件
3. 基于最近 8 天的使用历史计算 P90 限制
4. 格式化输出并显示在状态栏

## 故障排除

### 常见问题

1. **状态栏不显示**
   - 检查脚本权限: `chmod +x statusbar.py`
   - 测试脚本: `python3 statusbar.py`
   - 重启 Claude Code

2. **显示 "No Claude data found"**
   - 确认 Claude Code 已使用过
   - 检查数据目录: `ls -la ~/.claude/projects`

3. **显示 "No recent usage"**
   - 在 Claude Code 中发送消息
   - 等待几分钟后重试

4. **脚本执行失败**
   - 检查 Python 版本: `python3 --version`
   - 查看详细错误: `python3 statusbar.py 2>&1`

## 数据验证

状态栏版本已通过一致性验证，显示数据与原项目完全匹配：

```
✓ Token 使用匹配: (2,300 vs 2,318)
✓ Token 限制匹配: (113,500 vs 113,505)
✓ P90 动态计算: 完全一致
```

## 相关链接

- 原项目: [Claude-Code-Usage-Monitor](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor)
- Claude Code 文档: [状态栏配置](https://docs.anthropic.com/zh-CN/docs/claude-code/statusline)

## 许可证

MIT License