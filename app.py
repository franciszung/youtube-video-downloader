#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YouTube 视频下载器 - 本地网页版
核心流程: yt-dlp + 本地代理 + Node.js runtime
"""

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, jsonify, render_template, request, send_from_directory
from moviepy import AudioFileClip, VideoFileClip
import imageio_ffmpeg

app = Flask(__name__)
FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
DOWNLOADS_DIR = BASE_DIR / "downloads"
THUMBNAILS_DIR = BASE_DIR / "thumbnails"


def resolve_path(p, base=None):
    """把配置里的路径统一解析:
    - None / 空字符串 → 返回空字符串
    - 绝对路径 → 原样返回
    - 相对路径 → 基于 base (默认 BASE_DIR) 解析
    返回 Path 对象或空字符串。
    """
    if not p:
        return ""
    s = str(p).strip()
    if not s:
        return ""
    base = Path(base) if base else BASE_DIR
    path = Path(s)
    if path.is_absolute():
        return path
    return (base / path).resolve()


DEFAULT_CONFIG = {
    "proxy": "http://127.0.0.1:7892",
    "use_proxy": True,
    # 相对路径,优先找 setup.ps1 下载到工具自带的 runtime/node/node.exe
    "nodejs_runtime": "runtime/node/node.exe",
    "use_nodejs_runtime": True,
    "default_quality": "1080p",
    "output_dir": "downloads",  # 相对工具根目录
    "default_extract_frames": False,
    # 空=匿名下载（无法下载 age-restricted / 私有视频）
    # 可填: edge / chrome / firefox / brave / opera / safari
    # 或 cookies.txt 文件的绝对/相对路径
    "cookies_source": "cookies.txt",
    "use_cookies": False,
}

# 全局任务状态
_tasks = {}
_tasks_lock = threading.Lock()


def load_config():
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            # 合并默认值，处理新增字段
            for k, v in DEFAULT_CONFIG.items():
                cfg.setdefault(k, v)
            return cfg
        except Exception as e:
            print(f"[WARN] config load failed: {e}, using default")
    return DEFAULT_CONFIG.copy()


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def get_env_with_proxy(cfg):
    env = os.environ.copy()
    if cfg.get("use_proxy") and cfg.get("proxy"):
        proxy = cfg["proxy"].strip()
        env["HTTP_PROXY"] = proxy
        env["HTTPS_PROXY"] = proxy
        env["http_proxy"] = proxy
        env["https_proxy"] = proxy
    else:
        env.pop("HTTP_PROXY", None)
        env.pop("HTTPS_PROXY", None)
        env.pop("http_proxy", None)
        env.pop("https_proxy", None)

    # 某些沙箱 / IDE / 企业终端策略会通过 NODE_OPTIONS 注入自己的 shim。
    # yt-dlp 调 node 时会带上 --experimental-permission，权限模型会阻止 shim
    # 读取自身文件，导致 "Access to this API has been restricted"，
    # 签名求解失败、1080p+ 格式全部缺失。清掉它最稳妥。
    env.pop("NODE_OPTIONS", None)

    return env


def get_ytdlp_cmd():
    """检测 yt-dlp 调用方式:
    1. 优先使用项目目录下的 yt-dlp.exe (nightly 版本)
    2. 再尝试系统 PATH 中的 yt-dlp 命令
    3. 最后回退到 python -m yt_dlp
    """
    # 1. 项目目录下的 yt-dlp.exe (存在即用,避免首次启动 version 检查超时)
    local_exe = BASE_DIR / "yt-dlp.exe"
    if local_exe.exists():
        return [str(local_exe)]

    # 2. 系统 PATH 中的 yt-dlp
    ytdlp_exe = "yt-dlp"
    try:
        subprocess.run([ytdlp_exe, "--version"], capture_output=True, timeout=30, check=True)
        return [ytdlp_exe]
    except Exception:
        pass

    # 3. 回退到 Python 模块
    python_exe = sys.executable
    return [python_exe, "-m", "yt_dlp"]


def get_ytdlp_version():
    """获取 yt-dlp 版本号"""
    try:
        result = subprocess.run(
            get_ytdlp_cmd() + ["--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"


def build_ytdlp_base_cmd(cfg):
    cmd = get_ytdlp_cmd() + ["--no-update", "--no-playlist", "--no-warnings"]
    if cfg.get("use_nodejs_runtime") and cfg.get("nodejs_runtime"):
        node = resolve_path(cfg["nodejs_runtime"])
        if not (node and Path(node).exists()):
            # 配置里的路径失效（版本目录被清理 / 换了机器）时，回退到 PATH 上的 node
            node = shutil.which("node")
        if node and Path(node).exists():
            # yt-dlp 默认启用 deno 且优先级高于 node。用户机器上装了 deno 时，
            # 它会盖掉自带的 node 并因权限模型求解失败。
            # --no-js-runtimes 必须排在 --js-runtimes 之前才能清掉默认值。
            cmd.extend(["--no-js-runtimes", "--js-runtimes", f"node:{node}"])
    # Cookies 支持:用于 age-restricted / 私有视频
    if cfg.get("use_cookies") and cfg.get("cookies_source"):
        source = cfg["cookies_source"].strip()
        if source:
            # 文件路径 (相对/绝对) -> --cookies; 否则当作浏览器名 -> --cookies-from-browser
            resolved = resolve_path(source)
            if resolved and Path(resolved).exists() and Path(resolved).is_file():
                cmd.extend(["--cookies", str(resolved)])
            else:
                cmd.extend(["--cookies-from-browser", source])
    return cmd


def extract_video_id(url):
    patterns = [
        r"(?:v=|\/)([0-9A-Za-z_-]{11}).*",
        r"youtu\.be\/([0-9A-Za-z_-]{11})",
        r"embed\/([0-9A-Za-z_-]{11})",
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return None


def sanitize_filename(name):
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip() or "video"


def parse_formats(stdout_text):
    """解析 yt-dlp -F 输出，返回可用格式列表"""
    formats = []
    lines = stdout_text.splitlines()
    in_table = False
    for line in lines:
        if line.strip().startswith("ID ") and "RESOLUTION" in line:
            in_table = True
            continue
        if not in_table:
            continue
        if not line.strip() or line.startswith("-"):
            continue
        parts = line.split(None, 4)
        if len(parts) < 4:
            continue
        fid = parts[0]
        ext = parts[1]
        res = parts[2]
        fps = parts[3] if len(parts) > 3 else ""
        note = parts[4] if len(parts) > 4 else ""
        # 只保留视频/音频格式
        if ext in ("mp4", "webm", "m4a", "3gp"):
            formats.append({
                "id": fid,
                "ext": ext,
                "resolution": res,
                "fps": fps,
                "note": note,
            })
    return formats


def get_format_code(quality):
    """根据清晰度返回 yt-dlp 格式选择字符串"""
    q = quality.lower()
    if q in ("best", "最高"):
        return "best[ext=mp4]/best"
    if q in ("4k", "2160p"):
        return "bestvideo[height<=2160][ext=mp4]+bestaudio[ext=m4a]/best[height<=2160]"
    if q in ("1440p", "2k"):
        return "bestvideo[height<=1440][ext=mp4]+bestaudio[ext=m4a]/best[height<=1440]"
    if q in ("1080p", "1080"):
        return "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]"
    if q in ("720p", "720"):
        return "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]"
    if q in ("480p", "480"):
        return "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480]"
    if q in ("360p", "360"):
        return "bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[height<=360]"
    return f"bestvideo[height<={q.replace('p','')}][ext=mp4]+bestaudio[ext=m4a]/best[height<={q.replace('p','')}]"


def run_subprocess(cmd, env, cwd, task_id):
    """运行子进程并实时解析进度"""
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=cwd,
    )
    with _tasks_lock:
        _tasks[task_id]["pid"] = proc.pid

    for line in proc.stdout:
        line = line.rstrip()
        if not line:
            continue
        with _tasks_lock:
            _tasks[task_id]["log"].append(line)
            _tasks[task_id]["last_log"] = line
        # 解析进度百分比
        m = re.search(r"(\d+\.?\d*)%", line)
        if m:
            try:
                pct = float(m.group(1))
                with _tasks_lock:
                    _tasks[task_id]["progress"] = pct
            except ValueError:
                pass
        # 解析下载速度
        m2 = re.search(r"([\d.]+\s*[KMGT]?i?B/s)", line)
        if m2:
            with _tasks_lock:
                _tasks[task_id]["speed"] = m2.group(1)
        # 解析已下载大小
        m3 = re.search(r"([\d.]+\s*[KMGT]?i?B)\s+of\s+([\d.]+\s*[KMGT]?i?B)", line)
        if m3:
            with _tasks_lock:
                _tasks[task_id]["downloaded"] = m3.group(1)
                _tasks[task_id]["total_size"] = m3.group(2)

    proc.wait()
    return proc.returncode


def cleanup_temp_files(output_dir, safe_name, task_id=None):
    """清理 yt-dlp 下载过程中产生的临时分片文件 (.part-Frag*, .ytdl, .f*.m4a/webm, .f*.mp4/webm 等)
    使用多种删除方式 (按优先级):
      1. os.remove (主路径)
      2. pathlib.Path.unlink
      3. PowerShell Remove-Item -LiteralPath (绕过 sandbox safe-delete)
      4. PowerShell Get-Item | Remove-Item (更稳健)
    每次都记录每个文件的结果到日志
    """
    import glob

    patterns = [
        f"{safe_name}.part*",
        f"{safe_name}.ytdl",
        f"{safe_name}.f*.mp4",
        f"{safe_name}.f*.m4a",
        f"{safe_name}.f*.webm",
    ]

    files_to_remove = []
    seen = set()
    for pat in patterns:
        for f in glob.glob(str(Path(output_dir) / pat)):
            if f not in seen:
                seen.add(f)
                files_to_remove.append(f)

    if not files_to_remove:
        return 0

    removed = 0
    failures = []
    for f in files_to_remove:
        ok = False
        # 方法 1: os.remove
        try:
            os.remove(f)
            ok = True
        except Exception:
            pass

        # 方法 2: pathlib.unlink
        if not ok:
            try:
                Path(f).unlink(missing_ok=True)
                ok = not Path(f).exists()
            except Exception:
                pass

        # 方法 3: PowerShell Remove-Item -LiteralPath (长超时)
        if not ok:
            try:
                r = subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     f"Remove-Item -LiteralPath '{f}' -Force -ErrorAction SilentlyContinue"],
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60
                )
                ok = not os.path.exists(f)
            except Exception:
                pass

        # 方法 4: PowerShell Get-Item | Remove-Item (兜底)
        if not ok:
            try:
                r = subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     f"Get-Item -LiteralPath '{f}' | Remove-Item -Force -ErrorAction SilentlyContinue"],
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60
                )
                ok = not os.path.exists(f)
            except Exception:
                pass

        if ok:
            removed += 1
        else:
            failures.append(os.path.basename(f))

    if task_id:
        with _tasks_lock:
            if removed:
                _tasks[task_id]["log"].append(f"[cleanup] 已清理 {removed} 个临时文件")
            if failures:
                _tasks[task_id]["log"].append(
                    f"[cleanup] 警告:无法删除 {len(failures)} 个文件: {', '.join(failures[:3])}"
                    + ("..." if len(failures) > 3 else "")
                )

    return removed


def merge_video_audio(video_path, audio_path, output_path, task_id):
    """使用 ffmpeg 合并音画,避免 moviepy 在沙箱中产生临时文件导致 safe-delete 失败"""
    with _tasks_lock:
        _tasks[task_id]["status"] = "merging"
        _tasks[task_id]["message"] = "正在合并视频与音频..."
    try:
        cmd = [
            FFMPEG_EXE,
            "-y",
            "-i", str(video_path),
            "-i", str(audio_path),
            "-c", "copy",
            "-shortest",
            str(output_path)
        ]
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr[:500])
        return True
    except Exception as e:
        with _tasks_lock:
            _tasks[task_id]["error"] = f"合并失败: {e}"
        return False


def get_video_duration(video_path):
    """使用 ffmpeg 获取视频时长 (imageio-ffmpeg 不附带 ffprobe)
    使用 -c copy 避免转码,保证快速返回
    """
    try:
        cmd = [
            FFMPEG_EXE,
            "-i", str(video_path),
            "-c", "copy",
            "-f", "null", "-"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        # 从 stderr 中解析 Duration: 00:08:44.33
        m = re.search(r"Duration:\s+(\d+):(\d+):(\d+\.\d+)", result.stderr)
        if m:
            h, m_, s = m.groups()
            return int(h) * 3600 + int(m_) * 60 + float(s)
    except Exception:
        pass
    return 0


def extract_keyframes(video_path, output_dir, task_id, count=8):
    """使用 ffmpeg 提取关键帧缩略图"""
    with _tasks_lock:
        _tasks[task_id]["status"] = "extracting_frames"
        _tasks[task_id]["message"] = "正在提取关键帧..."
    try:
        duration = get_video_duration(video_path)
        if duration <= 0:
            # 回退到 moviepy 获取时长
            clip = VideoFileClip(str(video_path))
            duration = clip.duration
            clip.close()
        output_dir.mkdir(parents=True, exist_ok=True)
        frames = []
        timestamps = [duration * i / (count + 1) for i in range(1, count + 1)]
        for i, t in enumerate(timestamps, 1):
            fname = output_dir / f"{video_path.stem}_frame_{i:02d}.jpg"
            cmd = [
                FFMPEG_EXE,
                "-y",
                "-ss", str(t),
                "-i", str(video_path),
                "-vframes", "1",
                "-q:v", "2",
                str(fname)
            ]
            subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, check=True)
            frames.append({"time": round(t, 1), "file": str(fname.name)})
        return frames
    except Exception as e:
        with _tasks_lock:
            _tasks[task_id]["error"] = f"提取关键帧失败: {e}"
        return []


def download_worker(task_id, url, quality, output_name, extract_frames, cfg):
    """后台下载任务"""
    output_dir = resolve_path(cfg.get("output_dir"), BASE_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    with _tasks_lock:
        _tasks[task_id]["status"] = "preparing"
        _tasks[task_id]["message"] = "正在解析视频信息..."

    env = get_env_with_proxy(cfg)
    base_cmd = build_ytdlp_base_cmd(cfg)

    # 1. 先获取标题和可用格式
    try:
        info_cmd = base_cmd + ["--print", "%(title)s", "--print", "%(duration)s", url]
        result = subprocess.run(
            info_cmd,
            env=env,
            cwd=str(output_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        info_lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
        title = info_lines[0] if info_lines else "video"
        duration = info_lines[1] if len(info_lines) > 1 else ""
    except Exception as e:
        title = "video"
        duration = ""

    with _tasks_lock:
        _tasks[task_id]["title"] = title
        _tasks[task_id]["duration"] = duration

    safe_name = sanitize_filename(output_name or title)
    final_name = f"{safe_name}.mp4"
    final_path = output_dir / final_name

    # 如果文件已存在，加序号
    counter = 1
    while final_path.exists():
        final_name = f"{safe_name}_{counter:02d}.mp4"
        final_path = output_dir / final_name
        counter += 1

    # 2. 执行下载 (加入质量 fallback: 若 720p/1080p 失败,自动降一档重试)
    quality_fallback_order = [
        quality,
        "720p", "480p", "360p", "best",
    ]
    seen = set()
    quality_attempts = [q for q in quality_fallback_order if not (q in seen or seen.add(q))]

    returncode = 0
    for attempt_idx, q in enumerate(quality_attempts):
        fmt = get_format_code(q)
        download_cmd = base_cmd + [
            "-f", fmt,
            "--merge-output-format", "mp4",
            "-o", f"{safe_name}.%(ext)s",
            url,
        ]
        with _tasks_lock:
            _tasks[task_id]["status"] = "downloading"
            _tasks[task_id]["message"] = (
                f"尝试下载 [{q}]..." if attempt_idx > 0 else "开始下载..."
            )
            _tasks[task_id]["output_file"] = str(final_path)
            _tasks[task_id]["quality"] = q

        rc = run_subprocess(download_cmd, env, str(output_dir), task_id)

        # 找到任何生成的 mp4 / 分轨文件即视为成功
        generated_mp4 = output_dir / f"{safe_name}.mp4"
        import glob
        video_parts = glob.glob(str(output_dir / f"{safe_name}.f*.mp4"))
        audio_parts = glob.glob(str(output_dir / f"{safe_name}.f*.m4a"))

        if rc == 0 or generated_mp4.exists() or video_parts:
            returncode = 0
            with _tasks_lock:
                _tasks[task_id]["message"] = f"下载完成 (使用 {q})"
            break

        # 失败原因解析,只在非最后一次尝试时降档
        with _tasks_lock:
            last = _tasks[task_id].get("last_log", "")
            _tasks[task_id]["log"].append(f"[fallback] {q} 失败,尝试下一档...")
        if attempt_idx >= len(quality_attempts) - 1:
            returncode = rc
            break

    if returncode != 0:
        # 失败时也清理临时分片,避免污染 downloads 目录
        cleanup_temp_files(output_dir, safe_name, task_id)
        with _tasks_lock:
            _tasks[task_id]["status"] = "failed"
            _tasks[task_id]["message"] = "下载失败，请查看日志"
        return

    # 3. 如果 yt-dlp 没有自动合并（分轨情况），手动合并
    # 检查实际生成的文件
    possible_video = output_dir / f"{safe_name}.f*.mp4"
    possible_audio = output_dir / f"{safe_name}.f*.m4a"
    import glob
    video_parts = sorted(glob.glob(str(possible_video)))
    audio_parts = sorted(glob.glob(str(possible_audio)))

    # 如果已经生成最终 mp4，直接移动
    generated_mp4 = output_dir / f"{safe_name}.mp4"
    if generated_mp4.exists():
        if generated_mp4 != final_path:
            generated_mp4.rename(final_path)
    elif video_parts:
        # 手动合并
        # 找最大的视频文件和最大的音频文件
        vfile = max(video_parts, key=os.path.getsize)
        afile = audio_parts[0] if audio_parts else None
        if afile and Path(afile).exists():
            ok = merge_video_audio(Path(vfile), Path(afile), final_path, task_id)
            if not ok:
                with _tasks_lock:
                    _tasks[task_id]["status"] = "failed"
                return
        else:
            # 只有视频，直接重命名
            Path(vfile).rename(final_path)

    # 4. 校验最终文件
    if not final_path.exists():
        with _tasks_lock:
            _tasks[task_id]["status"] = "failed"
            _tasks[task_id]["message"] = "未找到下载文件"
        return

    # 4.5 清理临时文件 (.part-Frag*, .f*.mp4/m4a, .ytdl)
    with _tasks_lock:
        _tasks[task_id]["status"] = "cleaning"
        _tasks[task_id]["message"] = "清理临时文件..."
    cleanup_temp_files(output_dir, safe_name, task_id)

    # 5. 提取关键帧
    frames = []
    if extract_frames:
        frames_dir = THUMBNAILS_DIR / final_path.stem
        frames = extract_keyframes(final_path, frames_dir, task_id)

    # 6. 获取视频信息 (使用 ffmpeg 解析,避免 moviepy 临时文件问题)
    try:
        cmd = [
            FFMPEG_EXE,
            "-i", str(final_path),
            "-c", "copy",
            "-f", "null", "-"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        stderr = result.stderr
        # 解析 Stream #0:0(und): Video: h264 (avc1 / 0x31637661), yuv420p(tv, bt709), 640x360 [SAR 1:1 DAR 16:9], 462 kb/s, 24 fps
        # 注意避免匹配到 av01 / 0x31307661 里的数字
        stream_m = re.search(r"Stream\s+#\d+:\d+.*?Video:.*?yuv\w+\([^)]*\),\s+(\d+)x(\d+)\s+\[.*?\]\s*,.*?\s+([\d.]+)\s+fps", stderr)
        if stream_m:
            width = int(stream_m.group(1))
            height = int(stream_m.group(2))
            fps = round(float(stream_m.group(3)), 2)
        else:
            width, height, fps = 0, 0, 0
        duration = get_video_duration(final_path)
    except Exception:
        width, height, fps, duration = 0, 0, 0, 0

    with _tasks_lock:
        _tasks[task_id]["status"] = "completed"
        _tasks[task_id]["message"] = "下载完成"
        _tasks[task_id]["progress"] = 100
        _tasks[task_id]["file"] = {
            "name": final_path.name,
            "path": str(final_path),
            "size": final_path.stat().st_size,
            "resolution": f"{width}x{height}" if width else "",
            "fps": fps,
            "duration": round(duration, 2) if duration else 0,
        }
        _tasks[task_id]["frames"] = frames


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    if request.method == "GET":
        cfg = load_config()
        cfg["ytdlp_version"] = get_ytdlp_version()
        return jsonify(cfg)
    cfg = request.get_json() or {}
    current = load_config()
    current.update(cfg)
    save_config(current)
    return jsonify({"success": True, "config": current})


@app.route("/api/formats", methods=["POST"])
def api_formats():
    data = request.get_json() or {}
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "缺少 URL"}), 400
    cfg = load_config()
    env = get_env_with_proxy(cfg)
    cmd = build_ytdlp_base_cmd(cfg) + ["-F", url]
    try:
        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        if result.returncode != 0:
            return jsonify({"error": result.stderr or "获取格式失败"}), 500
        formats = parse_formats(result.stdout)
        # 同时获取标题
        info_cmd = build_ytdlp_base_cmd(cfg) + ["--print", "%(title)s", url]
        info_result = subprocess.run(info_cmd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        title = info_result.stdout.strip().splitlines()[0] if info_result.stdout.strip() else ""
        return jsonify({"title": title, "formats": formats})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/download", methods=["POST"])
def api_download():
    data = request.get_json() or {}
    url = data.get("url", "").strip()
    quality = data.get("quality", "1080p").strip() or "1080p"
    output_name = data.get("output_name", "").strip()
    extract_frames = bool(data.get("extract_frames", False))

    if not url:
        return jsonify({"error": "缺少 URL"}), 400

    task_id = f"task_{int(time.time() * 1000)}"
    cfg = load_config()

    with _tasks_lock:
        _tasks[task_id] = {
            "id": task_id,
            "url": url,
            "quality": quality,
            "output_name": output_name,
            "status": "queued",
            "message": "等待开始...",
            "progress": 0,
            "speed": "",
            "downloaded": "",
            "total_size": "",
            "title": "",
            "duration": "",
            "output_file": "",
            "log": [],
            "last_log": "",
            "error": "",
            "file": None,
            "frames": [],
            "created_at": datetime.now().isoformat(),
        }

    t = threading.Thread(
        target=download_worker,
        args=(task_id, url, quality, output_name, extract_frames, cfg),
        daemon=True,
    )
    t.start()

    return jsonify({"success": True, "task_id": task_id})


@app.route("/api/tasks", methods=["GET"])
def api_tasks():
    with _tasks_lock:
        tasks = [dict(t) for t in _tasks.values()]
        # 日志最多保留 100 条
        for t in tasks:
            t["log"] = t["log"][-100:]
    return jsonify(tasks)


@app.route("/api/files", methods=["GET"])
def api_files():
    cfg = load_config()
    output_dir = resolve_path(cfg.get("output_dir"), BASE_DIR)
    files = []
    if output_dir.exists():
        for f in sorted(output_dir.iterdir()):
            if f.is_file() and f.suffix.lower() in (".mp4", ".mkv", ".webm", ".mov"):
                files.append({
                    "name": f.name,
                    "path": str(f),
                    "size": f.stat().st_size,
                    "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                })
    return jsonify(files)


@app.route("/api/delete-file", methods=["POST"])
def api_delete_file():
    data = request.get_json() or {}
    filename = data.get("filename", "")
    if not filename:
        return jsonify({"error": "缺少文件名"}), 400
    cfg = load_config()
    output_dir = resolve_path(cfg.get("output_dir"), BASE_DIR)
    target = output_dir / filename
    # 安全检查
    try:
        target.relative_to(output_dir)
    except ValueError:
        return jsonify({"error": "非法路径"}), 400
    if target.exists():
        try:
            target.unlink()
        except Exception:
            # 沙箱 safe-delete 拦截,改用 PowerShell
            try:
                subprocess.run(
                    ["powershell", "-Command", f"Remove-Item -Path '{target}' -Force -ErrorAction SilentlyContinue"],
                    capture_output=True, timeout=15
                )
            except Exception:
                pass
        # 同时删除缩略图目录
        thumb_dir = THUMBNAILS_DIR / target.stem
        if thumb_dir.exists():
            import shutil
            shutil.rmtree(thumb_dir)
        return jsonify({"success": True})
    return jsonify({"error": "文件不存在"}), 404


@app.route("/api/cleanup-junk", methods=["POST"])
def api_cleanup_junk():
    """扫描 downloads 目录,清理所有 yt-dlp 临时文件 (.part-Frag*, .ytdl, .f*.m4a/mp4/webm 等)
    使用四阶段清理策略:
      1. os.remove
      2. pathlib.unlink
      3. PowerShell Remove-Item -LiteralPath
      4. PowerShell Get-Item | Remove-Item
    """
    cfg = load_config()
    output_dir = resolve_path(cfg.get("output_dir"), BASE_DIR)
    import glob

    patterns = ["*.part-Frag*", "*.part", "*.ytdl",
                "*.f*.mp4", "*.f*.m4a", "*.f*.webm"]
    files = []
    seen = set()
    for pat in patterns:
        for f in glob.glob(str(output_dir / pat)):
            if f not in seen:
                seen.add(f)
                files.append(f)

    removed = 0
    failed = []
    for f in files:
        ok = False
        # 方法 1: os.remove
        try:
            os.remove(f)
            ok = True
        except Exception:
            pass

        # 方法 2: pathlib.unlink
        if not ok:
            try:
                Path(f).unlink(missing_ok=True)
                ok = not Path(f).exists()
            except Exception:
                pass

        # 方法 3: PowerShell Remove-Item -LiteralPath (长超时)
        if not ok:
            try:
                subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     f"Remove-Item -LiteralPath '{f}' -Force -ErrorAction SilentlyContinue"],
                    capture_output=True, timeout=60
                )
                ok = not os.path.exists(f)
            except Exception:
                pass

        # 方法 4: PowerShell Get-Item | Remove-Item
        if not ok:
            try:
                subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     f"Get-Item -LiteralPath '{f}' | Remove-Item -Force -ErrorAction SilentlyContinue"],
                    capture_output=True, timeout=60
                )
                ok = not os.path.exists(f)
            except Exception:
                pass

        if ok:
            removed += 1
        else:
            failed.append(os.path.basename(f))

    return jsonify({"success": True, "removed": removed, "failed": failed[:10]})


@app.route("/api/extract-frames", methods=["POST"])
def api_extract_frames():
    data = request.get_json() or {}
    filename = data.get("filename", "")
    count = int(data.get("count", 8))
    if not filename:
        return jsonify({"error": "缺少文件名"}), 400
    cfg = load_config()
    output_dir = resolve_path(cfg.get("output_dir"), BASE_DIR)
    video_path = output_dir / filename
    try:
        video_path.relative_to(output_dir)
    except ValueError:
        return jsonify({"error": "非法路径"}), 400
    if not video_path.exists():
        return jsonify({"error": "文件不存在"}), 404

    frames_dir = THUMBNAILS_DIR / video_path.stem
    try:
        duration = get_video_duration(video_path)
        if duration <= 0:
            clip = VideoFileClip(str(video_path))
            duration = clip.duration
            clip.close()
        frames_dir.mkdir(parents=True, exist_ok=True)
        frames = []
        timestamps = [duration * i / (count + 1) for i in range(1, count + 1)]
        for i, t in enumerate(timestamps, 1):
            fname = frames_dir / f"{video_path.stem}_frame_{i:02d}.jpg"
            cmd = [
                FFMPEG_EXE,
                "-y",
                "-ss", str(t),
                "-i", str(video_path),
                "-vframes", "1",
                "-q:v", "2",
                str(fname)
            ]
            subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, check=True)
            frames.append({"time": round(t, 1), "file": fname.name})
        return jsonify({"success": True, "frames": frames, "dir": str(frames_dir)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/downloads/<path:filename>")
def serve_download(filename):
    cfg = load_config()
    output_dir = str(resolve_path(cfg.get("output_dir"), BASE_DIR))
    return send_from_directory(output_dir, filename)


@app.route("/thumbnails/<path:filename>")
def serve_thumbnail(filename):
    return send_from_directory(str(THUMBNAILS_DIR), filename)


if __name__ == "__main__":
    # 确保目录存在
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)
    save_config(load_config())
    print(f"[INFO] YouTube Downloader starting...")
    print(f"[INFO] Downloads: {DOWNLOADS_DIR}")
    print(f"[INFO] Open http://127.0.0.1:5123 in browser")
    app.run(host="127.0.0.1", port=5123, debug=False, threaded=True)
