# Real-time Day/Night Timelapse Wallpaper · 实时昼夜延时壁纸

> **English abstract.** Turn *any* fixed-camera, full-day/night-cycle timelapse video into a
> live wallpaper whose progress follows the **real sun position at your location**. The video is
> cut into small chunks and played at **1× (real speed, no time-stretching)**; a NOAA-based solar
> model maps the *real* solar altitude onto the *footage's own* solar altitude, picks the right
> chunk and position, and re-syncs with a 0.3 s cross-fade only when the on-screen time drifts
> past a threshold. Works in Wallpaper Engine or any browser. Code is MIT-licensed; you supply
> your own footage.

---

## 这是什么

把一段**固定机位、覆盖完整昼夜循环**的延时/实拍视频，变成一张**跟着你所在地真实太阳位置走**的实时壁纸：

- 你所在地此刻是清晨、正午、黄昏还是深夜，画面就处在对应位置；
- 日出、日落、正午、午夜按**你填的经纬度实时推算**（NOAA 太阳位置算法），与今天真实的时刻一致；
- 画面**不是**把这一帧钉死的静态图，而是按 **1× 原速顺播**，看起来像一段正在发生的实拍；
- 偏离真实时刻超过阈值时，用一次 **0.3 秒叠化**悄悄「跳回」正确位置。

支持 Wallpaper Engine 的 web 壁纸，也可以直接丢进浏览器调试。**本项目只发布代码，不含任何影像素材，你需要自备素材。**

---

## 原理

核心思想：**把「真实太阳位置」映射到「素材里的太阳位置」**，两种世界各自的太阳高度角一一对应。

```
        真实世界（你所在地）                          素材世界（视频拍的那一天）
        ─────────────────────                       ──────────────────────────

              真实时刻 t
                 │
                 │  NOAA 太阳位置算法
                 ▼
          真实太阳高度角 A        ── 分段线性重映射 ──▶      素材太阳高度角 A'
          （−90° … +90°）              （见下）          （由 V_LAT / V_DECL 决定）
                                                               │
                                                               │ 素材自身的“日晷”反解
                                                               ▼
                                                 素材时间轴位置 v（0 … LOOP 秒）
                                                               │
                                            ┌──────────────────┴──────────────────┐
                                            ▼                                     ▼
                                  选块 k = chunkIndexFor(v)              块内偏移 = v − BOUNDS[k]
                                            │
                                            ▼
                        双缓冲 <video> 从 chunks/00k.mp4 的「偏移处」1× 顺播
```

**「分段线性重映射」到底重映射了什么？** 一天分成 6 个相位，每个相位里太阳高度角都是单调的：

| 相位 | 真实世界（按太阳高度角 A 判断） | 素材世界（对应素材区间） |
|---|---|---|
| 上午   | 日出（−0.833°）→ 正午（今日正午高度角） | `V_RISE` → `V_NOON` |
| 下午   | 正午 → 日落（−0.833°）                  | `V_NOON` → `V_SET + LOOP` |
| 黄昏   | 日落（−0.833°）→ 天文暮光（−18°）        | `V_SET + LOOP` → 全黑（`DUSK_LEN` 秒后） |
| 深夜   | −18° → 太阳午夜                          | 全黑 → `V_MID + LOOP` |
| 后半夜 | 午夜 → −18°                              | `V_MID + LOOP` → `V_RISE + LOOP − DAWN_LEN` |
| 黎明   | −18° → 日出（−0.833°）                   | 拂晓 → `V_RISE + LOOP` |

在每一个相位内，取「真实高度角走到本相位的百分之几」，让素材在「对应相位」内也走同样的百分比。
这样做的效果是：

- 日出、日落、正午、午夜四个**锚点**仍精确落在真实时刻；
- 黎明、黄昏、正午的**快慢比例跟随真实太阳**，而不是在两个锚点之间草率地线性拉伸；
- 素材的昼长不必等于今天的真实昼长 —— 它会被**等比例缩放**到今天的太阳轨迹上。

> 素材自身的太阳高度角由两个标定常量决定：`V_LAT`（素材拍摄纬度）与 `V_DECL`（当天太阳赤纬）。
> 「素材世界正午高度角」= `90 − |V_LAT − V_DECL|`。这两个数**必须对**，否则整套映射会整体偏。

---

## 为什么是「1× 顺播 + 定期跳回」，而不是变速播放

要让画面进度跟上真实时间，直观想法是**变速播放**（把 24 小时压进素材时长）。但这条路有两个硬伤：

1. **慢放像 PPT。** 需要的倍率 ≈ `24h ÷ 素材时长`。素材若只有几分钟，倍率就是几百倍，
   相当于每个真实秒钟画面只前进几帧 —— 画面一格一格地蹦，完全不像「实时」。
   只有把素材拉长到几小时，1× 的顺播才看起来像实拍在走。
2. **无法适配不同的昼长。** 变速播放要求素材的昼长恰好等于你所在地**今天**的真实昼长。
   同一段夏日素材，冬天用不了；同一段低纬素材，高纬用不了；差一点，日出日落就永远对不上。

本方案**反过来做**：

- 让素材**始终 1× 原速顺播**（画面流畅、像实时，不受素材时长与昼长差异影响）；
- 后台持续比较「画面所处时刻」与「真实时刻」，**偏差没超阈值就不去打断它**；
- 一旦偏差超过阈值，用**一次 0.3 秒叠化**把画面「跳回」正确位置。

于是误差被限制在一个小区间内来回摆动，而那一次跳跃被叠化藏了起来。用一小段素材撑起一整天，
靠的就是这个 **「空间（素材长度）换时间（真实时长）＋ 定期校表」** 的技巧。

相关常量：`DRIFT_MAX_VID`（触发对时的画面偏差阈值，单位=素材秒）、`XFADE_DRIFT`（对时叠化时长）。

---

## 目录结构

```
realtime-timelapse-wallpaper/
├── index.html                  # 运行时：所有逻辑都在这里（顶部是 CONFIG 配置块）
├── project.json                # Wallpaper Engine 项目描述
├── README.md                   # 本文档
├── chunks/                     # ← 你需要自己放切好的片段：000.mp4, 001.mp4, …
│   └── chunks.csv              # cut-video.py 生成的清单（文件名, 起始秒, 结束秒）
└── tools/
    ├── cut-video.py            # 把长视频等长切成 chunks/000.mp4，并打印 BOUNDS
    └── measure-calibration.py  # 【辅助】用亮度曲线找日出/日落/正午/午夜
```

> `chunks/` 与其中的视频**不在仓库里**（见文末版权提醒）。你放置素材后，应形如
> `chunks/000.mp4, chunks/001.mp4 … chunks/0NN.mp4`，编号从 `000` 开始、补零到 3 位。

---

## 快速开始

1. 准备一段**固定机位、完整昼夜循环**的视频（见下一节）。
2. 用 `tools/cut-video.py` 切块，把它打印的 `LOOP / NCHUNK / BOUNDS` 填进 `index.html` 的 CONFIG。
3. 用 `tools/measure-calibration.py`（+ 肉眼确认）找出 `V_SET / V_MID / V_RISE / DUSK_LEN / DAWN_LEN`，以及 `V_LAT / V_DECL`，填进 CONFIG。
4. 把整个文件夹放进 Wallpaper Engine 或在浏览器打开 `index.html`。

---

## 如何准备素材

**拍摄/获取要求：**

- **固定机位**：三脚架固定、画面不动。手持或移动机位不行 —— 画面里的太阳轨迹与地理模型对不上。
- **完整昼夜循环**：至少覆盖「白天 → 黑夜 → 白天」，最好正好一整天。缺了哪一段，映射到该时段就会出问题。
- **等速或近似等速**：整段按相同的间隔抽帧（例如每 10 秒 1 帧）。忽快忽慢的延时会让「时间 → 亮度/太阳位置」的关系失真。
- **时长建议**：切块前总时长**几小时**比较理想 —— 太短（几分钟）会让 1× 顺播的可行时长偏短、对时更频繁；太长会让体积变大。经验值 2～4 小时、几十到上百块都可以。
- 尽量避免剧烈的云层变化、镜头渐晕/自动曝光，它们会干扰标定与观感。

**如何切块（两种方式）：**

方式 A（推荐）——用本仓库脚本，自动打印可直接粘进 CONFIG 的 BOUNDS：

```bash
# 均分成 96 块
python tools/cut-video.py path/to/daynight.mp4 --chunks 96

# 或每块 120 秒
python tools/cut-video.py path/to/daynight.mp4 --chunk-seconds 120
```

方式 B ——直接用 ffmpeg 的 segment 分割（切点会对齐关键帧，边界不如方式 A 精确，**不建议**用于 `-c copy`）：

```bash
# 每 125 秒切一块，输出 chunks/000.mp4、chunks/001.mp4 …
ffmpeg -i daynight.mp4 -c copy -map 0 -f segment \
       -segment_time 125 -reset_timestamps 1 -segment_format mp4 \
       chunks/%03d.mp4
```

> 切块方式只影响「块」这个粒度。真正决定画面位置的是 CONFIG 里的 `BOUNDS` 与 `LOOP`，
> 所以务必让它们和实际切出来的片段一致 —— 用 `cut-video.py` 最省事，它会把
> `LOOP / NCHUNK / BOUNDS` 直接打印出来。

---

## 如何标定素材（最重要的一节）

标定不准，画面就会和真实时间**整体错位**（例如明明中午却显示夜景），而且很难事后察觉。
请务必认真做这一步。所有结果都填进 `index.html` 顶部的 CONFIG。

### ① 找出 V_SET / V_MID / V_RISE（四个锚点里的三个）

把**原始长视频**（不是切块后的）拖进任意播放器，反复回看，记下三个**素材秒数**：

- `V_SET`：画面开始**明显变暗**的那一刻（太阳落到地平线）。看画面亮度/天空颜色的拐点，不要只看某一帧。
- `V_MID`：画面**最暗**的那一刻（午夜）。
- `V_RISE`：画面开始**明显变亮**的那一刻（日出）。
- 参考值：最亮的正午（不用填，仅帮助理解曲线形状）。

可以用 `tools/measure-calibration.py` 得到初值，再**肉眼抽查**：

```bash
python tools/measure-calibration.py path/to/daynight.mp4 --step 5
```

它会画一条亮度曲线并给出 `V_MID / V_RISE / V_SET` 的建议值 —— 但**亮度最陡处 ≠ 严格意义的日出/日落**，
遇到云、月亮、灯光会误判，**一定要回到视频里确认**。

### ② 找出 DUSK_LEN / DAWN_LEN

- `DUSK_LEN`：从**日落**到画面**完全黑下来**之间的素材秒数（日落 → 全黑）。
- `DAWN_LEN`：从**还是全黑**到**日出**之间的素材秒数（全黑 → 日出）。

这两个值用来把真实的「黄昏 / 黎明」段按比例铺到素材上，让暮色过渡的快慢也对得上。
`measure-calibration.py` 会用「最暗的一整段」给出估计，同样需要肉眼修正。

### ③ 反推 V_LAT 与 V_DECL

素材拍在某天某个纬度，它的**白昼长度**是已知的。由昼长可以反推「素材纬度 + 太阳赤纬」：

```
昼长 H 小时  →  日出时角半宽  hA = H × 15 ÷ 2   （度）
并且                cos(hA) = − tan(纬度) × tan(赤纬)
```

一个方程解不出两个未知数，所以**先固定一个、再求另一个**（补一个假设）：

- 常见做法：按**拍摄季节**确定太阳赤纬 δ（查天文历/太阳赤纬表），再反推纬度 φ；
- 或反过来：已知拍摄纬度 φ，再反推当天赤纬 δ。

**示例**（本项目 CONFIG 里的默认值就是这么来的）：

```
素材白昼 ≈ 14.2 小时（= 素材白昼秒数 ÷ LOOP × 24）
hA = 14.2 × 15 ÷ 2 = 106.5°       →  cos(hA) = −0.286
取拍摄季节赤纬 δ = +18°（夏日）   →  tan(δ) = 0.325
纬度 φ = atan( 0.286 ÷ 0.325 ) = 41.3°   →  取整为 V_LAT = 41.8°
V_DECL = +18
⇒ 素材世界正午高度角 = 90 − |41.8 − 18| = 66.2°
```

`measure-calibration.py` 会在给出昼长后，用 `--decl`（已知赤纬求纬度）或 `--lat`（已知纬度求赤纬）帮你算：

```bash
python tools/measure-calibration.py path/to/daynight.mp4 --decl 18   # 求 V_LAT
python tools/measure-calibration.py path/to/daynight.mp4 --lat 41.8 # 求 V_DECL
```

> 注意：`V_LAT` 与 `V_DECL` 需要**同号**才能得到「长昼」（夏日、北半球 +/+）。若你得到的是
> 「白昼不足 12 小时」的素材，说明拍摄时是冬半年，两者可能为异号，请按实际季节确定。

### ④ 关于 V_NOON

`V_NOON`（素材正午位置）**不需要你填**，运行时按 `V_RISE + ((LOOP − V_RISE) + V_SET) ÷ 2` 自动算出。

### 标定错误的后果

- `V_SET / V_MID / V_RISE` 偏 N 秒 → 画面整体比真实时间早/晚约 N 素材秒对应的时刻，日出日落尤其明显；
- `V_LAT / V_DECL` 偏 → 各时段**快慢比例**失真（正午附近偏离、早晚偏移）；
- `DUSK_LEN / DAWN_LEN` 偏 → 黄昏/黎明过渡的节奏不对。

---

## 如何部署

### 在 Wallpaper Engine 里

1. 把整个 `realtime-timelapse-wallpaper/` 文件夹放到你的 Wallpaper Engine 项目目录下，例如
   `…/wallpaper_engine/projects/myprojects/realtime-timelapse-wallpaper/`（自行新建即可）。
2. 把切好的片段放进该目录下的 `chunks/`。
3. 打开 Wallpaper Engine，在「已安装 / 我的壁纸」里**从文件导入**，选择该目录下的 `index.html`。
4. 进入壁纸的属性面板，填写**纬度 / 经度 / 时区**，必要时用「时间偏移」微调；改完画面会立刻重新对时。

### 在浏览器里直接调试

- 直接双击 `index.html` 可以跑；但 `file://` 下联网查询时区（`lookup` 模式）可能被浏览器限制而失败，
  此时会自动退化为「按经度估算」，你也可以改用「跟随本机时区」或手动 UTC 偏移。
- 想在浏览器里用完整的 `lookup` 时区查询，起一个本地 http 服务再访问：
  ```bash
  python -m http.server 8000
  # 然后浏览器打开 http://localhost:8000/index.html
  ```

---

## CONFIG 参数速查（都在 `index.html` 顶部）

| 参数 | 含义 | 怎么得到 |
|---|---|---|
| `CHUNK_SECONDS` | 每块时长（秒） | `cut-video.py` 打印 |
| `NCHUNK` | 块数 | `cut-video.py` 打印 |
| `LOOP` | 素材总时长（秒），也是「一整天」在素材轴上的长度 | `cut-video.py` 打印 |
| `BOUNDS` | N+1 个块边界（秒） | `cut-video.py` 打印，整行粘入 |
| `V_SET / V_MID / V_RISE` | 素材里日落 / 午夜 / 日出 的秒数 | 肉眼找 + `measure-calibration.py` 辅助 |
| `DUSK_LEN / DAWN_LEN` | 日落→全黑、全黑→日出 的素材秒数 | 肉眼找 + `measure-calibration.py` 辅助 |
| `V_LAT / V_DECL` | 素材拍摄纬度、当天太阳赤纬 | 由素材昼长反推（见上） |
| `LAT / LON` | 默认观察者经纬度（示例值） | 填你自己所在城市 |
| `DRIFT_MAX` | 现实偏差显示上限（秒） | 一般不用改 |
| `DRIFT_MAX_VID` | 触发对时的「画面偏差」阈值（素材秒） | 一般不用改 |
| `XFADE / XFADE_DRIFT / XFADE_SYNC / XFADE_WAKE_LONG` | 各处叠化时长（秒） | 一般不用改 |
| `VIDEO_FPS` | 素材帧率（仅文档参考） | 你的素材帧率 |

---

## 局限与已知问题

- **残余偏差**：因为采用「1× 顺播 + 阈值触发对时」，画面与真实时刻之间始终存在一个**有界的摆动误差**
  （工程量级最高约 `DRIFT_MAX_VID` 对应的现实分钟数，通常几十分钟；默认阈值下典型偏差在 ±45 分钟内）。
  这是「流畅优先」的设计取舍 —— 想要更准，可以调小 `DRIFT_MAX_VID`，代价是对时更频繁、叠化更密集。
- **对时瞬间有一次叠化**：0.3 秒，通常不易察觉，但在明暗突变处仍可能被注意到。
- **体积由素材决定**：最终占用 ≈ 所有片段之和。切块重编码会有累积损失，请用合理 CRF / 码率；
  用 `--copy` 可无损但边界不精确（会影响 `BOUNDS` 与实际的吻合度）。
- **只适用于固定机位**：手持、移动、变焦的素材不适用。
- **极端纬度**：极昼 / 极夜时太阳高度角在一天内可能不单调，映射会退化，观感可能异常。
- **联网依赖**：`lookup` 时区模式依赖 `timeapi.io`；断网时退化为按经度估算。
- **时区/偏移**：若你所在时区有夏令时且用了「跟随本机/手动」，请自行确保偏移正确，否则「当地几点」会错。

---

## 版权提醒

- 本仓库**只发布代码、脚本与文档，不包含任何影像素材**。
- 请**自备**你有权使用的素材（自己拍摄的，或已获授权的）。**不要**把影视、游戏、他人作品里的
  画面剪成片段随本项目一起分发或上传，这会侵犯版权。
- `chunks/` 目录下的视频请勿提交到公开仓库（可在 `.gitignore` 中忽略）。

---

## 许可

代码部分采用 **MIT License**。

用到的第三方 / 公开算法：

- **NOAA 太阳位置算法**（太阳赤纬、时差、太阳高度角的经验公式）—— 属于 NOAA 公开发布的
  大气/太阳几何公式，可自由使用；本项目的 `sunTimes` / `sunParams` / `sunAltRad` 即由此实现。
- **[timeapi.io](https://timeapi.io)** —— 在 `lookup` 时区模式下按其经纬度坐标接口查询 IANA 时区名
  与当前 UTC 偏移（含夏令时）。使用前请遵守其服务条款。
- 本项目**未**使用 SunCalc 等第三方库，全部计算为自实现。

---

## 致谢

太阳位置公式参考 NOAA Solar Calculator 的公开算法；实时对时思路受「用一段短素材撑起长时段、
再定期校表」这一朴素工程直觉启发。欢迎按自己的素材重新标定并分享改进。
