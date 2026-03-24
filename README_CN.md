# WhisperDictate

macOS 本地语音输入 — 按住 FN 说话，松开即转录。基于 [MLX Whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper)，Apple Silicon 原生加速。

<p align="center">
  <code>◦ ──────────────</code> → <code>♪ ───│──────</code> → <code>✎ ┄┄┄┄┄┄</code> → <code>✓ ──────────────</code>
</p>

## 为什么做这个？

市面上有不少不错的语音输入工具——macOS 听写、Typeless、微信语音输入都做得很好。WhisperDictate 填的是一个特定的空位：

- **免费 + 纯本地** — 不订阅，不上云，音频不离开你的 Mac
- **只做输入，不做助手** — 有些工具会自动补全、回答问题，但你真的不需要一个输入法来回答问题。WhisperDictate 只转录你说的话，不多不少
- **开源可改** — ~500 行 Python，想怎么改怎么改
- **中英混合** — 关键词纠偏机制对专有名词的识别明显好于通用方案

## 中英文混合：核心优势

Whisper large-v3-turbo 天然支持多语言识别，不需要手动切换语言。你可以这样说：

> "帮我看一下 NVIDIA 的 Q3 earnings，revenue 同比增长了多少"

直接输出：`帮我看一下 NVIDIA 的 Q3 earnings，revenue 同比增长了多少`

**关键词纠偏机制**进一步提升专有名词准确率：

| 场景 | 无关键词 | 有关键词 |
|------|---------|---------|
| 公司名 | "因伟达" → 漏掉 | NVIDIA ✓ |
| 金融术语 | "SP500" | S&P 500 ✓ |
| 中文易混词 | "舱位" | 仓位 ✓ |
| 中文易混词 | "你回购" | 逆回购 ✓ |
| 中文易混词 | "空头" | 空投 ✓ |
| 英文术语 | "watchless" | watchlist ✓ |

只需把常用术语加到 `~/.config/whisper/keywords.txt`，Whisper 会自动往正确拼写上靠。

## 功能特性

- **完全本地** — 不联网，不上传，数据不离开你的 Mac
- **免费** — 无订阅，无用量限制
- **FN 按住说话** — 按住 FN 录音，松开自动转录并粘贴到光标位置
- **极简 UI** — 屏幕底部 170×20 像素浮动条，不抢焦点，不遮挡内容
- **中英文混合** — 一句话里自由切换中英文，无需手动切语言
- **智能后处理** — 8 步 regex 引擎，自动去除 Whisper 幻觉、重复片段、口水词
- **关键词提示** — 自定义关键词表，提升专有名词（人名/公司名/术语）识别率
- **窗口检测** — 录音时没切窗口→自动粘贴；切了窗口→显示 Copy 按钮，手动粘贴
- **右键菜单** — 右键浮动条：编辑关键词、查看历史、切换麦克风、退出
- **转录历史** — JSONL 格式，7 天自动清理，方便找回之前说过什么
- **内存自管理** — 定期清理缓存，内存过高时自动重启

## 对比

| | WhisperDictate | macOS 听写 | Typeless | 微信语音输入 |
|---|---|---|---|---|
| 隐私 | 纯本地 | 云端（Apple） | 云端或本地 | 云端（腾讯） |
| 费用 | 免费 | 免费 | $8-15/月 | 免费 |
| 速度 | ~2-3 秒 | 快 | 快 | 快 |
| 后处理 | Regex 去重去幻觉 | 无 | AI 驱动（最好） | 不错 |
| AI 功能 | 无（刻意不加） | 无 | 自动补全、问答 | 无 |
| 历史记录 | 7 天 JSONL | 无 | 有 | 无 |
| 开源 | 是 | 否 | 否 | 否 |

## 系统要求

- **macOS 13+**（Ventura 及以上）
- **Apple Silicon**（M1 / M2 / M3 / M4）
- **Python 3.10+**（推荐 conda）
- **~1.5 GB** 磁盘空间（首次运行自动下载 Whisper 模型）

## 安装

### 1. 配置 Python 环境

```bash
conda create -n voice python=3.10 -y
conda activate voice
pip install -r requirements.txt
```

不用 conda 也行：
```bash
pip3 install -r requirements.txt
```

### 2. 构建 macOS App

```bash
python setup_whisper_app.py
```

会在 `~/Applications/WhisperDictate.app` 生成独立应用。

如果 Python 不在 conda `voice` 环境：
```bash
WHISPER_PYTHON=/path/to/python3 python setup_whisper_app.py
```

### 3. 系统权限设置

1. **系统设置 → 键盘 → "按下🌐键时"** → 选 **不执行任何操作**
2. **系统设置 → 隐私与安全性 → 辅助功能** → 添加 WhisperDictate.app
3. **系统设置 → 隐私与安全性 → 麦克风** → 允许 WhisperDictate.app
4. （可选）**系统设置 → 通用 → 登录项** → 添加 WhisperDictate.app 开机自启

### 4. 启动

```bash
open ~/Applications/WhisperDictate.app
```

首次启动会下载 Whisper 模型（~1.5 GB）。浮动条显示 `· ┄┄┄...` 表示加载中，变为 `◦ ──────────────` 表示就绪。

## 使用

### 语音输入

1. **按住 FN** — 浮动条显示 `♪` 和实时音量指示
2. **说话** — 中文、英文、混合都行
3. **松开 FN** — 浮动条显示 `✎`，2-3 秒完成转录
4. 文本自动粘贴到当前光标位置

### 右键菜单

右键点击浮动条：
- **Edit Keywords** — 编辑关键词文件
- **Open History** — 查看转录历史
- **Open Log** — 查看运行日志
- **Input Device** — 切换麦克风（连接外接显示器/耳机时常用）
- **Quit** — 退出

### 关键词管理

编辑 `~/.config/whisper/keywords.txt`，逗号分隔。加入你工作中常用的术语：

```
NVIDIA, Tesla, S&P 500, Bitcoin, 仓位, 逆回购, 你的自定义术语
```

每次转录自动重新加载，无需重启。

### 命令行控制（可选）

```bash
./whisper_ctl.sh status    # 查看进程状态和内存
./whisper_ctl.sh log       # 查看日志
./whisper_ctl.sh mic       # 查看/切换麦克风
./whisper_ctl.sh restart   # 重启
./whisper_ctl.sh quit      # 退出
```

## 致谢

底部浮动指示条的 UI 设计灵感来自 **[Typeless](https://typeless.so/)**，感谢他们做出了很好的产品。

基于以下开源项目构建：

- **[OpenAI Whisper](https://github.com/openai/whisper)** — 原始语音识别模型
- **[MLX](https://github.com/ml-explore/mlx)** (Apple) — Apple Silicon 机器学习框架
- **[mlx-whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper)** — MLX 优化的 Whisper 推理
- **[PyObjC](https://github.com/ronaldoussoren/pyobjc)** — Python ↔ Objective-C 桥接
- **[sounddevice](https://github.com/spatialaudio/python-sounddevice)** / [PortAudio](http://www.portaudio.com/) — 跨平台音频 I/O
- **[SoundFile](https://github.com/bastibe/python-soundfile)** / [libsndfile](https://github.com/libsndfile/libsndfile) — 音频文件读写
- **[NumPy](https://numpy.org/)** — 数组处理

## License

MIT
