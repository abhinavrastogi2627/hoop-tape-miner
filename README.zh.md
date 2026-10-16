# hoop-tape-miner 🏀

**从比赛录像里，挖出能赢下一场的东西。**

[![tests](https://github.com/mariusDing/hoop-tape-miner/actions/workflows/tests.yml/badge.svg)](https://github.com/mariusDing/hoop-tape-miner/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](pyproject.toml)
[![Agent: Claude Code | Codex](https://img.shields.io/badge/agent-Claude%20Code%20%7C%20Codex-8A2BE2.svg)](AGENTS.md)
[![good first issues](https://img.shields.io/github/issues/mariusDing/hoop-tape-miner/good%20first%20issue.svg?label=good%20first%20issues)](https://github.com/mariusDing/hoop-tape-miner/issues?q=is%3Aopen+label%3A%22good+first+issue%22)

[English](README.md) · 中文

面向业余和俱乐部球队的 AI 篮球录像分析。贴上比赛链接，就能拿到一份教练会给你的复盘：比赛怎么打的、为什么输/赢、对手做了什么、下一步练什么。有两种形式：可以读也可以听的网页，和一段配着比赛画面讲解的视频。

你的 AI 编程助手（[Claude Code](https://claude.com/claude-code) 或 [Codex](https://openai.com/codex)）在你自己的 GPU 上跑完这个仓库里的计算机视觉流程，像教练一样看录像，然后把所有东西写出来。不用订阅，录像也不用上传到任何体育分析平台。

**适合谁**

- 每场都录像、但没时间回看的业余、俱乐部和野球队。
- 想在再次交手前拿到一份对手球探报告的队长和志愿教练。
- 想要一套能直接 fork 来改的篮球计算机视觉 + AI 看录像流程的开发者。

![报告页面：比分、口播大播放按钮、教练复盘正文](docs/images/hero.png)

## 你能得到什么

每场比赛两样东西：

1. **网页，以链接分享**：一个全队页面和一个重点球员页面，都是中英文，页面上一键切换。
   - 全队页面：比赛走势、对手核心球员和习惯、我们哪里打得好哪里不好、再碰面的打法、训练计划，以及每个队员的复盘和两个训练项目。
   - 球员页面：针对一个球员的深度复盘，只发给他本人。
   - 每个页面都有一个**口播**大播放按钮，不想读的队友可以在去训练的路上听。
   - **关键回合的录像片段就放在分析旁边**（带慢放），还有一张标出得分潮的分差走势图。
   - 每个页面有一个固定的、不公开的链接（Cloudflare 免费）。改完再发布一次，已经发出去的链接就显示新版本。
2. **讲解视频**，每种语言一个：口播配着它讲到的关键回合和图表，定格画面圈出球员，字幕烧在画面里。就是普通的 MP4，由你自己发出去，不会上传到任何地方。

每个结论都标了录像时间，球队讨论要改什么的时候可以直接看那一刻。

| 双语报告 | 图表 | 手机上看 |
|---|---|---|
| ![中文版报告](docs/images/report-zh.png) | ![报告里的图表](docs/images/charts.png) | ![手机界面](docs/images/mobile.png) |

*截图来自一场真实比赛，队名已替换。*

代码还能做对手档案、场上提示音循环、战术板回放、投篮区域图和单个离线 HTML 文件。这些是可选的附加项（见 [playbook](docs/playbook.md#optional-extras)）。

## 工作原理

```
联赛链接 ──► 抓取 ──────────────► 计算机视觉（GPU，约 1 小时）──► AI 看录像复盘 ──► 网页、口播 ──► 链接
             录像、技术统计、       球员、球、球场位置、                              片段          + 讲解视频
             得分流水、名单         两队、球衣号码
```

1. **抓取：** 助手从联赛网站读取比赛（两队、名单、比分、技术统计、每次得分后的比分），并下载比赛录像。
2. **计算机视觉：** 每一帧检测球员和球，映射到球场上，按球衣颜色分出两队，识别球衣号码，算出上场阵容和回合。球场标定由助手自己读带网格的画面完成，不需要人去点。
3. **看录像复盘：** 比赛被切成带标注的帧拼图，子助手按教练检查清单逐段过一遍：退防、对球施压、投篮选择等。
4. **先事实，后写作：** 复盘结果先汇总成事实表（正负值、上场时段、规律、片段），再按 [`prompts/`](prompts/) 里的写作指南写出页面。
5. **渲染和分享：** 口播（微软 Edge 神经语音）、关键回合片段、HTML 页面（以链接发布）和讲解视频。

全部由一条命令驱动：`hoop-tape-miner run`。它知道每一步产出哪个文件，所以中断后从停下的地方接着跑，只在需要助手看或写的地方暂停。详细说明：[docs/pipeline.md](docs/pipeline.md)。

## 快速开始

### 1. 需要什么

- 一块 **NVIDIA 显卡**，8 GB 显存或以上，Windows 或 Linux。号码识别需要 CUDA。
- [uv](https://docs.astral.sh/uv/)、Python 3.11，以及 PATH 上的 `ffmpeg`。发布和页面检查需要 Node.js。
- 大约 20 GB 硬盘放模型，第一次用时自动下载。
- Claude Code 或 Codex。看录像复盘和写作都是助手的活。
- 一场由球场侧面单机位拍的比赛：联赛录像（链接）或者你自己的录像。

### 2. 安装

```bash
git clone https://github.com/mariusDing/hoop-tape-miner.git    # 或者你的 fork
cd hoop-tape-miner
uv sync
uv run hoop-tape-miner          # 列出所有步骤
```

### 3. 告诉它你是谁（只做一次）

```bash
mkdir -p workspace && cp templates/team.example.json workspace/team.json
```

填上联赛里显示的队名、球衣颜色、重点球员号码、报告语言，以及一个放在**仓库外面**的密钥文件路径，里面是你的联赛登录信息（两行：`GLORY_EMAIL=...` 和 `GLORY_PASSWORD=...`）。`workspace/` 里的东西都只留在你的电脑上，永远不会提交。

要用链接分享，注册一个免费的 Cloudflare 账号，运行一次 `npx wrangler login`。

### 4. 每场比赛之后，贴上链接

在仓库里打开 Claude Code：

```
/game https://my.gloryleague.basketball/game/<id>/overview
```

用 Codex（或其他助手）就说：*"这是我们的比赛：`<链接>`。按 AGENTS.md 跑完。"*

助手会运行 `uv run hoop-tape-miner run <链接>`，自己完成需要"看"的步骤：球场标定点、哪个颜色是哪队、看录像复盘、写作，以及用浏览器检查页面。然后发布页面，回复你链接和两个视频的路径。GPU 部分大约一小时，再加上助手的工作时间。

**别的联赛，或者没有联赛数据？** 从你自己的录像开始：`uv run hoop-tape-miner new-game --opponent "Red Foxes" --date 2026-10-14 --video game.mp4 --us-team "Night Owls"`，填好 `game.json`，再对这个文件夹 `run`。技术统计和得分流水是可选的：把你联赛的数据转成 `official.json` 的格式（见 [playbook 第 6 步](docs/playbook.md#6-official-stats-and-result)），或者让报告只靠录像复盘。欢迎贡献其他联赛网站的 `fetch`。

### 5. 分享

- 网页：把总览页（新比赛会自动出现在上面）或全队页面的链接发给全队；球员页面只发给那个球员。链接不公开，但没有密码。
- 讲解视频：把 `film.zh.mp4` / `film.en.mp4` 发到球队群里。
- 片段和视频里有真人：只分享给本队（见 [docs/privacy.md](docs/privacy.md)）。

## 命令

| 步骤 | 做什么 |
|---|---|
| `run` | 一场比赛从头到尾：按顺序跑下面的每一步，可中断续跑，在需要助手判断的地方暂停（`--status`、`--publish`） |
| `fetch` | 联赛比赛链接 → `game.json`、技术统计和得分流水、比赛录像 |
| `new-game` | 手动建比赛文件夹和 `game.json`（没有联赛数据时） |
| `calibrate` | 球场标定：`--grid` 生成供阅读的网格画面，`--points` 求解并检查 |
| `extract` → `embed` → `tracks` → `jersey` | 计算机视觉：检测、分队、跟踪、球衣号码 |
| `analyze` | 身份、回合、战术指标 |
| `coach-sheets` → `coach-summary`、`plusminus` | 复盘用的帧拼图，以及助手复盘结果的统计 |
| `momentum` | 带得分潮的分差走势图 |
| `clips` | 剪出报告里标记的片段（`![说明](clip:07:24-07:33)`） |
| `narrate` | 口播稿 → MP3 |
| `html` | 报告文件夹 → 一个双语 HTML 页面 |
| `publish` | 页面 → Cloudflare 上的私密链接网站，每份报告一个固定链接 |
| `film` | 讲解视频：口播配片段、定格画面、战术图和图表，带字幕 |
| `official`、`recalib`、`report`、`replay`、`review`、`merge-reviews` | 可选：导入联赛 JSON、重跑球场映射、视觉图表、战术板回放、事件复盘 |

每一步的参数用 `uv run hoop-tape-miner <步骤> -h` 查看。

## 项目结构

```
.claude/commands/game.md   Claude Code 的 /game 命令
AGENTS.md                  给所有助手的说明（CLAUDE.md 指向这里）
docs/playbook.md           助手照着做的流程，链接 → 页面 + 视频
prompts/                   写作指南：复盘任务说明、教练报告、球员深度复盘、口播、讲解视频
templates/                 team.json、game.json 和对手档案的模板
src/hoop_tape_miner/       流程代码（每一步一个模块；run.py 串起来）
workspace/                 你自己的数据：球队档案、比赛、报告（不进 git）
```

## 常见问题

**需要联网吗？** 模型只下载一次，之后视觉和分析都在本地跑。抓取会读联赛网站，口播会把口播文字（不是录像）发给微软的语音合成服务，发布会把页面、音频和片段（不是整场录像）上传到你自己的 Cloudflare 账号。AI 助手本身用的是你自己的账号。

**没有 GPU、或者用 Mac 能跑吗？** 暂时不行。检测可以退回 CPU，但非常慢；号码识别需要 CUDA。

**我们联赛没有技术统计，或者不是 Glory League？** 没关系。用 `new-game` 开始，在 `game.json` 里填上最终比分，报告只靠录像复盘也能生成。如果你们联赛有公开数据，可以转成 `official.json` 的格式，或者给它写一个 `fetch`。

**准不准？** 视觉部分给出位置和回合，判断来自看录像复盘；看不清的（比如号码）会标"疑似"。采纳之前先去看报告指出的那段录像。

**支持哪些语言？** 网页、口播和视频都有中文和英文。

**隐私。** 报告会点名球员，也会有真人画面。分享前请读 [docs/privacy.md](docs/privacy.md)，尤其是联赛里有未成年人的时候。

## 现状和路线图

已经在真实比赛上完整跑通（单机位侧面录像，NVIDIA GPU）。已知限制和下一步：

- [ ] 不用 CUDA 也能跑（CPU 或 Apple Silicon 上的号码识别）
- [ ] 一场谁都能跑的合成演示比赛，里面没有真人
- [ ] 支持更多联赛的 `fetch`（目前是 Glory League，见 [`fetch.py`](src/hoop_tape_miner/fetch.py)）
- [ ] 中英文之外的更多报告和口播语言
- [ ] 更好地处理会转动的机位或手机录像

欢迎在 [Discussions](https://github.com/mariusDing/hoop-tape-miner/discussions) 里提想法、投票。

## 参与贡献

从改一个错别字到新增一个联赛抓取器，都欢迎。先看 [CONTRIBUTING.md](CONTRIBUTING.md) 和 [good first issues](https://github.com/mariusDing/hoop-tape-miner/issues?q=is%3Aopen+label%3A%22good+first+issue%22)，有问题去 [Discussions](https://github.com/mariusDing/hoop-tape-miner/discussions) 问。

一条硬规定：永远不要在 issue 或 PR 里附上比赛录像、截图、名单或真实球员的名字。详见 [docs/privacy.md](docs/privacy.md)。

请遵守[行为准则](CODE_OF_CONDUCT.md)。安全问题请按 [SECURITY.md](SECURITY.md) 私下报告。

## 致谢

基于 [RF-DETR](https://github.com/roboflow/rf-detr)、[supervision](https://github.com/roboflow/supervision) / [trackers](https://github.com/roboflow/trackers)、[SigLIP](https://huggingface.co/google/siglip-base-patch16-224)、[Qwen3-VL](https://huggingface.co/Qwen)、[edge-tts](https://github.com/rany2/edge-tts)，并参考了 [basketball_analysis](https://github.com/abdullahtarek/basketball_analysis)。详见 [docs/research.md](docs/research.md)。

## 许可证

[MIT](LICENSE)。运行时下载的模型各自遵循它们自己的许可证。

引用本项目：点 GitHub 右侧栏的 **Cite this repository**（[CITATION.cff](CITATION.cff)）。

如果对你的球队有帮助，点个 ⭐ 让更多人看到。
