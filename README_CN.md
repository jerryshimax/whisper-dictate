# WhisperDictate

macOS 本地语音输入工具 — 按住快捷键说话，松开自动转文字粘贴。完全本地运行，不联网。

两个语音引擎可选：[MLX Whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper)（Apple Silicon 原生加速）和 [FunASR Paraformer](https://github.com/modelscope/FunASR)（中英混合最快）。右键菜单切换，不用重启。

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

| | WhisperDictate | macOS 听写 | Typeless | 微信语音输入 |
|---|---|---|---|---|
| 隐私 | 纯本地 | 云端 (Apple) | 云/本地 | 云端 (腾讯) |
| 费用 | 免费 | 免费 | $8-15/月 | 免费 |
| 速度 | 1-3 秒 | 快 | 快 | 快 |
| 中英混合 | 好 | 一般 | 好 | 一般 |
| 开源 | 是 | 否 | 否 | 否 |

## 安装教程

需要：macOS 13+、Apple Silicon (M1/M2/M3/M4)、Python 3.10+

### 第一步：下载代码

```bash
git clone https://github.com/jerryshimax/whisper-dictate.git
cd whisper-dictate
```

### 第二步：安装依赖

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

这一步会下载 PyTorch 等依赖，大概需要几分钟。

### 第三步：构建 App

```bash
.venv/bin/python setup_whisper_app.py
```

会在 `~/Applications/` 下生成 `WhisperDictate.app`。

### 第四步：设置系统权限

这一步很重要，不设的话按键监听和麦克风都不工作：

1. **系统设置 → 键盘 → "按下🌐键时"** → 选 **不执行任何操作**
2. **系统设置 → 隐私与安全性 → 辅助功能** → 把 WhisperDictate.app 加进去
3. **系统设置 → 隐私与安全性 → 麦克风** → 允许 WhisperDictate.app
4. （可选）**系统设置 → 通用 → 登录项** → 加上 WhisperDictate.app 开机自启

### 第五步：启动

```bash
open ~/Applications/WhisperDictate.app
```

第一次启动会下载模型（~1.5 GB），屏幕底部会出现一个小浮动条，显示 loading 状态。等变成 `◦ dictate` 就可以用了。

## 怎么用

### 基本操作

1. **按住 Ctrl+Option** — 浮动条展开，显示实时音波动画
2. **说话** — 中文英文随便说
3. **松开** — 音波变成闪烁动画（正在识别），1-3 秒后文字自动粘贴到光标

如果录音过程中你切了窗口，不会自动粘贴，而是显示一个 Copy 按钮，手动点一下。

### 切换语音引擎

右键点浮动条 → **ASR Backend**：

| 引擎 | 适合 | 速度 | 模型大小 |
|------|------|------|---------|
| **Whisper (MLX)** | 纯英文、生僻词 | 1-3 秒 | 1.5 GB |
| **Paraformer (FunASR)** | 中文、中英混合 | 0.5-1 秒 | 300 MB |

切换后会在后台加载新模型，浮动条显示 loading，加载完自动切换。

### 关键词提示

编辑 `~/.config/whisper/keywords.txt`，加入你常用的专有名词（逗号分隔）：

```
NVIDIA, Tesla, S&P 500, Bitcoin, 你的术语
```

关键词能显著提升专有名词的识别准确率，每次录音自动加载，不用重启。

### 右键菜单

右键点浮动条可以：
- **Edit Keywords** — 编辑关键词
- **Open History** — 看转录历史
- **Open Log** — 看运行日志
- **Input Device** — 切麦克风（接了外接显示器/耳机的时候有用）
- **ASR Backend** — 切语音引擎
- **Quit** — 退出

## 常见问题

**Q: 按 Ctrl+Option 没反应？**
→ 检查辅助功能权限有没有给 WhisperDictate.app

**Q: 浮动条一直显示 loading？**
→ 第一次需要下载模型，等几分钟。看日志：`~/.config/whisper/app.log`

**Q: 识别结果不准？**
→ 把常用术语加到 keywords.txt，会好很多

**Q: 内存占用高？**
→ 正常，Whisper 模型大约 1.5 GB。App 会自动在内存过高时重启

**Q: 怎么卸载？**
→ 删掉 `~/Applications/WhisperDictate.app` 和 `~/.config/whisper/` 就行

## 致谢

UI 设计灵感来自 [Typeless](https://typeless.so/)。

基于以下开源项目：
- [OpenAI Whisper](https://github.com/openai/whisper) — 语音识别模型
- [MLX](https://github.com/ml-explore/mlx) — Apple Silicon 机器学习框架
- [FunASR](https://github.com/modelscope/FunASR) — 阿里达摩院语音识别
- [PyObjC](https://github.com/ronaldoussoren/pyobjc) — Python ↔ Cocoa 桥接

## License

MIT
