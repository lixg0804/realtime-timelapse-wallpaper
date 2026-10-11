#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
measure-calibration.py —— 【辅助】用画面亮度曲线，帮你找出素材里的
                          日出 / 日落 / 正午 / 午夜 四个时刻，供填入 index.html 的 CONFIG。

原理（很朴素，别指望它 100% 准）：
    把视频按固定间隔抽帧、缩成小图、转灰度，算每帧的平均亮度，
    得到一条「亮度 vs 素材时间」的曲线，然后：
        · 曲线最低点 ≈ 午夜（最暗）        → 填 CONFIG 的 V_MID
        · 曲线最高点 ≈ 正午（最亮）
        · 上升最陡处 ≈ 日出                → 填 CONFIG 的 V_RISE
        · 下降最陡处 ≈ 日落                → 填 CONFIG 的 V_SET
        · 最暗的一整段（接近纯黑）的起止 ≈ 全黑段，用来估算 DUSK_LEN / DAWN_LEN
    再按「白昼占整个昼夜循环的比例」推素材世界的昼长，从而反推 V_LAT 或 V_DECL。

★★★ 重要提醒（务必照做）★★★
    亮度曲线只是【辅助定位】，遇到云、月亮、城市灯光、镜头渐变、白天有遮挡等
    情况会误判。脚本给出的每个时刻，都要回到视频里肉眼抽查确认后再填进 CONFIG。
    标定不准 → 画面与真实时间整体错位，而这是最难事后发现的问题。
──────────────────────────────────────────────────────────────────────────────
用法示例（需要 ffmpeg / ffprobe 在 PATH 里）：

    # 基本用法：每 5 秒抽 1 帧
    python tools/measure-calibration.py D:/footage/daynight.mp4

    # 抽稀一点（长视频更快）：每 10 秒 1 帧
    python tools/measure-calibration.py daynight.mp4 --step 10

    # 已知拍摄季度的太阳赤纬，反推素材纬度（例如夏日 δ=+18°）
    python tools/measure-calibration.py daynight.mp4 --decl 18

    # 已知拍摄纬度，反推当天太阳赤纬
    python tools/measure-calibration.py daynight.mp4 --lat 41.8
──────────────────────────────────────────────────────────────────────────────
"""

import argparse
import math
import shutil
import subprocess
import sys

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"

COLS = 78      # ASCII 图宽度（列）
ROWS = 12      # ASCII 图高度（行）
GAUGE = " .:-=+*#%@"   # 亮度从暗到亮的字符（最后一个不用，见下）


def die(msg):
    print("[错误] " + msg, file=sys.stderr)
    sys.exit(1)


def check_tools():
    for name, exe in (("ffmpeg", FFMPEG), ("ffprobe", FFPROBE)):
        if shutil.which(exe) is None:
            die("找不到 %s，请先安装 ffmpeg 并加入 PATH。" % name)


def probe_duration(path):
    cmd = [FFPROBE, "-v", "error", "-show_entries", "format=duration",
           "-of", "default=noprint_wrappers=1:nokey=1", str(path)]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        die("ffprobe 读取时长失败：%s" % e.output.decode(errors="replace").strip())
    try:
        return float(out.decode(errors="replace").strip())
    except ValueError:
        die("无法解析视频时长。")


def extract_brightness(path, step, w=32, h=18):
    """按 step 秒抽帧，返回 [(时间秒, 平均亮度0~255), ...]。"""
    vf = "fps=1/%.6f,scale=%d:%d,format=gray" % (step, w, h)
    cmd = [FFMPEG, "-v", "error", "-i", str(path), "-vf", vf,
           "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        die("ffmpeg 抽帧失败：%s" % proc.stderr.decode(errors="replace").strip()[-400:])
    data = proc.stdout
    frame = w * h
    if frame <= 0 or len(data) < frame:
        die("没有抽到任何帧，请检查视频是否可解码。")
    count = len(data) // frame
    curve = []
    for i in range(count):
        chunk = data[i * frame:(i + 1) * frame]
        curve.append((i * step, sum(chunk) / float(frame)))
    return curve


def moving_average(vals, win):
    """简单移动平均；win 会被规整成不超过序列长度的奇数。"""
    n = len(vals)
    if n == 0:
        return vals
    if win < 1:
        win = 1
    if win % 2 == 0:
        win += 1
    if win > n:
        win = n if n % 2 == 1 else n - 1
    if win <= 1:
        return list(vals)
    half = win // 2
    out = []
    for i in range(n):
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        seg = vals[lo:hi]
        out.append(sum(seg) / len(seg))
    return out


def circular_forward(a, b, loop):
    """从 a 沿正方向走到 b 的距离（归一化到 [0, loop)）。"""
    return ((b - a) % loop + loop) % loop


def dark_plateau(curve, times, thr_frac=0.05):
    """返回最暗点所在的那一整段（亮度 <= min + thr_frac*range）的起止时间（秒）。"""
    b = [v for _, v in curve]
    n = len(b)
    lo, hi = min(b), max(b)
    thr = lo + thr_frac * (hi - lo)
    mn = b.index(lo)
    left = mn
    cnt = 0
    while cnt < n and b[(left - 1) % n] <= thr:
        left -= 1
        cnt += 1
    right = mn
    cnt = 0
    while cnt < n and b[(right + 1) % n] <= thr:
        right += 1
        cnt += 1
    return times[left % n], times[right % n], mn, thr


def steepest(curve):
    """返回上升最陡、下降最陡对应的下标（用平滑后的曲线做中心差分）。"""
    vals = [v for _, v in curve]
    n = len(vals)
    if n < 3:
        return 0, 0
    der = []
    for i in range(n):
        a = vals[(i - 1) % n]
        c = vals[(i + 1) % n]
        der.append(c - a)
    rise_i = der.index(max(der))
    set_i = der.index(min(der))
    return rise_i, set_i


def ascii_chart(curve, marks):
    """打印一个粗糙的亮度曲线 ASCII 图。marks: {字符: 下标}"""
    vals = [v for _, v in curve]
    n = len(vals)
    if n < 2:
        print("（采样太少，无法画图）")
        return
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1.0
    # 把曲线重采样到 COLS 列
    cols = []
    for c in range(COLS):
        a = int(c * n / COLS)
        b = max(a + 1, int((c + 1) * n / COLS))
        seg = vals[a:b]
        cols.append(sum(seg) / len(seg))
    grid = [[" "] * COLS for _ in range(ROWS)]
    for c, v in enumerate(cols):
        r = int(round((v - lo) / rng * (ROWS - 1)))
        grid[ROWS - 1 - r][c] = "*"
    for row in grid:
        print("  |" + "".join(row))
    print("  +" + "-" * COLS)
    # 标记行
    mline = [" "] * COLS
    for ch, idx in marks.items():
        if idx is None or idx < 0 or idx >= n:
            continue
        c = min(COLS - 1, int(idx * COLS / n))
        mline[c] = ch
    print("   " + "".join(mline) + "   （R=日出 S=日落 N=正午 M=午夜）")


def hhmmss(seconds, loop=None):
    seconds = max(0.0, float(seconds))
    return "%d:%02d:%02d" % (int(seconds // 3600),
                             int((seconds // 60) % 60),
                             int(seconds % 60))


def solve_lat_or_decl(day_fraction, decl_deg, lat_deg):
    """由白昼占比反推 V_LAT 或 V_DECL。两个未知数一个方程，所以只能给一个求另一个。"""
    day_hours = day_fraction * 24.0
    hA_deg = day_hours * 15.0 / 2.0          # 日出时角半宽（度）
    if hA_deg <= 0 or hA_deg >= 180:
        return None, day_hours, hA_deg
    cos_hA = math.cos(math.radians(hA_deg))
    if decl_deg is not None:
        t = math.tan(math.radians(decl_deg))
        if abs(t) < 1e-9:
            return None, day_hours, hA_deg   # 春/秋分：昼长约 12h，与纬度无关，无法反推
        lat = math.degrees(math.atan(-cos_hA / t))
        return ("lat", lat), day_hours, hA_deg
    if lat_deg is not None:
        t = math.tan(math.radians(lat_deg))
        if abs(t) < 1e-9:
            return None, day_hours, hA_deg
        decl = math.degrees(math.atan(-cos_hA / t))
        return ("decl", decl), day_hours, hA_deg
    return None, day_hours, hA_deg


def main():
    ap = argparse.ArgumentParser(
        description="用亮度曲线辅助定位素材的日出/日落/正午/午夜，供 CONFIG 标定。",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="输入视频文件路径")
    ap.add_argument("--step", type=float, default=5.0, help="抽帧间隔，秒（默认 5）")
    ap.add_argument("--smooth", type=int, default=5, help="亮度曲线平滑窗口（默认 5，奇数）")
    ap.add_argument("--decl", type=float, default=None, help="已知素材拍摄日太阳赤纬（度），用于反推纬度")
    ap.add_argument("--lat", type=float, default=None, help="已知素材拍摄纬度（度），用于反推赤纬")
    args = ap.parse_args()

    check_tools()
    duration = probe_duration(args.input)
    if duration <= 0:
        die("读到的视频时长为 0。")

    print("正在抽帧分析（间隔 %.1f 秒）…" % args.step)
    raw = extract_brightness(args.input, args.step)
    if len(raw) < 5:
        die("抽到的帧太少，请把 --step 调小。")

    times = [t for t, _ in raw]
    smooth = moving_average([v for _, v in raw], args.smooth)
    curve = list(zip(times, smooth))

    # 极值点
    b = [v for _, v in curve]
    i_min = b.index(min(b))
    i_max = b.index(max(b))
    t_mid = times[i_min]
    t_noon = times[i_max]

    # 陡变点
    i_rise, i_set = steepest(curve)
    t_rise = times[i_rise]
    t_set = times[i_set]

    # 全黑段
    t_dark_start, t_dark_end, _, thr = dark_plateau(curve, times)

    # 暮色长度（沿正方向）
    dusk_len = circular_forward(t_set, t_dark_start, duration)
    dawn_len = circular_forward(t_dark_end, t_rise, duration)

    # 白昼占比 / 素材世界昼长
    day_secs = circular_forward(t_rise, t_set, duration)
    day_fraction = day_secs / duration

    print()
    print("=" * 78)
    print("亮度曲线（横轴=素材时间，纵轴=亮度）：")
    print("=" * 78)
    ascii_chart(curve, {"M": i_min, "N": i_max, "R": i_rise, "S": i_set})

    print()
    print("=" * 78)
    print("★ 建议填入 index.html CONFIG 的数值（单位：素材秒）")
    print("=" * 78)
    print("  V_MID  (午夜 · 最暗) = %-12s  ≈ %s" % ("%.2f" % t_mid, hhmmss(t_mid)))
    print("  V_RISE (日出 · 最陡升) = %-12s  ≈ %s" % ("%.2f" % t_rise, hhmmss(t_rise)))
    print("  V_SET  (日落 · 最陡降) = %-12s  ≈ %s" % ("%.2f" % t_set, hhmmss(t_set)))
    print("  （参考）最亮点/正午 = %-12s ≈ %s" % ("%.2f" % t_noon, hhmmss(t_noon)))
    print()
    print("  全黑段 ≈ [%s , %s]（阈值：最暗 + 5%% 亮度范围）" %
          ("%.1f" % t_dark_start, "%.1f" % t_dark_end))
    print("  DUSK_LEN (日落→全黑) 建议 = %.0f 秒" % dusk_len)
    print("  DAWN_LEN (全黑→日出) 建议 = %.0f 秒" % dawn_len)

    print()
    print("=" * 78)
    print("★ 素材世界昼长与 V_LAT / V_DECL 反推")
    print("=" * 78)
    print("  白昼素材秒数 = %.1f，占整个昼夜循环的 %.1f%%" % (day_secs, day_fraction * 100))
    print("  → 若素材是「一整天」的等速延时，则素材世界昼长 ≈ %.2f 小时（占 24h 的 %.1f%%）"
          % (day_fraction * 24, day_fraction * 100))
    print("  反推公式：cos(昼长/2 × 15°) = -tan(纬度) × tan(赤纬)")
    (kind_val, day_hours, hA) = solve_lat_or_decl(day_fraction, args.decl, args.lat)
    if kind_val is not None:
        kind, val = kind_val
        if kind == "lat":
            print("  已知赤纬 δ=%s° → 反推素材纬度 φ ≈ %.2f°（北纬为正）  ⇒ V_LAT≈%.2f" %
                  (args.decl, val, val))
        else:
            print("  已知纬度 φ=%s° → 反推太阳赤纬 δ ≈ %.2f°              ⇒ V_DECL≈%.2f" %
                  (args.lat, val, val))
    else:
        print("  提示：一个方程解不出两个未知数。请用 --decl 指定拍摄当日太阳赤纬（查天文历），")
        print("        或用 --lat 指定拍摄纬度，本脚本就会反推出另一个。")

    print()
    print("!" * 78)
    print("!! 以上全部是【亮度曲线推断】的估计值，务必回到视频里肉眼抽查确认！！")
    print("!! 尤其 V_RISE / V_SET：亮度最陡处 ≠ 严格意义的日出/日落时刻。         !!")
    print("!! 若曲线受云、月亮、灯光影响，请手动在视频里找到真实拐点再填 CONFIG。  !!")
    print("!" * 78)


if __name__ == "__main__":
    main()
