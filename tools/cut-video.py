#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cut-video.py —— 把一段长视频等长切成 chunks/000.mp4 序列，并打印可直接粘进
                 index.html CONFIG 的 BOUNDS 数组。

用两个 ffmpeg 子进程（ffmpeg / ffprobe），不依赖任何 Python 第三方库，
在 Windows / macOS / Linux 上都能跑（不写死任何路径）。

──────────────────────────────────────────────────────────────────────────────
用法示例（先装好 ffmpeg 并确保 ffmpeg、ffprobe 在 PATH 里）：

    # 按“块数”切：把整段视频均分成 96 块
    python tools/cut-video.py D:/footage/daynight.mp4 --chunks 96

    # 按“每块时长”切：每块 120 秒，最后一块不足 120 秒则更短
    python tools/cut-video.py D:/footage/daynight.mp4 --chunk-seconds 120

    # 指定输出目录（默认 ./chunks）
    python tools/cut-video.py daynight.mp4 --chunks 96 --out chunks

    # 无损快速切分（-c copy，秒级完成，但切点会对齐到关键帧，边界不精确）
    python tools/cut-video.py daynight.mp4 --chunks 96 --copy

    # 重编码参数（默认 libx264 / crf 18 / preset medium）
    python tools/cut-video.py daynight.mp4 --chunks 96 --crf 20 --preset slow --fps 30 --height 1080

参数说明：
    --chunks N          切成 N 块（与 --chunk-seconds 二选一）
    --chunk-seconds S   每块 S 秒（与 --chunks 二选一）
    --out DIR           输出目录，默认 ./chunks
    --copy              用 -c copy 无损快速切分（边界对齐关键帧，不精确）
    --crf / --preset    重编码画质与速度（仅重编码模式有效）
    --fps / --height    可选：统一帧率 / 缩放到指定高度（仅重编码模式有效）
    --dry-run           只打印计划与 BOUNDS，不真正调用 ffmpeg

输出：
    chunks/000.mp4, chunks/001.mp4, …     切好的片段
    chunks/chunks.csv                     文件名, 起始秒, 结束秒
    终端里打印 CHUNK_SECONDS / NCHUNK / LOOP / BOUNDS，直接复制到 index.html 的 CONFIG。
──────────────────────────────────────────────────────────────────────────────
"""

import argparse
import csv
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"


def die(msg):
    print("[错误] " + msg, file=sys.stderr)
    sys.exit(1)


def check_tools():
    """确认 ffmpeg / ffprobe 可用。"""
    for name, exe in (("ffmpeg", FFMPEG), ("ffprobe", FFPROBE)):
        if shutil.which(exe) is None:
            die("找不到 %s，请先安装 ffmpeg 并把它加入 PATH（https://ffmpeg.org/）。" % name)


def probe_duration(path):
    """用 ffprobe 读取视频时长（秒）。"""
    cmd = [FFPROBE, "-v", "error",
           "-show_entries", "format=duration",
           "-of", "default=noprint_wrappers=1:nokey=1",
           str(path)]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        die("ffprobe 读取时长失败：%s" % e.output.decode(errors="replace").strip())
    txt = out.decode(errors="replace").strip()
    try:
        return float(txt)
    except ValueError:
        die("无法解析视频时长（ffprobe 返回：%r）" % txt)


def make_bounds(duration, chunks, chunk_seconds):
    """生成 N+1 个块边界（秒）。"""
    if chunks:
        n = int(chunks)
        if n < 1:
            die("--chunks 必须 >= 1")
        step = duration / n
        bounds = [round(i * step, 6) for i in range(n)]
        bounds.append(duration)
        return bounds, step
    else:
        s = float(chunk_seconds)
        if s <= 0:
            die("--chunk-seconds 必须 > 0")
        n = max(1, int(math.ceil(duration / s - 1e-9)))
        bounds = [round(min(i * s, duration), 6) for i in range(n)]
        bounds.append(duration)
        return bounds, s


def fmt_js(x):
    """把秒数格式化成 JS 数组里好看且紧凑的写法（最多两位小数）。"""
    return ("%g" % round(x, 2))


def run_ffmpeg(args):
    """执行 ffmpeg，失败时把 stderr 末尾打出来。"""
    proc = subprocess.run([FFMPEG] + args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if proc.returncode != 0:
        tail = proc.stdout.decode(errors="replace").strip().splitlines()[-15:]
        die("ffmpeg 执行失败（退出码 %d）：\n%s" % (proc.returncode, "\n".join(tail)))


def main():
    ap = argparse.ArgumentParser(
        description="把长视频等长切成 chunks/000.mp4 序列，并打印 BOUNDS 供 CONFIG 使用。",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="输入视频文件路径")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--chunks", type=int, help="切成 N 块")
    g.add_argument("--chunk-seconds", type=float, help="每块 S 秒")
    ap.add_argument("--out", default="chunks", help="输出目录（默认 ./chunks）")
    ap.add_argument("--copy", action="store_true", help="用 -c copy 无损快速切分（边界不精确）")
    ap.add_argument("--crf", type=int, default=18, help="重编码质量，越小越好（默认 18）")
    ap.add_argument("--preset", default="medium", help="x264 preset（默认 medium）")
    ap.add_argument("--fps", type=int, default=0, help="可选：统一帧率（重编码模式）")
    ap.add_argument("--height", type=int, default=0, help="可选：缩放到指定高度（重编码模式，宽度自动）")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划与 BOUNDS，不调用 ffmpeg")
    args = ap.parse_args()

    src = Path(args.input).expanduser()
    if not src.is_file():
        die("输入文件不存在：%s" % src)

    if not args.dry_run:
        check_tools()

    duration = probe_duration(src)
    if duration <= 0:
        die("读到的视频时长为 0，无法切分。")

    bounds = None
    step = None
    if args.chunks:
        bounds, step = make_bounds(duration, args.chunks, None)
    else:
        bounds, step = make_bounds(duration, None, args.chunk_seconds)
    n = len(bounds) - 1

    out_dir = Path(args.out).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 78)
    print("输入文件 : %s" % src)
    print("总时长   : %.3f 秒（≈ %s）" % (duration, hhmmss(duration)))
    print("切分方式 : %s" % ("均分成 %d 块" % n if args.chunks else "每块 %.3f 秒 → %d 块" % (args.chunk_seconds, n)))
    print("输出目录 : %s" % out_dir.resolve())
    print("编码方式 : %s" % ("-c copy（无损快速，边界对齐关键帧）" if args.copy else
                             "libx264 crf=%d preset=%s" % (args.crf, args.preset)))
    print("=" * 78)

    rows = []
    for k in range(n):
        start = bounds[k]
        dur = bounds[k + 1] - bounds[k]
        name = "%03d.mp4" % k
        dst = out_dir / name
        rows.append((name, start, bounds[k + 1]))
        print("[%3d/%3d] %s  %s → %s  （%.2f 秒）" %
              (k + 1, n, name, hhmmss(start), hhmmss(bounds[k + 1]), dur))
        if args.dry_run:
            continue
        if args.copy:
            cmd = ["-y", "-ss", "%.3f" % start, "-i", str(src), "-t", "%.3f" % dur,
                   "-c", "copy", "-an", "-avoid_negative_ts", "make_zero", str(dst)]
        else:
            cmd = ["-y", "-ss", "%.3f" % start, "-i", str(src), "-t", "%.3f" % dur,
                   "-c:v", "libx264", "-crf", str(args.crf), "-preset", args.preset,
                   "-pix_fmt", "yuv420p", "-an", "-movflags", "+faststart"]
            if args.fps:
                cmd += ["-r", str(args.fps)]
            if args.height:
                cmd += ["-vf", "scale=-2:%d" % args.height]
            cmd += [str(dst)]
        run_ffmpeg(cmd)

    # 写 chunks.csv（文件名, 起始秒, 结束秒）——与原工程格式一致
    if not args.dry_run:
        csv_path = out_dir / "chunks.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            for name, start, end in rows:
                w.writerow([name, "%.6f" % start, "%.6f" % end])
        print("\n已写出 %s" % csv_path.resolve())

    # 打印可直接粘进 index.html CONFIG 的片段
    bounds_js = ",".join(fmt_js(b) for b in bounds)
    print("\n" + "=" * 78)
    print("把下面这几行粘进 index.html 顶部的 CONFIG 里（替换同名常量）：")
    print("=" * 78)
    print("const CHUNK_SECONDS = %s;" % fmt_js(step))
    print("const NCHUNK        = %d;" % n)
    print("const LOOP          = %s;" % fmt_js(duration))
    print("const BOUNDS  = [%s];" % bounds_js)
    print("=" * 78)
    print("★ 下一步：用 tools/measure-calibration.py 找出 V_SET / V_MID / V_RISE，")
    print("  并标定 V_LAT / V_DECL / DUSK_LEN / DAWN_LEN（详见 README.md）。")


def hhmmss(seconds):
    seconds = max(0, int(round(seconds)))
    return "%d:%02d:%02d" % (seconds // 3600, (seconds // 60) % 60, seconds % 60)


if __name__ == "__main__":
    main()
