"""
EyeUX — WebCam 眼动追踪可用性测试工具
用法: python server.py
数据保存到 %APPDATA%/EyeUX/data/，CSV 格式适合热力图等后续分析。
"""

import base64
import csv
import html as _html
import http.server
import io
import json
import os
import socket
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

ROOT_DIR = Path(__file__).parent

# ── 数据目录：%APPDATA%/EyeUX/data ──
def _get_data_dir() -> Path:
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        base = Path(appdata)
    else:
        base = Path.home() / "AppData" / "Roaming"
    d = base / "EyeUX" / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d

DATA_DIR = _get_data_dir()

# ── 端口自动检测 ──
def _find_port(start=8080, end=8090) -> int:
    for port in range(start, end + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return start  # fallback

PORT = _find_port()

# ── 读取 HTML 模板 ──
HTML_PATH = ROOT_DIR / "static" / "index.html"
HTML = HTML_PATH.read_text(encoding="utf-8")

# ── 会话级文件句柄 ──
current_session: dict | None = None  # {id, csv_path, csv_file, csv_writer, start_time, count}


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
                "screen_width": None,
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
    print("  EyeUX — WebCam 眼动追踪 + 数据存储")
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
        if current_session:
            current_session["csv_file"].close()
        print("\nBye")


if __name__ == "__main__":
    main()
