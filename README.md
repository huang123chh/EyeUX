# EyeUX — WebCam 眼动追踪可用性测试工具

> 用户说好 ≠ 真的好。眼睛不会撒谎。
> WebCam 眼动追踪 + AI 分析，让可用性测试人人可用。

## 🎯 是什么

EyeUX 用普通电脑摄像头替代昂贵的眼动仪，让任何人都能做专业的可用性测试。打开图片/PDF/网页 → 摄像头追踪眼球运动 → 生成热力图和数据分析。

## 🚀 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 启动
python webgazer_server.py
```

浏览器会自动打开 `http://localhost:8080`。

## ✨ 功能

- **WebCam 眼动追踪** — 基于 WebGazer.js + MediaPipe Face Mesh，9 点校准
- **1€ Filter 平滑** — 注视时稳如磐石，扫视时快速响应
- **弹簧惯性物理** — 注视泡泡带橡皮筋回弹效果
- **文件热力图** — 支持图片 (JPG/PNG/WebP)、PDF、Word、PPTX、HTML
- **录制回放** — CSV 格式保存所有注视数据
- **悬停冲击波** — 鼠标悬停按钮时视觉反馈

## 🛠️ 技术栈

| 层 | 技术 |
|----|------|
| 眼动追踪 | WebGazer.js, MediaPipe Face Mesh |
| 后端 | Python HTTP Server |
| 热力图 | NumPy, SciPy, Matplotlib |
| PPTX 转换 | PowerPoint COM / LibreOffice |
| PDF 渲染 | pdf.js |
| Word 渲染 | Mammoth.js |

## 📁 项目结构

```
├── webgazer_server.py      # 主程序（HTTP 服务器 + 前端 HTML）
├── webgazer_local.js       # WebGazer 眼动追踪库
├── mediapipe/              # MediaPipe Face Mesh 模型文件
├── requirements.txt        # Python 依赖
└── data/                   # 录制数据（gitignore）
```

## 📊 数据格式

录制数据保存为 CSV，字段包括：

| 字段 | 说明 |
|------|------|
| timestamp_ms | 时间戳 |
| x, y | 屏幕坐标 |
| screen_width, screen_height | 屏幕分辨率 |
| page | 页码 |
| scroll_x, scroll_y | 滚动偏移 |
| content_w, content_h | 内容尺寸 |

## 🗺️ 路线图

- [x] WebCam 眼动采集 + 9 点校准
- [x] 基础热力图叠加
- [x] 多格式文件支持（图片、PDF、Word、PPTX、HTML）
- [ ] AI 困惑/迷失检测
- [ ] LLM 自动分析报告
- [ ] A/B 页面对比测试
- [ ] Tobii 高精度模式

## 📄 许可证

MIT
