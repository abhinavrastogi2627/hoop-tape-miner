# hoop-tape-miner 🏀

**从比赛录像里，挖出能赢下一场的东西。**

[![tests](https://github.com/mariusDing/hoop-tape-miner/actions/workflows/tests.yml/badge.svg)](https://github.com/mariusDing/hoop-tape-miner/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](pyproject.toml)
[![Agent: Claude Code | Codex](https://img.shields.io/badge/agent-Claude%20Code%20%7C%20Codex-8A2BE2.svg)](AGENTS.md)
[![good first issues](https://img.shields.io/github/issues/mariusDing/hoop-tape-miner/good%20first%20issue.svg?label=good%20first%20issues)](https://github.com/mariusDing/hoop-tape-miner/issues?q=is%3Aopen+label%3A%22good+first+issue%22)

[English](README.md) · 中文

面向业余和俱乐部球队的 AI 篮球录像分析。把你比赛的录像变成一份教练级复盘：比赛怎么输/赢的、对手怎么打、每个队员该练什么，还附带可以直接听的口播版。

你只需要一段比赛录像。你的 AI 编程助手（[Claude Code](https://claude.com/claude-code) 或 [Codex](https://openai.com/codex)）在你自己的 GPU 上跑完这个仓库里的计算机视觉流程，像教练一样看录像，然后写出报告。不用订阅，录像也不用上传到任何体育分析平台。

**适合谁**

- 每场都录像、但没时间回看的业余、俱乐部和野球队。
- 想在再次交手前拿到一份对手球探报告的队长和志愿教练。
- 想要一套能直接 fork 来改的篮球计算机视觉 + AI 看录像流程的开发者。

![报告页面：比分、口播大播放按钮、教练复盘正文](docs/images/hero.png)

## 你能得到什么

每场比赛一个文件夹，里面有：

- **教练复盘报告**，中英文，页面上一键切换。内容包括：比赛走势、对手核心球员和习惯、我们哪里打得好哪里不好、再碰面的打法、训练计划。
- **全队逐个球员复盘**：每人做得好、要改的地方，以及两个训练项目，可以直接发给全队。
- **图表**：分差和得分潮、投篮区域、热区图、两队对比。
- **口播 MP3**，中英文都有，页面上有大播放按钮，没时间看的队友路上就能听。
- **一个带解说的视频**：解说配着它讲的关键回合和图表播放，字幕直接烧在画面里（解说比回合长时自动半速重放）。队员打开就能看。
- **一个可分享的 HTML 文件**：图片、音频和录像片段都打包在里面，离线能打开，发到微信等聊天软件也能用。
- **可选**：给某个球员的单独深度复盘；以及一段可以循环播放的"场上口令" MP3（"两步内找人"），边打球边听。

报告里每一个结论都标了录像时间，关键回合还**直接在分析旁边配了录像片段**（可以慢放），大家一边看一边讨论下次怎么改。

| 中英双语 | 图表 | 手机上 |
|---|---|---|
| ![中文版报告](docs/images/report-zh.png) | ![报告里的图表](docs/images/charts.png) | ![手机视图](docs/images/mobile.png) |

*截图来自一场真实比赛，队名已替换。*

## 怎么做到的

```
比赛录像 ──► 计算机视觉（GPU，约 1 小时）──► AI 分段看录像 ──► 报告 + 图表 + 口播 ──► 一个 HTML 文件
            球员、球、场上位置               按教练清单逐段复盘     先整理事实再写作
            分队、识别球衣号码                                      每个结论附录像时间
```

1. **计算机视觉**：逐帧识别球员和球，映射到球场坐标，按球衣颜色分队，识别号码。
2. **回合与阵容**：谁在场上、谁持球、每个回合何时开始结束。如果你的联赛有官方技术统计，会自动和录像对齐。
3. **看录像复盘**：把比赛切成带标注的画面表，助手派多个子代理按教练清单逐段看（退防、对持球人施压、出手选择等）。
4. **先事实，后写作**：复盘结果汇总成事实表（正负值、上场段、模式、录像片段），再按 [`prompts/`](prompts/) 里的写作模板写报告。
5. **生成**：图表、口播（微软 Edge 神经语音）、关键回合的录像短片段（按报告里标的时间段用 ffmpeg 剪出），以及一个自包含的 HTML 页面。

详细说明见 [docs/pipeline.md](docs/pipeline.md)。

## 快速开始

### 1. 准备

- **NVIDIA 显卡**，显存 8 GB 以上，Windows 或 Linux（号码识别需要 CUDA）。
- [uv](https://docs.astral.sh/uv/)、Python 3.11，`ffmpeg` 在 PATH 里。
- 约 20 GB 硬盘空间放模型（第一次运行自动下载）。
- Claude Code 或 Codex。流程也可以手动跑，但看录像和写报告要靠 AI 助手。
- 一整场比赛录像，球场侧面单机位（俱乐部常见的那种录法）。

### 2. 安装

```bash
git clone https://github.com/mariusDing/hoop-tape-miner.git
cd hoop-tape-miner
uv sync
uv run hoop-tape-miner          # 列出所有步骤
```

### 3. 新建一场比赛

```bash
uv run hoop-tape-miner new-game --opponent "Red Foxes" --date 2026-10-14 --video path/to/game.mp4 --us-team "Night Owls"
```

这会创建 `workspace/teams/red-foxes/2026-10-14/`，里面的 `game.json` 需要你填：队名、球衣颜色、名单、最终比分。`workspace/` 里的一切只留在你自己电脑上，永远不会提交到 git。

### 4. 让 AI 助手来跑

在仓库里打开 Claude Code 或 Codex，说：

> 按 docs/playbook.md 分析 `workspace/teams/red-foxes/2026-10-14` 这场比赛。我们是 Night Owls，深蓝色球衣。

助手会按 [docs/playbook.md](docs/playbook.md) 一步步做（[`CLAUDE.md`](CLAUDE.md) 和 [`AGENTS.md`](AGENTS.md) 会把它引到那里）。中间只会停下来问你两次：

1. **球场标定**：在一帧画面上确认几个球场点位。
2. **队伍颜色**：确认哪个颜色是你们队。

跑完后打开 `workspace/teams/red-foxes/2026-10-14/index.html`。

### 5. 分享

```bash
uv run hoop-tape-miner html workspace/teams/red-foxes/2026-10-14 --share --out Night-Owls_vs_Red-Foxes.html
```

分享文件会把录像片段打包进去（480p，每 10 秒片段约 1 MB），十几段片段的报告大约几十 MB。片段里是真实球员，只发给本队（见 [docs/privacy.md](docs/privacy.md)）。

得到一个单文件，图片和音频都在里面，直接发聊天软件。如果聊天软件的内置浏览器禁用了脚本，页面会自动退回到手机自带的播放器。

## 命令一览

| 步骤 | 作用 |
|---|---|
| `new-game` | 创建比赛文件夹和 `game.json` |
| `calibrate` | 球场标定关键帧 |
| `extract` → `embed` → `tracks` → `jersey` | 计算机视觉：检测、分队、跟踪、号码 |
| `analyze` | 身份、回合、战术指标 |
| `official` | 导入联赛技术统计并和录像对齐（可选） |
| `coach-sheets` → `merge-reviews` → `coach-summary` | 复盘画面表，合并、汇总各代理的复盘 |
| `plusminus`、`report`、`momentum`、`replay` | 事实和图表 |
| `narrate` | 口播稿 → MP3（加 `--chime --gap 6 --loud` 就是场上循环口令） |
| `clips` | 按报告里的标记（`![说明](clip:07:24-07:33)`）剪出录像片段 |
| `film` | 带解说的视频：解说配着录像片段、定格圈人、战术动画和图表，烧录字幕（`film.<lang>.md` → `film.<lang>.mp4`） |
| `html` | 报告文件夹 → 一个双语 HTML（`--share` 生成可发送的单文件） |

每一步的参数：`uv run hoop-tape-miner <步骤> -h`。

## 目录结构

```
docs/playbook.md         助手照着做的完整流程：录像 → 报告
prompts/                 写作模板：复盘任务说明、教练报告、个人深度复盘、口播稿、场上口令
templates/               game.json 和对手档案的骨架
src/hoop_tape_miner/     流程代码（每一步一个模块）
workspace/               你自己的数据：录像、中间结果、报告（不进 git）
```

## 常见问题

**需要联网吗？** 模型只下载一次，之后视觉和分析都在本地跑。口播会把口播文字（不是录像）发给微软的语音合成服务。AI 助手本身用的是你自己的账号。

**没有 GPU、或者用 Mac 能跑吗？** 暂时不行。检测可以退回 CPU，但非常慢；号码识别需要 CUDA。

**我们联赛没有官方技术统计？** 没关系，在 `game.json` 里填上最终比分，报告只靠录像复盘也能生成。

**准不准？** 视觉部分给出位置和回合，判断来自看录像复盘；看不清的（比如号码）会标"疑似"。采纳之前先去看报告指出的那段录像。

**支持哪些语言？** 报告和口播都有中文和英文。

**隐私。** 报告会点名球员，也会有真人画面。分享前请读 [docs/privacy.md](docs/privacy.md)，尤其是联赛里有未成年人的时候。

## 现状和路线图

已经在真实比赛上完整跑通（单机位侧面录像，NVIDIA GPU）。已知限制和下一步：

- [ ] 不用 CUDA 也能跑（CPU 或 Apple Silicon 上的号码识别）
- [ ] 一场谁都能跑的合成演示比赛，里面没有真人
- [ ] 支持更多联赛的技术统计导入（目前只支持一种格式，见 [`official.py`](src/hoop_tape_miner/official.py)）
- [ ] 中英文之外的更多报告和口播语言
- [ ] 更好地处理会转动的机位或手机录像

欢迎在 [Discussions](https://github.com/mariusDing/hoop-tape-miner/discussions) 里提想法、投票。

## 参与贡献

从改一个错别字到新增一个联赛导入器，都欢迎。先看 [CONTRIBUTING.md](CONTRIBUTING.md) 和 [good first issues](https://github.com/mariusDing/hoop-tape-miner/issues?q=is%3Aopen+label%3A%22good+first+issue%22)，有问题去 [Discussions](https://github.com/mariusDing/hoop-tape-miner/discussions) 问。

一条硬规定：永远不要在 issue 或 PR 里附上比赛录像、截图、名单或真实球员的名字。详见 [docs/privacy.md](docs/privacy.md)。

请遵守[行为准则](CODE_OF_CONDUCT.md)。安全问题请按 [SECURITY.md](SECURITY.md) 私下报告。

## 致谢

基于 [RF-DETR](https://github.com/roboflow/rf-detr)、[supervision](https://github.com/roboflow/supervision) / [trackers](https://github.com/roboflow/trackers)、[SigLIP](https://huggingface.co/google/siglip-base-patch16-224)、[Qwen3-VL](https://huggingface.co/Qwen)、[edge-tts](https://github.com/rany2/edge-tts)，并参考了 [basketball_analysis](https://github.com/abdullahtarek/basketball_analysis)。详见 [docs/research.md](docs/research.md)。

## 许可证

[MIT](LICENSE)。运行时下载的模型各自遵循它们自己的许可证。

引用本项目：点 GitHub 右侧栏的 **Cite this repository**（[CITATION.cff](CITATION.cff)）。

如果对你的球队有帮助，点个 ⭐ 让更多人看到。
