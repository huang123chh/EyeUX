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
python server.py
```

浏览器会自动打开 `http://localhost:8080`。

## ⚙️ AI 报告配置

默认录制+热力图可直接使用。AI 分析报告需要配置 LLM：

1. 复制 `config.example.json` → `config.json`
2. 填入你的 LLM 信息：
```json
{
  "llm": {
    "base_url": "https://api.openai.com/v1",
    "api_key": "sk-your-key-here",
    "model": "gpt-4o"
  }
}
```
3. 重启 `python server.py`

支持任何 OpenAI 兼容 API（OpenAI / DeepSeek / Ollama / 自建代理等）。

## ✨ 功能

- **WebCam 眼动追踪** — 基于 WebGazer.js + MediaPipe Face Mesh，9 点校准
- **1€ Filter 平滑** — 注视时稳如磐石，扫视时快速响应
- **弹簧惯性物理** — 注视泡泡带橡皮筋回弹效果
- **文件热力图** — 支持图片 (JPG/PNG/WebP)、PDF、Word、PPTX、HTML
- **录制回放** — CSV 格式保存所有注视数据
- **悬停冲击波** — 鼠标悬停按钮时视觉反馈
- **AI 分析报告** — 录制后一键生成 UX 分析报告（需配置 LLM）

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
├── server.py                # 主程序（HTTP 服务器 + API）
├── static/
│   ├── index.html           # 前端 HTML + CSS
│   └── app.js               # 前端 JS（1€ Filter、物理引擎等）
├── webgazer_local.js        # WebGazer 眼动追踪库
├── pdf.min.js               # pdf.js（本地离线）
├── pdf.worker.min.js        # pdf.js Worker
├── mammoth.browser.min.js   # Mammoth.js Word 渲染
├── mediapipe/               # MediaPipe Face Mesh 模型文件
├── requirements.txt         # Python 依赖
└── data/                    # 录制数据 → %APPDATA%/EyeUX/data（gitignore）
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
- [x] LLM 自动分析报告
- [ ] A/B 页面对比测试
- [ ] Tobii 高精度模式

## 📄 许可证

[AGPL v3](LICENSE) — 可免费使用、修改、分发，但通过网络提供服务也视为分发，必须同样以 AGPL v3 开源。闭源商用需单独授权。
