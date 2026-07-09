"""
EyeUX — WebGazer 眼动追踪 + 数据存储
用法: python webgazer_server.py
数据保存到 ./data/ 目录，CSV 格式适合热力图等后续分析。
"""

import base64
import csv
import html as _html
import http.server
import io
import json
import os
import threading
import time
import uuid
import sys
import webbrowser
import zipfile

# 修复 Windows 控制台中文乱码
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
from datetime import datetime
from pathlib import Path

PORT = 8080
ROOT_DIR = Path(__file__).parent
DATA_DIR = ROOT_DIR / "data"

# ── 确保数据目录存在 ──
DATA_DIR.mkdir(exist_ok=True)

# ── 会话级文件句柄 ──
current_session: dict | None = None  # {id, csv_path, csv_file, csv_writer, start_time, count}

HTML = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>EyeUX</title>
<style>
  *{margin:0;padding:0;box-sizing:border-box}
  body{background:#1a1a2e;overflow:hidden;height:100vh}

  /* ── Tobii 风格校准遮罩 ── */
  #cal-overlay{
    position:fixed;top:0;left:0;width:100%;height:100%;
    background:#3a3a3a;z-index:100;cursor:pointer;
  }
  #cal-overlay.done{display:none}

  /* ── 校准点容器 ── */
  #cal-dot{
    position:absolute;width:56px;height:56px;
    margin-left:-28px;margin-top:-28px;
    pointer-events:none;
    animation:cal-pulse 2s ease-in-out infinite;
  }
  @keyframes cal-pulse{
    0%,100%{transform:scale(1)}
    50%{transform:scale(1.12)}
  }

  /* ── 进度圆环 SVG ── */
  #cal-timer-svg{
    position:absolute;top:0;left:0;width:100%;height:100%;
    transform:rotate(-90deg);
  }
  #cal-timer-track{
    fill:none;stroke:rgba(255,255,255,0.12);stroke-width:1.5;
  }
  #cal-timer-fill{
    fill:none;stroke:rgba(255,255,255,0.85);stroke-width:2;
    stroke-linecap:round;
    stroke-dasharray:163.36;
    stroke-dashoffset:163.36;
  }

  /* ── 外层白色圆环 ── */
  #cal-ring-outer{
    position:absolute;top:50%;left:50%;
    width:42px;height:42px;
    margin-left:-21px;margin-top:-21px;
    border-radius:50%;
    border:1.5px solid rgba(255,255,255,0.55);
    pointer-events:none;
  }

  /* ── 内层白色圆环 ── */
  #cal-ring-inner{
    position:absolute;top:50%;left:50%;
    width:28px;height:28px;
    margin-left:-14px;margin-top:-14px;
    border-radius:50%;
    border:1px solid rgba(255,255,255,0.4);
    pointer-events:none;
  }

  /* ── 中心实心原点 ── */
  #cal-core{
    position:absolute;top:50%;left:50%;
    width:7px;height:7px;
    margin-left:-3.5px;margin-top:-3.5px;
    background:rgba(255,255,255,0.85);
    border-radius:50%;
    pointer-events:none;
    box-shadow:0 0 3px rgba(255,255,255,0.4);
  }

  #cal-counter{
    position:absolute;bottom:8%;left:50%;transform:translateX(-50%);
    color:rgba(255,255,255,0.5);font-size:13px;letter-spacing:2px;
    pointer-events:none;font-family:inherit;
  }

  /* ── 顶部状态栏 ── */
  #status{
    position:fixed;top:12px;left:50%;transform:translateX(-50%);z-index:50;
    color:#fff;font-size:13px;font-family:monospace;
    background:rgba(0,0,0,0.55);padding:5px 14px;border-radius:5px;
    white-space:nowrap;
  }

  /* ── 录制按钮 ── */
  #rec-controls{
    position:fixed;top:12px;right:16px;z-index:300;display:flex;gap:8px;
  }
  #rec-controls button{
    padding:6px 14px;border-radius:5px;border:none;cursor:pointer;
    font-size:13px;font-family:monospace;color:#fff;
    transition:opacity 0.2s;
  }
  #rec-controls button:hover{opacity:0.85}
  #btn-start{
    background:#27ae60;display:inline;
  }
  #btn-stop{
    background:#e74c3c;display:none;
  }
  #rec-dot{
    display:none;width:8px;height:8px;border-radius:50%;
    background:#e74c3c;animation:rec-blink 1s step-end infinite;
    align-self:center;
  }
  @keyframes rec-blink{0%,100%{opacity:1}50%{opacity:0}}

  #sample-count{
    position:fixed;bottom:12px;right:16px;z-index:300;
    color:rgba(255,255,255,0.45);font-size:11px;font-family:monospace;
  }

  /* ── 注视泡泡 ── */
  #gaze-dot{
    position:fixed;width:200px;height:200px;
    margin-left:-100px;margin-top:-100px;
    background:radial-gradient(circle at 36% 30%,
      rgba(210,235,255,0.50) 0%,
      rgba(150,200,240,0.30) 35%,
      rgba(100,160,210,0.18) 65%,
      rgba(60,110,160,0.08) 100%);
    border-radius:50%;
    border:1px solid rgba(255,255,255,0.30);
    pointer-events:none;z-index:200;display:none;
    box-shadow:
      inset 0 0 30px rgba(255,255,255,0.10),
      inset 0 -5px 15px rgba(180,210,240,0.08),
      0 0 35px rgba(100,150,210,0.18),
      0 0 70px rgba(60,110,170,0.06);
  }

  /* ── 水滴碎片（从泡泡尾部分离，随后聚合）── */
  .gaze-droplet{
    position:fixed;
    pointer-events:none;z-index:199;
    border-radius:50%;
    background:radial-gradient(circle at 36% 30%,
      rgba(210,235,255,0.42) 0%,
      rgba(150,200,240,0.25) 35%,
      rgba(100,160,210,0.12) 65%,
      rgba(60,110,160,0.04) 100%);
    border:1px solid rgba(255,255,255,0.20);
    box-shadow:
      inset 0 0 10px rgba(255,255,255,0.06),
      0 0 14px rgba(100,150,210,0.10);
    transform:translate(-50%,-50%);
  }

  /* ── 悬停冲击波光环 ── */
  @keyframes shockwave {
    0%   { transform:translate(-50%,-50%) scale(0.4); opacity:0.65; }
    100% { transform:translate(-50%,-50%) scale(2.8); opacity:0; }
  }
  .shockwave-ring{
    position:fixed;
    pointer-events:none;z-index:198;
    width:200px;height:200px;
    border-radius:50%;
    border:2px solid rgba(180,220,255,0.55);
    box-shadow:0 0 18px rgba(140,200,240,0.25), inset 0 0 12px rgba(180,220,255,0.08);
    animation:shockwave 0.85s ease-out forwards;
  }

  /* ── 文件展示层 ── */
  #file-layer{
    position:fixed;top:0;left:0;width:100%;height:100%;z-index:0;
    display:flex;align-items:center;justify-content:center;
    background:#1a1a2e;
  }
  #file-layer img{
    max-width:100vw;max-height:100vh;object-fit:contain;
  }
  #file-layer canvas{
    display:block;box-shadow:0 0 30px rgba(0,0,0,0.5);
  }
  #file-layer pre{
    width:100%;height:100%;padding:60px 80px;overflow:auto;
    color:#ddd;font-size:15px;line-height:1.7;white-space:pre-wrap;
    background:#1a1a2e;box-sizing:border-box;
  }
  #file-layer .text-iframe{
    width:100%;height:100%;border:none;
  }

  /* ── 隐藏的文件选择器 ── */
  #file-input{display:none}

  /* ── 打开文件按钮 ── */
  #btn-open{background:#8e44ad}

  /* ── PDF 页码指示器 ── */
  #pdf-indicator{
    display:none;position:fixed;bottom:24px;left:50%;transform:translateX(-50%);
    z-index:300;color:#fff;font-size:13px;font-family:monospace;
    background:rgba(0,0,0,0.6);padding:4px 14px;border-radius:4px;
  }
</style>
</head>
<body>

<input type="file" id="file-input" accept=".jpg,.jpeg,.png,.gif,.webp,.bmp,.pdf,.txt,.md,.html,.htm,.docx,.pptx">
<div id="file-layer"></div>

<div id="cal-overlay">
  <div id="cal-dot">
    <svg id="cal-timer-svg" viewBox="0 0 56 56">
      <circle id="cal-timer-track" cx="28" cy="28" r="26"/>
      <circle id="cal-timer-fill" cx="28" cy="28" r="26"/>
    </svg>
    <div id="cal-ring-outer"></div>
    <div id="cal-ring-inner"></div>
    <div id="cal-core"></div>
  </div>
  <div id="cal-counter"></div>
</div>

<div id="status">Loading...</div>

<div id="rec-controls">
  <div id="rec-dot"></div>
  <button id="btn-start" onclick="startRecording()">REC</button>
  <button id="btn-stop"  onclick="stopRecording()">STOP</button>
  <button id="btn-open" onclick="document.getElementById('file-input').click()">📂 Open</button>
  <button id="btn-heatmap" onclick="showHeatmap()" style="display:none;background:#e67e22">🔥 Heatmap</button>
  <button id="btn-video" onclick="toggleVideo()" style="background:#555">📷 视频</button>
  <button id="btn-gazedot" onclick="toggleGazeDot()" style="background:#555">🔴 目光</button>
</div>

<!-- 翻页控件 —— 底部居中，始终可点 -->
<div id="page-bar" style="display:none;position:fixed;bottom:16px;left:50%;
  transform:translateX(-50%);z-index:9999;background:rgba(0,0,0,0.75);
  border-radius:8px;padding:8px 18px;align-items:center;gap:14px;
  border:1px solid rgba(255,255,255,0.2);">
  <button id="btn-page-prev" style="background:rgba(255,255,255,0.2);color:#fff;
    border:none;border-radius:5px;padding:8px 18px;cursor:pointer;font-size:16px;">◀ 上一页</button>
  <span id="page-num" style="color:#fff;font-size:16px;min-width:50px;text-align:center;font-weight:bold;">P1</span>
  <button id="btn-page-next" style="background:#e67e22;color:#fff;
    border:none;border-radius:5px;padding:8px 18px;cursor:pointer;font-size:16px;">下一页 ▶</button>
</div>

<div id="sample-count"></div>
<div id="gaze-dot"></div>
<div id="pdf-indicator"></div>


<script src="/webgazer_local.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/mammoth/1.6.0/mammoth.browser.min.js"></script>
<script>
// ── 1€ Filter: 自适应低通滤波，注视时强平滑，扫视时快速响应 ──
// Reference: G. Casiez, "1€ Filter: A Simple Speed-based Low-pass Filter for Noisy Input in Interactive Systems"
class OneEuroFilter {
  constructor(freq, mincutoff, beta, dcutoff) {
    this.freq = freq;           // 采样率 (Hz)
    this.mincutoff = mincutoff; // 最小截止频率 (Hz) — 越小注视时越稳
    this.beta = beta;           // 速度系数 — 越大对快速移动越敏感
    this.dcutoff = dcutoff;     // 导数截止频率 (Hz)
    this.x = null;              // 上一次滤波后的值
    this.dx = null;             // 上一次滤波后的导数
    this.lasttime = null;       // 上一次时间戳 (ms)
  }

  alpha(cutoff) {
    var te = 1.0 / this.freq;
    var tau = 1.0 / (2.0 * Math.PI * cutoff);
    return 1.0 / (1.0 + tau / te);
  }

  filter(x, timestamp) {
    if (this.lasttime === null || this.x === null) {
      this.x = x;
      this.dx = 0;
      this.lasttime = timestamp !== undefined ? timestamp : Date.now();
      return x;
    }
    var dt = (timestamp !== undefined ? (timestamp - this.lasttime) / 1000.0 : 1.0 / this.freq);
    if (dt <= 0) dt = 1.0 / this.freq;
    this.lasttime = timestamp !== undefined ? timestamp : Date.now();

    // 计算导数（速度）
    var dx = (x - this.x) / dt;

    // 对导数做低通滤波
    var edx = this.dx + this.alpha(this.dcutoff) * (dx - this.dx);
    this.dx = edx;

    // 根据速度动态调整截止频率
    var cutoff = this.mincutoff + this.beta * Math.abs(edx);

    // 对信号做低通滤波
    var filtered = this.x + this.alpha(cutoff) * (x - this.x);
    this.x = filtered;

    return filtered;
  }
}

console.log('[EyeUX v2] 1€ Filter loaded — gaze smoothing active');

const calOverlay = document.getElementById('cal-overlay');
const calDot = document.getElementById('cal-dot');
const calTimerFill = document.getElementById('cal-timer-fill');
const calCounter = document.getElementById('cal-counter');
const gazeDot = document.getElementById('gaze-dot');
const status = document.getElementById('status');
const btnStart = document.getElementById('btn-start');
const btnStop = document.getElementById('btn-stop');
const btnHeatmap = document.getElementById('btn-heatmap');
const recDot = document.getElementById('rec-dot');
const sampleCount = document.getElementById('sample-count');
const fileInput = document.getElementById('file-input');
const fileLayer = document.getElementById('file-layer');
const pdfIndicator = document.getElementById('pdf-indicator');
const pageBar = document.getElementById('page-bar');
const btnPagePrev = document.getElementById('btn-page-prev');
const btnPageNext = document.getElementById('btn-page-next');
const pageNum = document.getElementById('page-num');
btnPagePrev.addEventListener('click', function(e) { e.preventDefault(); navigateHtml('prev'); });
btnPageNext.addEventListener('click', function(e) { e.preventDefault(); navigateHtml('next'); });

// ── Calibration: 9-point ──
const MARGIN = 0.12;
const POINT_DURATION = 2000;  // 每点 2 秒
const CIRCUMFERENCE = 2 * Math.PI * 26;  // ≈ 163.36

let calPoints = [], calIdx = 0, calActive = false, calibrated = false;
let ringRaf = null, ringStart = 0;

function startRingAnimation() {
  if (ringRaf) cancelAnimationFrame(ringRaf);
  ringStart = performance.now();
  calTimerFill.style.strokeDashoffset = CIRCUMFERENCE;
  function tick(now) {
    let elapsed = now - ringStart;
    let progress = Math.min(elapsed / POINT_DURATION, 1);
    calTimerFill.style.strokeDashoffset = CIRCUMFERENCE * (1 - progress);
    if (progress < 1) { ringRaf = requestAnimationFrame(tick); }
  }
  ringRaf = requestAnimationFrame(tick);
}

function genPoints() {
  let pts = [];
  for (let r = 0; r < 3; r++)
    for (let c = 0; c < 3; c++)
      pts.push({ x: MARGIN + c/2*(1-2*MARGIN), y: MARGIN + r/2*(1-2*MARGIN) });
  for (let i = pts.length - 1; i > 0; i--) {
    let j = Math.floor(Math.random() * (i + 1));
    [pts[i], pts[j]] = [pts[j], pts[i]];
  }
  return pts;
}

function advancePoint() {
  let p = calPoints[calIdx];
  let sx = p.x * window.innerWidth;
  let sy = p.y * window.innerHeight;
  webgazer.recordScreenPosition(sx, sy, 'click');
  if (calIdx + 1 >= 9) {
    calActive = false;
    calibrated = true;
    bubbleReady = false;  // 重置泡泡，下次注视重新定位
    bubbleVX = bubbleVY = 0;
    hoverCount = 0;         // 重置悬停计数
    resetParticles();       // 清空粒子
    calOverlay.classList.add('done');
    gazeDot.style.display = 'block';
    if (ringRaf) cancelAnimationFrame(ringRaf);
  } else {
    showDot(calIdx + 1);
  }
}

let pointTimer = null;

function showDot(i) {
  calIdx = i;
  calDot.style.left = (calPoints[i].x * 100) + '%';
  calDot.style.top  = (calPoints[i].y * 100) + '%';
  calCounter.textContent = '● '.repeat(i+1) + '○ '.repeat(8-i);
  calDot.style.animation = 'none';
  calDot.offsetHeight;
  calDot.style.animation = 'cal-pulse 2s ease-in-out infinite';
  startRingAnimation();
  clearTimeout(pointTimer);
  pointTimer = setTimeout(advancePoint, POINT_DURATION);
}

calOverlay.onclick = function() {
  if (!calActive) return;
  clearTimeout(pointTimer);
  advancePoint();
};

// ── 录制状态 ──
let sessionId = null;
let sampleIdx = 0;
let sendTimer = null;
let buffer = [];           // 本地缓冲，攒够一批再发
let recordedSamples = [];  // 完整记录（热力图用）
const BATCH_SIZE = 20;     // 每批 20 条
const FLUSH_INTERVAL = 500; // 最多 500ms 发送一次

// ── 页面上下文（翻页/滚动 → 热力图映射）──
// sx,sy = 内容视口在屏幕上的位置    scroll_x,scroll_y = 内容内部的滚动偏移
// cw,ch = 内容原始总尺寸    csw,csh = 视口在屏幕上的渲染尺寸
// 热力图转换（PDF/图片，不滚动）:
//   doc_x = (gaze_x - sx) * (cw / csw)
//   doc_y = (gaze_y - sy) * (ch / csh)
// 热力图转换（HTML/Word，可滚动）:
//   doc_x = (gaze_x - sx) * (cw / csw) + scroll_x
//   doc_y = (gaze_y - sy) * (ch / csh) + scroll_y
function getPageContext() {
  // PDF/PPTX 用 pdfPage，HTML 用 htmlPage
  var page = pdfDoc ? pdfPage : (htmlPage || 0);
  var scroll_x = 0, scroll_y = 0;

  // ── iframe（HTML / Word 渲染）──
  var iframe = fileLayer.querySelector('iframe');
  if (iframe) {
    var ir = iframe.getBoundingClientRect();
    var cw = 0, ch = 0;
    try {
      if (iframe.contentDocument) {
        var doc = iframe.contentDocument;
        scroll_x = doc.documentElement.scrollLeft || doc.body.scrollLeft || 0;
        scroll_y = doc.documentElement.scrollTop || doc.body.scrollTop || 0;
        cw = doc.documentElement.scrollWidth || doc.body.scrollWidth || 0;
        ch = doc.documentElement.scrollHeight || doc.body.scrollHeight || 0;
      }
    } catch(e) {}
    return {page: page,
            sx: Math.round(ir.left), sy: Math.round(ir.top),
            scroll_x: Math.round(scroll_x), scroll_y: Math.round(scroll_y),
            cw: Math.round(cw), ch: Math.round(ch),
            csw: Math.round(ir.width), csh: Math.round(ir.height)};
  }

  // ── PDF / PPTX canvas（不滚动，只有翻页）──
  if (pdfDoc) {
    var canvas = fileLayer.querySelector('canvas');
    if (canvas) {
      var r = canvas.getBoundingClientRect();
      return {page: page,
              sx: Math.round(r.left), sy: Math.round(r.top),
              scroll_x: 0, scroll_y: 0,
              cw: Math.round(canvas.width), ch: Math.round(canvas.height),
              csw: Math.round(r.width), csh: Math.round(r.height)};
    }
  }

  // ── 图片（不滚动）──
  var img = fileLayer.querySelector('img');
  if (img) {
    var r = img.getBoundingClientRect();
    return {page: page,
            sx: Math.round(r.left), sy: Math.round(r.top),
            scroll_x: 0, scroll_y: 0,
            cw: Math.round(img.naturalWidth || 0), ch: Math.round(img.naturalHeight || 0),
            csw: Math.round(r.width), csh: Math.round(r.height)};
  }

  return {page: page, sx: 0, sy: 0, scroll_x: 0, scroll_y: 0,
          cw: 0, ch: 0, csw: 0, csh: 0};
}

// ── 热力图叠加 ──
function removeHeatmapOverlay() {
  // iframe 内
  var iframe = fileLayer.querySelector('iframe');
  if (iframe && iframe.contentDocument) {
    try {
      var old = iframe.contentDocument.getElementById('eyeux-heatmap-layer');
      if (old) old.remove();
    } catch(e) {}
  }
  // fileLayer 内（PDF/图片）
  var old = fileLayer.querySelector('#eyeux-heatmap-layer');
  if (old) old.remove();
}

// ── 视频预览开关 ──
let videoVisible = true;
function toggleVideo() {
  var c = document.getElementById('webgazerVideoContainer');
  if (!c) return;
  videoVisible = !videoVisible;
  c.style.display = videoVisible ? '' : 'none';
  var btn = document.getElementById('btn-video');
  if (btn) btn.style.background = videoVisible ? '#555' : '#e67e22';
}

// ── 目光红点开关 ──
let gazeDotVisible = true;
function toggleGazeDot() {
  gazeDotVisible = !gazeDotVisible;
  gazeDot.style.display = gazeDotVisible ? 'block' : 'none';
  var btn = document.getElementById('btn-gazedot');
  if (btn) btn.style.background = gazeDotVisible ? '#555' : '#e67e22';
}

function showHeatmap() {
  if (!recordedSamples.length) return;
  btnHeatmap.textContent = '⏳ Generating...';
  btnHeatmap.disabled = true;

  // 调试：统计每页采样数
  var pageDist = {};
  recordedSamples.forEach(function(s) { pageDist[s.page] = (pageDist[s.page] || 0) + 1; });
  console.log('[EyeUX] Samples per page:', JSON.stringify(pageDist));
  console.log('[EyeUX] Total samples:', recordedSamples.length, ' current htmlPage:', htmlPage, ' pdfPage:', pdfPage);

  // PDF/PPTX/HTML 翻页：只看当前页的注视点
  var samplesToSend = recordedSamples;
  var curPage = pdfDoc ? pdfPage : (htmlPage > 0 ? htmlPage : 0);
  if (curPage > 0) {
    samplesToSend = recordedSamples.filter(function(s) { return s.page === curPage; });
    if (!samplesToSend.length) {
      btnHeatmap.textContent = 'No data for page ' + curPage;
      btnHeatmap.disabled = false;
      return;
    }
  }

  // 判断模式：滚动型（文档坐标, noScale）vs 幻灯型（视口坐标, 按页分）
  var iframe = fileLayer.querySelector('iframe');
  var useViewport = false, noScale = false;
  var viewW = 0, viewH = 0;
  if (iframe) {
    var ir = iframe.getBoundingClientRect();
    viewW = Math.round(ir.width);
    viewH = Math.round(ir.height);
    try {
      var doc = iframe.contentDocument;
      var docH = doc.documentElement.scrollHeight || doc.body.scrollHeight || 0;
      useViewport = (docH <= viewH * 1.2);  // 幻灯型 → 视口坐标
      noScale = !useViewport;               // 滚动型 → 文档坐标，1:1 不缩放
    } catch(e) { useViewport = true; }
  }

  fetch('/api/heatmap', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      samples: samplesToSend,
      viewportMode: useViewport,
      noScale: noScale,
      viewW: viewW, viewH: viewH
    })
  })
  .then(function(r) {
    if (!r.ok) return r.json().then(function(d) { throw new Error(d.error || 'fail'); });
    return r.blob();
  })
  .then(function(blob) {
    var url = URL.createObjectURL(blob);

    // ── 注入 iframe（HTML / Word）──
    var iframe = fileLayer.querySelector('iframe');
    if (iframe && iframe.contentDocument) {
      try {
        removeHeatmapOverlay();
        var img = iframe.contentDocument.createElement('img');
        img.id = 'eyeux-heatmap-layer';
        img.src = url;
        img.style.cssText = 'position:absolute;top:0;left:0;width:100%;height:auto;' +
          'pointer-events:none;z-index:9999;opacity:0.55;mix-blend-mode:difference';
        iframe.contentDocument.body.appendChild(img);
        btnHeatmap.textContent = '🔥 Refresh';
        btnHeatmap.style.background = '#27ae60';
        btnHeatmap.disabled = false;
        return;
      } catch(e) {}
    }

    // ── PDF / PPTX canvas ──
    var canvas = fileLayer.querySelector('canvas');
    if (canvas) {
      removeHeatmapOverlay();
      var img = document.createElement('img');
      img.id = 'eyeux-heatmap-layer';
      img.src = url;
      img.style.cssText = 'position:absolute;pointer-events:none;z-index:5;' +
        'opacity:0.5;mix-blend-mode:difference;max-width:100%;max-height:100%';
      fileLayer.appendChild(img);
      btnHeatmap.textContent = '🔥 Refresh';
      btnHeatmap.style.background = '#27ae60';
      btnHeatmap.disabled = false;
      return;
    }

    // ── 图片 ──
    var imgEl = fileLayer.querySelector('img:not(#eyeux-heatmap-layer)');
    if (imgEl) {
      removeHeatmapOverlay();
      var overlay = document.createElement('img');
      overlay.id = 'eyeux-heatmap-layer';
      overlay.src = url;
      overlay.style.cssText = 'position:absolute;pointer-events:none;z-index:5;' +
        'opacity:0.5;mix-blend-mode:difference;max-width:100%;max-height:100%';
      fileLayer.appendChild(overlay);
      btnHeatmap.textContent = '🔥 Refresh';
      btnHeatmap.style.background = '#27ae60';
      btnHeatmap.disabled = false;
      return;
    }
  })
  .catch(function(e) {
    btnHeatmap.textContent = '❌ Failed';
    btnHeatmap.disabled = false;
    console.error(e);
  });
}

// ── HTML 翻页追踪 ──
let htmlPage = 0, lastIframeHash = '', hashPollTimer = null;

function setupIframeHashWatch(iframe) {
  htmlPage = 1; lastIframeHash = '';
  updateHtmlPageUI();

  // 每 500ms 轮询 hash 变化（最简单可靠的方式）
  if (hashPollTimer) clearInterval(hashPollTimer);
  hashPollTimer = setInterval(function() {
    try {
      var win = iframe.contentWindow;
      if (!win) return;
      var h = win.location.hash;
      if (h && h !== lastIframeHash) {
        var n = parseInt(h.replace(/[^0-9]/g,''));
        htmlPage = n || htmlPage + 1;
        lastIframeHash = h;
        updateHtmlPageUI();
      }
    } catch(e) {}
  }, 500);
}

function htmlPageUp()   { if (htmlPage > 1) { htmlPage--; updateHtmlPageUI(); } }
function htmlPageDown() { htmlPage++; updateHtmlPageUI(); }

// 翻页按钮：更新计数器 + 真正让 iframe 内 HTML 翻页
function navigateHtml(dir) {
  if (dir === 'next') htmlPageDown(); else htmlPageUp();

  var iframe = fileLayer.querySelector('iframe');
  if (!iframe) return;
  try {
    var win = iframe.contentWindow;
    var doc = iframe.contentDocument;
    if (!win || !doc) return;

    // 方法1：注入键盘事件（reveal.js 等框架用方向键翻页）
    var key = (dir === 'next') ? 'ArrowRight' : 'ArrowLeft';
    var opts = {key: key, code: key, keyCode: (dir==='next'?39:37),
                which: (dir==='next'?39:37), bubbles: true, cancelable: true, view: win};
    doc.dispatchEvent(new win.KeyboardEvent('keydown', opts));
    doc.dispatchEvent(new win.KeyboardEvent('keyup', opts));

    // 方法2：点击页内导航按钮（部分框架）
    var sel = (dir === 'next') ? '.navigate-next,.next,[data-nav="next"]'
                                : '.navigate-prev,.prev,[data-nav="prev"]';
    var btn = doc.querySelector(sel);
    if (btn) btn.click();

    // 方法3：修改 hash（对于 hash 路由的幻灯）
    if (dir === 'next') {
      var n = htmlPage;
    } else {
      var n = htmlPage;
    }
    try {
      // reveal.js: #/N
      win.location.hash = '#/' + htmlPage;
    } catch(e) {}
  } catch(e) {
    console.error('navigateHtml error:', e);
  }
}
function updateHtmlPageUI() {
  if (htmlPage > 0) {
    pageBar.style.display = 'flex';
    pageNum.textContent = 'P' + htmlPage;
  } else {
    pageBar.style.display = 'none';
  }
}

// 主窗口键盘：←↑ 上一页  →↓ 下一页
window.addEventListener('keydown', function(e) {
  if (!htmlPage || pdfDoc) return;
  if (e.key === 'ArrowRight' || e.key === 'ArrowDown')  { e.preventDefault(); navigateHtml('next'); }
  if (e.key === 'ArrowLeft'  || e.key === 'ArrowUp')    { e.preventDefault(); navigateHtml('prev'); }
});

// ── 文件浏览状态 ──
let currentFileName = '';
let pdfDoc = null, pdfPage = 1, pdfTotalPages = 0;

function startRecording() {
  fetch('/api/start', {method:'POST'})
    .then(r => r.json())
    .then(data => {
      sessionId = data.session_id;
      sampleIdx = 0;
      buffer = [];
      recordedSamples = [];
      btnStart.style.display = 'none';
      btnStop.style.display = 'inline';
      btnHeatmap.style.display = 'none';
      recDot.style.display = 'inline';
      sampleCount.textContent = 'samples: 0';
      status.textContent = 'REC ● ' + sessionId.slice(0,8) + (currentFileName ? ' | ' + currentFileName : '');
      // 清理上一轮的旧热力图叠加层
      removeHeatmapOverlay();
    })
    .catch(e => { alert('Failed to start recording: ' + e); });
}

function stopRecording() {
  // 先 flush 剩余的 buffer
  flushBuffer();
  if (sendTimer) clearTimeout(sendTimer);
  fetch('/api/stop', {method:'POST'})
    .then(r => r.json())
    .then(data => {
      sessionId = null;
      btnStart.style.display = 'inline';
      btnStop.style.display = 'none';
      recDot.style.display = 'none';
      status.textContent = 'Saved: ' + (data.total_samples || 0) + ' samples → ' + (data.csv_file || '');
      if (recordedSamples.length > 0) {
        btnHeatmap.style.display = 'inline';
        btnHeatmap.textContent = '🔥 Heatmap';
        btnHeatmap.style.background = '#e67e22';
        btnHeatmap.disabled = false;
      }
    })
    .catch(e => { console.error(e); });
}

function flushBuffer() {
  if (buffer.length === 0) return;
  let batch = buffer.splice(0);
  fetch('/api/gaze', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      session_id: sessionId,
      samples: batch
    })
  }).catch(e => console.error('flush error:', e));
}

// ── 文件浏览 ──
fileInput.onchange = function(e) {
  let file = e.target.files[0];
  if (!file) return;
  // 清理上一个文件的录制数据和 UI
  recordedSamples = [];
  removeHeatmapOverlay();
  if (hashPollTimer) { clearInterval(hashPollTimer); hashPollTimer = null; }
  btnHeatmap.style.display = 'none';
  htmlPage = 0; updateHtmlPageUI();
  currentFileName = file.name;
  pdfDoc = null; pdfPage = 1; pdfTotalPages = 0;
  htmlPage = 0; lastIframeHash = '';
  pdfIndicator.style.display = 'none';
  let url = URL.createObjectURL(file);
  let ext = file.name.split('.').pop().toLowerCase();
  if (['jpg','jpeg','png','gif','webp','bmp'].includes(ext)) {
    renderImage(url);
  } else if (ext === 'pdf') {
    renderPDF(url);
  } else if (ext === 'docx') {
    renderDocx(url);
  } else if (['pptx'].includes(ext)) {
    renderPptx(file);
  } else if (['html','htm'].includes(ext)) {
    file.text().then(function(t) { renderHTML(t); });
  } else {
    renderText(url, ext);
  }
};

function renderImage(url) {
  fileLayer.innerHTML = '<img src="' + url + '">';
}

function renderPDF(url) {
  pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
  pdfjsLib.getDocument(url).promise.then(function(pdf) {
    pdfDoc = pdf;
    pdfTotalPages = pdf.numPages;
    pdfPage = 1;
    renderPage(1);
  }).catch(function(e) { console.error(e); });
}

function renderPage(num) {
  if (!pdfDoc) return;
  pdfDoc.getPage(num).then(function(page) {
    let vp = page.getViewport({scale: 1});
    let scale = Math.min(window.innerWidth / vp.width, window.innerHeight / vp.height, 1.5);
    let viewport = page.getViewport({scale: scale});
    let canvas = document.createElement('canvas');
    canvas.width = viewport.width;
    canvas.height = viewport.height;
    let ctx = canvas.getContext('2d');
    fileLayer.innerHTML = '';
    fileLayer.appendChild(canvas);
    page.render({canvasContext: ctx, viewport: viewport});
    pdfPage = num;
    pdfIndicator.textContent = num + ' / ' + pdfTotalPages;
    pdfIndicator.style.display = 'block';
  });
}

function renderText(url, ext) {
  let iframe = document.createElement('iframe');
  iframe.className = 'text-iframe';
  iframe.src = url;
  fileLayer.innerHTML = '';
  fileLayer.appendChild(iframe);
}

function renderHTML(htmlText) {
  let iframe = document.createElement('iframe');
  iframe.className = 'text-iframe';
  iframe.srcdoc = htmlText;
  fileLayer.innerHTML = '';
  fileLayer.appendChild(iframe);
  setupIframeHashWatch(iframe);
  updateHtmlPageUI();
}

function renderDocx(url) {
  fetch(url).then(function(r) { return r.arrayBuffer(); })
  .then(function(buf) {
    return mammoth.convertToHtml({arrayBuffer: buf});
  })
  .then(function(result) {
    let html = result.value;
    // 注入基础样式，让 Word 内容更接近原版排版
    let styled = '<style>body{font-family:Calibri,sans-serif;font-size:16px;' +
      'line-height:1.6;color:#ddd;padding:40px 60px;max-width:900px;margin:0 auto;' +
      'background:#1a1a2e}' +
      'img{max-width:100%}table{border-collapse:collapse;width:100%}' +
      'td,th{border:1px solid #555;padding:6px 10px}' +
      '</style>' + html;
    let iframe = document.createElement('iframe');
    iframe.className = 'text-iframe';
    fileLayer.innerHTML = '';
    fileLayer.appendChild(iframe);
    iframe.contentDocument.write(styled);
    iframe.contentDocument.close();
    setupIframeHashWatch(iframe);
    updateHtmlPageUI();
  }).catch(function(e) { console.error('docx error:', e); });
}

// ── PPTX 渲染（PowerPoint COM → PDF → PDF.js）──
function renderPptx(file) {
  currentFileName = file.name;
  pdfDoc = null; pdfPage = 1; pdfTotalPages = 0;
  pdfIndicator.style.display = 'none';

  fileLayer.innerHTML = '<div style="color:#fff;text-align:center;padding-top:40vh;font-family:monospace;font-size:16px;">🔄 Converting PPTX → PDF...</div>';

  file.arrayBuffer().then(function(buf) {
    fetch('/api/convert-pptx', {
      method: 'POST',
      headers: {'Content-Type': 'application/octet-stream'},
      body: buf
    })
    .then(function(r) {
      var ct = r.headers.get('Content-Type') || '';
      if (ct.indexOf('application/pdf') !== -1) {
        return r.blob().then(function(blob) {
          var url = URL.createObjectURL(blob);
          renderPDF(url);
        });
      } else {
        return r.json().then(function(data) {
          fileLayer.innerHTML = '<div style="color:#e74c3c;text-align:center;padding-top:40vh;font-family:monospace;">PPTX error: ' + (data.error || 'unknown') + '<br><br>请安装 PowerPoint 或 LibreOffice</div>';
        });
      }
    })
    .catch(function(e) {
      fileLayer.innerHTML = '<div style="color:#e74c3c;text-align:center;padding-top:40vh;font-family:monospace;">Request failed: ' + e + '</div>';
    });
  });
}

// PDF 滚轮翻页
window.addEventListener('wheel', function(e) {
  if (!pdfDoc) return;
  e.preventDefault();
  if (e.deltaY > 0 && pdfPage < pdfTotalPages) renderPage(pdfPage + 1);
  else if (e.deltaY < 0 && pdfPage > 1) renderPage(pdfPage - 1);
}, {passive: false});

// ── 1€ Filter 实例（闭包变量，校准完成后初始化）──
let filterX = null, filterY = null;

// ── 弹簧惯性物理（橡皮筋重物：过冲 + 回弹）──
const DEAD_ZONE_RADIUS = 200;     // 死区半径 (px)
const STIFFNESS = 0.12;          // 弹簧刚度 → 0.08~0.12s 延迟
const DAMPING = 0.89;            // 阻尼 < 1 → 欠阻尼过冲，急停时滑出 3~5mm 再弹回
const MAX_STRETCH = 0.30;        // 最大拉伸比例 (1.0 → 1.30)
const STRETCH_SPEED = 15;        // 速度阈值 (px/frame) → 约 22°/s
const BREATH_PERIOD = 2000;      // 呼吸周期
const BREATH_AMPLITUDE = 0.06;   // 呼吸幅度
const HOVER_FRAMES = 22;         // 悬停触发帧数
const SHOCKWAVE_COOLDOWN = 800;  // 冲击波冷却 (ms)

let bubbleTargetX = null;
let bubbleTargetY = null;
let bubbleX = null;
let bubbleY = null;
let bubbleVX = 0;
let bubbleVY = 0;
let bubbleReady = false;
let physicsRunning = false;
let hoverCount = 0;
let lastShockTime = 0;

function spawnShockwave(x, y) {
  var ring = document.createElement('div');
  ring.className = 'shockwave-ring';
  ring.style.left = x + 'px';
  ring.style.top = y + 'px';
  document.body.appendChild(ring);
  setTimeout(function() { ring.remove(); }, 900);
}

// ── 末端粒子消散（20~30 个光点，寿命 0.3s）──
const MAX_PARTICLES = 25;
const PARTICLE_LIFE = 0.30;
const PARTICLE_SIZE = 13;
const PARTICLE_SPEED_MIN = 0.5;
const PARTICLE_SPEED_MAX = 3.0;
const PARTICLE_SPREAD = Math.PI * 0.55;
const PARTICLE_DAMPING = 0.91;

let particles = [];
let particleEls = [];

function initParticles() {
  for (var i = 0; i < MAX_PARTICLES; i++) {
    var el = document.createElement('div');
    el.className = 'gaze-droplet';
    el.style.display = 'none';
    document.body.appendChild(el);
    particleEls.push(el);
    particles.push({
      active: false,
      x: 0, y: 0, vx: 0, vy: 0,
      life: 0, maxLife: PARTICLE_LIFE
    });
  }
}

function resetParticles() {
  for (var i = 0; i < MAX_PARTICLES; i++) {
    particles[i].active = false;
    particleEls[i].style.display = 'none';
  }
}

initParticles();

// ── 弹簧惯性 + 粒子消散 动画循环 ──
function physicsTick() {
  if (!bubbleReady || !calibrated) {
    physicsRunning = false;
    return;
  }

  var now = Date.now();

  // ── 1. 弹簧物理（欠阻尼 → 急停时过冲滑出再弹回，0.08~0.12s 延迟）──
  var fx = STIFFNESS * (bubbleTargetX - bubbleX);
  var fy = STIFFNESS * (bubbleTargetY - bubbleY);
  bubbleVX = (bubbleVX + fx) * DAMPING;
  bubbleVY = (bubbleVY + fy) * DAMPING;
  bubbleX += bubbleVX;
  bubbleY += bubbleVY;

  gazeDot.style.left = bubbleX + 'px';
  gazeDot.style.top  = bubbleY + 'px';

  // ── 2. 速度响应拉伸（>22°/s 时椭圆变形，长轴沿运动方向拉至 1.30 倍）──
  var speed = Math.sqrt(bubbleVX * bubbleVX + bubbleVY * bubbleVY);
  var breath = 1 + Math.sin(now / BREATH_PERIOD * Math.PI * 2) * BREATH_AMPLITUDE;
  var stretch = speed > STRETCH_SPEED ? Math.min((speed - STRETCH_SPEED) * 0.008, MAX_STRETCH) : 0;

  if (stretch > 0.008) {
    var angle = Math.atan2(bubbleVY, bubbleVX) * 180 / Math.PI;
    var sx = (1 + stretch) * breath;
    var sy = (1 - stretch * 0.50) * breath;
    gazeDot.style.transform =
      'rotate(' + angle.toFixed(1) + 'deg) ' +
      'scaleX(' + sx.toFixed(3) + ') ' +
      'scaleY(' + sy.toFixed(3) + ')';
  } else {
    gazeDot.style.transform = 'scale(' + breath.toFixed(3) + ')';
  }

  // ── 3. 悬停冲击波 ──
  var rdx = bubbleTargetX - bubbleX;
  var rdy = bubbleTargetY - bubbleY;
  var remaining = Math.sqrt(rdx * rdx + rdy * rdy);

  if (remaining < 1.5 && speed < 1.0) {
    var elUnder = document.elementFromPoint(bubbleX, bubbleY);
    if (elUnder) {
      var interactive = elUnder.closest('button, a, input, [role="button"], [onclick]');
      if (interactive) {
        hoverCount++;
        if (hoverCount === HOVER_FRAMES && now - lastShockTime > SHOCKWAVE_COOLDOWN) {
          spawnShockwave(bubbleX, bubbleY);
          lastShockTime = now;
        }
      } else { hoverCount = 0; }
    } else { hoverCount = 0; }
  } else { hoverCount = 0; }

  // ── 4. 末端粒子消散 — 在泡泡后方撒出 25 个光点，寿命 0.3s ──
  var tailX = bubbleX;
  var tailY = bubbleY;

  if (speed > 3) {
    var spawnCount = Math.min(2, 1 + Math.floor(speed / 10));
    for (var s = 0; s < spawnCount; s++) {
      for (var pi = 0; pi < MAX_PARTICLES; pi++) {
        if (!particles[pi].active) {
          var p = particles[pi];
          var baseA = Math.atan2(-bubbleVY, -bubbleVX);
          var spread = (Math.random() - 0.5) * PARTICLE_SPREAD;
          var a = baseA + spread;
          var spd = PARTICLE_SPEED_MIN + Math.random() * (PARTICLE_SPEED_MAX - PARTICLE_SPEED_MIN);
          p.x = tailX + (Math.random() - 0.5) * 20;
          p.y = tailY + (Math.random() - 0.5) * 20;
          p.vx = Math.cos(a) * spd;
          p.vy = Math.sin(a) * spd;
          p.life = PARTICLE_LIFE;
          p.maxLife = PARTICLE_LIFE;
          p.active = true;
          break;
        }
      }
    }
  }

  for (var pi = 0; pi < MAX_PARTICLES; pi++) {
    var p = particles[pi];
    if (!p.active) continue;
    p.life -= 0.016;
    if (p.life <= 0) {
      p.active = false;
      particleEls[pi].style.display = 'none';
      continue;
    }
    p.vx *= PARTICLE_DAMPING;
    p.vy *= PARTICLE_DAMPING;
    p.x += p.vx;
    p.y += p.vy;
    var ratio = p.life / p.maxLife;
    var sz = PARTICLE_SIZE * (0.25 + ratio * 0.75);
    var op = 0.42 * ratio;
    particleEls[pi].style.display = '';
    particleEls[pi].style.left = p.x + 'px';
    particleEls[pi].style.top = p.y + 'px';
    particleEls[pi].style.width = sz + 'px';
    particleEls[pi].style.height = sz + 'px';
    particleEls[pi].style.opacity = op.toFixed(2);
  }

  requestAnimationFrame(physicsTick);
}

// ── Init WebGazer ──
webgazer
  .setRegression('ridge')
  .setTracker('TFFacemesh')
  .showVideoPreview(true)
  .showFaceOverlay(true)
  .showFaceFeedbackBox(false)
  .showPredictionPoints(false)
  .setGazeListener(function(data) {
    if (!data || !calibrated) return;
    let x = data.x, y = data.y;
    if (x == null || y == null) return;

    // 校准完成后初始化滤波器（只初始化一次）
    // 参数说明: freq=30Hz, mincutoff=0.3(注视时超强平滑), beta=0.001(速度敏感度极低), dcutoff=1.0
    if (!filterX) {
      filterX = new OneEuroFilter(30, 0.3, 0.001, 1.0);
      filterY = new OneEuroFilter(30, 0.3, 0.001, 1.0);
    }

    // 1€ Filter 平滑
    var ts = Date.now();
    x = filterX.filter(x, ts);
    y = filterY.filter(y, ts);

    // 边界裁剪：确保坐标不超出屏幕
    x = Math.max(0, Math.min(x, window.innerWidth - 1));
    y = Math.max(0, Math.min(y, window.innerHeight - 1));

    // ── 死区 + 弹簧物理：更新目标，物理循环负责渲染 ──
    if (!bubbleReady) {
      // 首次定位：目标和当前位置都吸附到第一个注视点
      bubbleTargetX = bubbleX = x;
      bubbleTargetY = bubbleY = y;
      bubbleVX = bubbleVY = 0;
      bubbleReady = true;
      if (!physicsRunning) {
        physicsRunning = true;
        requestAnimationFrame(physicsTick);
      }
    } else {
      // 死区：以目标位置为中心，目光移出半径才更新目标
      var dx = x - bubbleTargetX;
      var dy = y - bubbleTargetY;
      if (Math.sqrt(dx * dx + dy * dy) >= DEAD_ZONE_RADIUS) {
        bubbleTargetX = x;
        bubbleTargetY = y;
      }
      // 微小眼动不更新目标 → 泡泡物理动画稳定在原地
    }
    var ctx = getPageContext();
    var extra = (currentFileName ? ' | ' + currentFileName : '') + (ctx.page > 0 ? ' | P' + ctx.page : '');
    status.textContent = 'x:' + String(Math.round(x)).padStart(4,' ') + '  y:' + String(Math.round(y)).padStart(4,' ') + extra;

    // ── 录制中：缓冲数据 ──
    if (sessionId && x > 0 && x < window.innerWidth && y > 0 && y < window.innerHeight) {
      buffer.push({
        ts: Date.now(),
        x: Math.round(x * 10) / 10,
        y: Math.round(y * 10) / 10,
        sw: window.innerWidth,
        sh: window.innerHeight,
        page: ctx.page,
        sx: ctx.sx,
        sy: ctx.sy,
        scx: ctx.scroll_x,
        scy: ctx.scroll_y,
        cw: ctx.cw,
        ch: ctx.ch,
        csw: ctx.csw,
        csh: ctx.csh,
        fn: currentFileName
      });
      // 同步存完整记录（热力图用）
      recordedSamples.push({
        x: x, y: y,
        page: ctx.page, sx: ctx.sx, sy: ctx.sy,
        scx: ctx.scroll_x, scy: ctx.scroll_y,
        cw: ctx.cw, ch: ctx.ch,
        csw: ctx.csw, csh: ctx.csh
      });
      sampleIdx++;
      sampleCount.textContent = 'samples: ' + sampleIdx;

      // 攒够一批就发，或用定时器兜底
      if (buffer.length >= BATCH_SIZE) {
        flushBuffer();
      } else if (!sendTimer) {
        sendTimer = setTimeout(function() {
          sendTimer = null;
          flushBuffer();
        }, FLUSH_INTERVAL);
      }
    }
  })
  .begin();

// 页面关闭前 flush
window.addEventListener('beforeunload', function() {
  if (sessionId) flushBuffer();
});

// 窗口大小变化时重渲 PDF
window.addEventListener('resize', function() {
  if (pdfDoc && pdfPage) renderPage(pdfPage);
});

setTimeout(function() {
  status.textContent = 'Click each dot to calibrate';
  calPoints = genPoints();
  calActive = true;
  showDot(0);
}, 2000);
</script>
</body>
</html>"""


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT_DIR), **kwargs)

    def log_message(self, fmt, *args):
        pass

    def _send_json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.end_headers()
            self.wfile.write(HTML.encode("utf-8"))
        else:
            super().do_GET()

    def do_POST(self):
        global current_session

        if self.path == "/api/start":
            # ── 关闭旧 session（如果开着） ──
            if current_session:
                current_session["csv_file"].close()

            sid = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]
            csv_path = DATA_DIR / f"gaze_{sid}.csv"
            f = open(csv_path, "w", newline="", encoding="utf-8")
            w = csv.writer(f)
            w.writerow(["timestamp_ms", "x", "y", "screen_width", "screen_height",
                        "page", "view_x", "view_y", "scroll_x", "scroll_y",
                        "content_w", "content_h", "view_w", "view_h",
                        "file_name", "session_id"])

            current_session = {
                "id": sid,
                "csv_path": str(csv_path),
                "csv_file": f,
                "csv_writer": w,
                "start_time": time.time(),
                "count": 0,
            }
            print(f"[REC] {sid}  →  {csv_path}")
            self._send_json({"ok": True, "session_id": sid})

        elif self.path == "/api/stop":
            if not current_session:
                self._send_json({"ok": False, "error": "no active session"}, 400)
                return

            total = current_session["count"]
            csv_path = current_session["csv_path"]

            # 写 session 摘要 JSON
            meta = {
                "session_id": current_session["id"],
                "start_time": datetime.fromtimestamp(current_session["start_time"]).isoformat(),
                "duration_s": round(time.time() - current_session["start_time"], 1),
                "total_samples": total,
                "csv_file": str(csv_path),
                "screen_width": None,   # 由样本中推断
                "screen_height": None,
            }
            meta_path = DATA_DIR / f"meta_{current_session['id']}.json"
            with open(meta_path, "w", encoding="utf-8") as mf:
                json.dump(meta, mf, ensure_ascii=False, indent=2)

            current_session["csv_file"].close()
            print(f"[STOP] {current_session['id']}  total={total} samples  →  {csv_path}")
            current_session = None
            self._send_json({
                "ok": True,
                "total_samples": total,
                "csv_file": csv_path,
            })

        elif self.path == "/api/gaze":
            if not current_session:
                self._send_json({"ok": False, "error": "no active session"}, 400)
                return

            content_len = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(content_len))
            samples = body.get("samples", [])
            sid = current_session["id"]

            w = current_session["csv_writer"]
            for s in samples:
                w.writerow([s["ts"], s["x"], s["y"], s["sw"], s["sh"],
                            s.get("page", 0), s.get("sx", 0), s.get("sy", 0),
                            s.get("scx", 0), s.get("scy", 0),
                            s.get("cw", 0), s.get("ch", 0),
                            s.get("csw", 0), s.get("csh", 0),
                            s.get("fn", ""), sid])
            current_session["csv_file"].flush()  # 保证掉电不丢数据
            current_session["count"] += len(samples)

            self._send_json({"ok": True, "received": len(samples)})

        elif self.path == "/api/convert-pptx":
            content_len = int(self.headers.get("Content-Length", 0))
            pptx_bytes = self.rfile.read(content_len)

            import subprocess
            import tempfile

            tmpdir = tempfile.mkdtemp()
            pptx_path = os.path.join(tmpdir, "input.pptx")
            pdf_path = os.path.join(tmpdir, "output.pdf")

            try:
                with open(pptx_path, "wb") as f:
                    f.write(pptx_bytes)

                converted = False

                # ── 方法 1: PowerPoint COM（Windows, 完美保真）──
                try:
                    import pythoncom
                    import win32com.client
                    pythoncom.CoInitialize()
                    try:
                        powerpoint = win32com.client.Dispatch("PowerPoint.Application")
                        try:
                            presentation = powerpoint.Presentations.Open(
                                pptx_path, WithWindow=False
                            )
                            presentation.SaveAs(pdf_path, 32)  # 32 = ppSaveAsPDF
                            presentation.Close()
                            converted = True
                        finally:
                            try:
                                powerpoint.Quit()
                            except Exception:
                                pass
                    finally:
                        pythoncom.CoUninitialize()
                except Exception as com_err:
                    print(f"[PPTX] PowerPoint COM failed: {com_err}")

                # ── 方法 2: LibreOffice 兜底 ──
                if not converted:
                    try:
                        result = subprocess.run(
                            [
                                "libreoffice", "--headless", "--convert-to", "pdf",
                                "--outdir", tmpdir, pptx_path,
                            ],
                            capture_output=True, timeout=60,
                        )
                        lo_pdf = os.path.join(tmpdir, "input.pdf")
                        if os.path.exists(lo_pdf):
                            os.rename(lo_pdf, pdf_path)
                            converted = True
                        else:
                            print(f"[PPTX] LibreOffice failed: {result.stderr.decode()}")
                    except Exception as lo_err:
                        print(f"[PPTX] LibreOffice failed: {lo_err}")

                if not converted:
                    raise RuntimeError(
                        "No converter available. Install PowerPoint or LibreOffice."
                    )

                with open(pdf_path, "rb") as f:
                    pdf_bytes = f.read()

                print(f"[PPTX→PDF] {len(pptx_bytes)} → {len(pdf_bytes)} bytes, {os.path.getsize(pptx_path)} pptx")
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf")
                self.send_header("Content-Length", str(len(pdf_bytes)))
                self.end_headers()
                self.wfile.write(pdf_bytes)

            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            finally:
                for p in [pptx_path, pdf_path]:
                    try:
                        os.unlink(p)
                    except Exception:
                        pass
                try:
                    os.rmdir(tmpdir)
                except Exception:
                    pass

        elif self.path == "/api/heatmap":
            content_len = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(content_len))
            samples = body.get("samples", [])

            if not samples:
                self._send_json({"ok": False, "error": "no samples"}, 400)
                return

            try:
                import io as _io
                import numpy as np
                import matplotlib
                matplotlib.use("Agg")
                import matplotlib.pyplot as plt
                from matplotlib.colors import LinearSegmentedColormap
                from scipy.ndimage import gaussian_filter
            except ImportError as e:
                self._send_json({"ok": False, "error": f"Missing package: {e}"}, 500)
                return

            try:
                viewport_mode = body.get("viewportMode", False)
                no_scale = body.get("noScale", False)
                view_w = body.get("viewW", 0)
                view_h = body.get("viewH", 0)

                docs = []
                cw = ch = 768
                for s in samples:
                    vx = s.get("sx", 0)
                    vy = s.get("sy", 0)

                    if viewport_mode and view_w > 0 and view_h > 0:
                        # 幻灯型：视口坐标
                        dx = s["x"] - vx
                        dy = s["y"] - vy
                        cw, ch = view_w, view_h
                        if 0 <= dx <= cw and 0 <= dy <= ch:
                            docs.append((dx, dy))
                    elif no_scale:
                        # 滚动型 HTML：1:1 渲染，不缩放
                        scx = s.get("scx", 0)
                        scy = s.get("scy", 0)
                        _cw = s.get("cw", 0) or 1
                        _ch = s.get("ch", 0) or 1
                        cw, ch = _cw, _ch
                        dx = (s["x"] - vx) + scx
                        dy = (s["y"] - vy) + scy
                        if 0 <= dx <= _cw and 0 <= dy <= _ch:
                            docs.append((dx, dy))
                    else:
                        # PDF / 图片：缩放型文档坐标
                        scx = s.get("scx", 0)
                        scy = s.get("scy", 0)
                        _cw = s.get("cw", 0) or 1
                        _ch = s.get("ch", 0) or 1
                        _vsw = s.get("csw", 0) or 1
                        _vsh = s.get("csh", 0) or 1
                        cw, ch = _cw, _ch
                        dx = (s["x"] - vx) * (_cw / _vsw) + scx
                        dy = (s["y"] - vy) * (_ch / _vsh) + scy
                        if 0 <= dx <= _cw and 0 <= dy <= _ch:
                            docs.append((dx, dy))

                if not docs:
                    self._send_json({"ok": False, "error": "no valid doc coords"}, 400)
                    return

                docs = np.array(docs)
                cw = int(cw)
                ch = int(ch)

                bins_x = max(20, min(cw // 10, 200))
                bins_y = max(20, min(ch // 10, 200))
                h, xedges, yedges = np.histogram2d(
                    docs[:, 0], docs[:, 1],
                    bins=[bins_x, bins_y],
                    range=[[0, cw], [0, ch]],
                )

                sigma = max(1, min(bins_x, bins_y) / 15)
                h_smooth = gaussian_filter(h, sigma=sigma)
                h_max = h_smooth.max()
                if h_max > 0:
                    h_smooth = h_smooth / h_max

                dpi = 72
                fig_w = cw / dpi
                fig_h = ch / dpi
                max_inches = 200
                if fig_h > max_inches:
                    scale = max_inches / fig_h
                    fig_w *= scale
                    fig_h = max_inches

                fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=dpi,
                                        facecolor="none")
                ax.set_facecolor("none")

                colors = [
                    (0, 0, 0, 0),
                    (0, 0.8, 0, 0.2),
                    (1, 1, 0, 0.5),
                    (1, 0.3, 0, 0.7),
                    (1, 0, 0, 0.9),
                ]
                cmap = LinearSegmentedColormap.from_list("eyeux", colors, N=256)

                ax.imshow(h_smooth.T, extent=[0, cw, ch, 0],
                          cmap=cmap, aspect="auto", origin="upper",
                          interpolation="bilinear")
                ax.set_xlim(0, cw)
                ax.set_ylim(ch, 0)
                ax.axis("off")
                plt.tight_layout(pad=0)

                buf = _io.BytesIO()
                fig.savefig(buf, format="png", dpi=dpi, transparent=True,
                            bbox_inches="tight", pad_inches=0)
                plt.close(fig)
                buf.seek(0)
                png_bytes = buf.read()

                print(f"[HEATMAP] {len(docs)} points → {len(png_bytes)} bytes  ({cw}x{ch})")

                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(png_bytes)))
                self.end_headers()
                self.wfile.write(png_bytes)

            except Exception as e:
                import traceback
                traceback.print_exc()
                self._send_json({"ok": False, "error": str(e)}, 500)

        else:
            self.send_response(404)
            self.end_headers()


def main():
    print("=" * 50)
    print("  EyeUX — WebGazer 眼动追踪 + 数据存储")
    print(f"  http://localhost:{PORT}")
    print(f"  数据目录: {DATA_DIR}")
    print("=" * 50)

    server = http.server.HTTPServer(("0.0.0.0", PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    webbrowser.open(f"http://localhost:{PORT}")
    print("Ready. Ctrl+C to stop.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        # 清理
        if current_session:
            current_session["csv_file"].close()
        print("\nBye")


if __name__ == "__main__":
    main()
