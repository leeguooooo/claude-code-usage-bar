# 图片引用指南

## 当前可用图片

### 主截图 (img.png)
**GitHub Raw URL:** 
```
https://raw.githubusercontent.com/leeguooooo/claude-code-usage-bar/main/img.png
```

**用途：** 显示Claude Code中的状态栏效果

## 不同平台的引用方式

### 1. GitHub README (✅ 已更新)
```markdown
![Claude Code Status Bar](https://raw.githubusercontent.com/leeguooooo/claude-code-usage-bar/main/img.png)
```

### 2. Reddit
**重要：** Reddit不支持外链图片在帖子中直接显示！

**正确做法：**
1. 下载 img.png 到本地
2. 使用Reddit的"Image & Video"发帖类型
3. 或在富文本编辑器中点击图片按钮上传
4. Reddit会自动托管图片

**不要在Reddit使用：**
```markdown
![Screenshot](https://...)  # 这会显示为链接，不是图片
```

### 3. Twitter/X
Twitter不支持Markdown，需要：
1. 直接上传图片文件
2. 或复制图片URL让Twitter自动展开

### 4. Discord/Slack
直接粘贴URL即可：
```
https://raw.githubusercontent.com/leeguooooo/claude-code-usage-bar/main/img.png
```

### 5. Dev.to / Hashnode / Medium
Markdown格式可用：
```markdown
![Claude Status Bar](https://raw.githubusercontent.com/leeguooooo/claude-code-usage-bar/main/img.png)
```

### 6. Product Hunt
需要特定尺寸：
- **Gallery:** 1400x788px (需要重新制作)
- **Thumbnail:** 240x240px (需要制作logo)

## 📸 需要制作的额外图片

### 1. 安装过程GIF
展示一行命令安装的过程
```bash
# 使用 asciinema 录制
asciinema rec install_demo.cast

# 或使用 terminalizer
terminalizer record install_demo
```

### 2. 使用效果GIF
展示状态栏实时更新
- 显示从绿色到黄色到红色的变化
- 5-10秒循环

### 3. Before/After对比图
- 左边：没有状态栏的Claude Code
- 右边：有状态栏的Claude Code

### 4. Logo (240x240)
用于Product Hunt和社交媒体头像

## 🛠️ 快速制作图片

### 制作GIF (Mac)
```bash
# 使用 Kap (推荐)
brew install --cask kap

# 或使用 Gifski
brew install gifski
```

### 制作截图对比
```bash
# 使用 ImageMagick 拼接图片
brew install imagemagick

# 横向拼接两张图
convert +append before.png after.png comparison.png

# 添加标签
convert comparison.png \
  -gravity North \
  -pointsize 30 \
  -annotate +0+10 'Before vs After' \
  labeled_comparison.png
```

### 优化图片大小
```bash
# 压缩PNG
optipng -o7 img.png

# 或使用 pngquant
pngquant --quality=85-95 img.png
```

## 📝 图片使用检查清单

- [x] README.md - 使用GitHub raw URL
- [x] Reddit模板 - 提醒上传到Reddit
- [x] Twitter模板 - 提醒直接上传
- [ ] 制作安装GIF
- [ ] 制作使用效果GIF
- [ ] 制作Product Hunt尺寸图片