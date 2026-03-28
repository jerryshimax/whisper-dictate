# WhisperDictate

macOS 本地语音输入工具 — 按住快捷键说话，松开自动转文字粘贴。完全本地运行，不联网，不要钱。

基于 [MLX Whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper)（Apple Silicon 原生加速），内置 LLM 自动修正标点符号。

## 30 秒了解

1. 屏幕底部有一个小浮动条
2. 按住 **Ctrl+Option** 说话，浮动条会显示实时音波动画
3. 松开，1-3 秒出文字，自动粘贴到光标位置
4. 中文、英文、中英混合都行，一句话里随便切

## 为什么用这个？

- **免费 + 纯本地** — 不要钱，不上云，音频不离开你的电脑
- **只做输入** — 不自动补全，不回答问题，你说什么它打什么
- **中英混合强** — "帮我看下 NVIDIA 的 Q3 earnings" 直接出对的
- **开源可改** — Python 写的，想改就改

| | WhisperDictate | macOS 听写 | 商业方案 | 微信语音输入 |
|---|---|---|---|---|
| 隐私 | 纯本地 | 云端 (Apple) | 看产品 | 云端 (腾讯) |
| 费用 | 免费 | 免费 | $8-15/月 | 免费 |
| 速度 | 1-3 秒 | 快 | 快 | 快 |
| 中英混合 | 好 | 一般 | 好 | 一般 |
| 开源 | 是 | 否 | 否 | 否 |

## 功能列表

- **两种输入模式**：
  - **按住说话** — 按住 Ctrl+Option 说话，松开自动转文字
  - **点击切换** — 快速点一下开始录音，再点一下停止（可以放开双手）
- **LLM 标点修正** — 本地 Qwen2.5-0.5B 自动修正标点、大小写（~0.15 秒）
- **知识库关键词** — 自动扫描 Obsidian 笔记库中的人名、公司名、中文术语，提升识别准确率
- **实时音波动画** — 录音时显示动态波形，转录时闪烁动画
- **声音提示** — 开始录音 Tink 一声，转录完成 Ping 一声，不用盯着屏幕
- **中英混合** — 一句话里中英文随便切换
- **智能后处理** — 自动去除幻觉文本、重复、语气词、碎片逗号
- **自定义关键词** — 手动添加专业术语提升识别率
- **窗口检测** — 同一窗口自动粘贴，切了窗口显示 Copy 按钮
- **右键菜单** — 切麦克风、编辑关键词、查看日志
- **转录历史** — JSONL 格式，7 天自动清理
- **内存管理** — 自动清理，内存过高时自动重启

## 系统要求

- **macOS 13+**（Ventura 或更新）
- **Apple Silicon**（M1 / M2 / M3 / M4）
- **Python 3.10+**
- **~1.5 GB** 硬盘空间（Whisper 模型，首次运行自动下载）
- **~400 MB**（LLM 标点模型，首次运行自动下载）

## 安装教程

### 方式 A：从源码运行（推荐开发者）

```bash
# 1. 下载代码
git clone https://github.com/jerryshimax/whisper-dictate.git
cd whisper-dictate

# 2. 创建虚拟环境并安装依赖
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. 设置系统权限（见下方）

# 4. 启动
python -m whisper_dictate
```

### 方式 B：构建 macOS App

```bash
# 下载代码并安装依赖后：
bash build_dmg.sh
```

会在 `~/Applications/` 下生成 `WhisperDictate.app`，双击即可运行，不需要 Python 环境。

### 设置系统权限

这一步很重要，不设的话按键监听和麦克风都不工作：

1. **系统设置 > 隐私与安全性 > 辅助功能** — 把 WhisperDictate（或终端）加进去
2. **系统设置 > 隐私与安全性 > 麦克风** — 允许 WhisperDictate（或终端）
3. （可选）**系统设置 > 通用 > 登录项** — 加上开机自启

### 首次启动

第一次启动会下载 Whisper 模型（~1.5 GB）和 LLM 模型（~400 MB），屏幕底部会出现一个小浮动条。等变成 `○` 就可以用了。

## 怎么用

### 按住说话（默认模式）

1. **按住 Ctrl+Option** — 浮动条展开，显示音波动画，Tink 一声
2. **说话** — 中文英文随便说
3. **松开** — 音波闪烁（正在识别），Ping 一声表示完成
4. 文字自动粘贴到光标位置

### 点击切换（解放双手）

1. **快速点一下 Ctrl+Option**（< 0.6 秒）— 开始录音，听到两声 Tink
2. **说话** — 想说多久说多久，双手可以做别的
3. **再快速点一下 Ctrl+Option** — 停止录音，转录，Ping 一声完成

如果录音过程中你切了窗口，不会自动粘贴，而是显示一个 Copy 按钮，手动点一下。

### 关键词提示

编辑 `~/.config/whisper/keywords.txt`，加入你常用的专有名词：

```
# 用自然语言句子效果最好，Whisper 会学习语言风格
Synergis Capital tracks ARR and valuation multiples.
你的术语, 人名, 公司名
```

如果你有 Obsidian 笔记库在 `~/Work/[00] Brain/`，WhisperDictate 会自动扫描里面的人名、公司名和中文术语，不用手动添加。

### 右键菜单

右键点浮动条：
- **Edit Keywords** — 编辑关键词
- **Open History** — 看转录历史
- **Open Log** — 看运行日志
- **Input Device** — 切麦克风
- **Quit** — 退出

### 命令行

```bash
# 从源码运行
pkill -f whisper_dictate
cd ~/Ship/dictation && source .venv/bin/activate && python -m whisper_dictate &

# 或者运行 App
open ~/Applications/WhisperDictate.app
```

## 配置文件

| 文件 | 用途 |
|------|------|
| `~/.config/whisper/keywords.txt` | Whisper 关键词提示 |
| `~/.config/whisper/config.json` | 设置（麦克风、模型等） |
| `~/.config/whisper/history.jsonl` | 转录历史（7 天自动清理） |
| `~/.config/whisper/app.log` | 运行日志（5 MB 自动轮换） |

所有配置文件权限为 0600（仅所有者可读写）。

## 常见问题

**Q: 按 Ctrl+Option 没反应？**
检查辅助功能权限有没有给 WhisperDictate 或终端。

**Q: 浮动条一直显示加载中？**
第一次需要下载模型，等几分钟。看日志：`~/.config/whisper/app.log`

**Q: 识别结果不准？**
把常用术语加到 keywords.txt，会好很多。LLM 会自动修正标点和大小写。

**Q: 内存占用高？**
正常，Whisper 模型大约 1.5 GB。App 会自动在内存过高时重启。

**Q: 怎么卸载？**
删掉 `~/Applications/WhisperDictate.app` 和 `~/.config/whisper/` 就行。

## 基于以下开源项目

- [OpenAI Whisper](https://github.com/openai/whisper) — 语音识别模型
- [MLX](https://github.com/ml-explore/mlx) — Apple Silicon 机器学习框架
- [MLX-LM](https://github.com/ml-explore/mlx-examples/tree/main/llms) — 本地 LLM 推理
- [PyObjC](https://github.com/ronaldoussoren/pyobjc) — Python-Cocoa 桥接
- [sounddevice](https://github.com/spatialaudio/python-sounddevice) / [PortAudio](http://www.portaudio.com/)

## License

MIT
