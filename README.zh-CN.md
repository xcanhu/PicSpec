# PicSpec

**把你想要的画面效果写下来一次，之后每个生图模型都照做，每条要求都能核对。**

[English](README.md)

你清楚自己要什么效果：带一点胶片颗粒，人脸要清晰，人物朝左走，绝不要塑料感皮肤。现在你每次都得把这些重新写进提示词，模型还是会漏掉一半。PicSpec 把这些偏好存进一个文件 `PICSPEC.md`，每条偏好都是一条能用“是或否”核对的规则。出图时它按每个模型最容易理解的方式把规则加进提示词，商业模型（gpt-image-2）和本地模型（ComfyUI）都支持。全程不训练、不微调任何模型。

```markdown
# 我的出图规格

自然光纪实人像，35mm 胶片质感。

## 画面质感
- `t1` 全画面带轻微的胶片颗粒，没有数码的平滑感
  - 核对：画面里是否能看到均匀的细颗粒？
- `t2` 人物面部清晰，眼睛对焦准确
  - 核对：人物的眼睛和面部是否清晰锐利、没有发糊？
  - 适用：画面中有人物

## 主体与构图
- `c1` 人物面向或走向画面左侧
  - 核对：人物是否面向或走向画面左侧？
  - 参考图：refs/pose-left.jpg | 身体朝向参考这张

## 禁忌
- `f1` 过度磨皮、塑料感的皮肤
  - 核对：皮肤是否显得过度磨皮或有塑料感？
  - 期望：否
```

> **状态：v0.1，早期版本。** 规格文件格式、统一的后端接口、gpt-image-2 和 ComfyUI 两个适配器、命令行工具现在可用。“逐条核对出图”和“从你的意见里学规则”是接下来要做的，见[路线图](#路线图)。gpt-image-2 适配器目前只用本地模拟的接口测试过，还没有对真实服务跑过。

## 安装

```bash
git clone https://github.com/xcanhu/PicSpec && cd PicSpec
pip install -e .
```

需要 Python 3.10 或更新版本，唯一的依赖是 Pillow。

## 快速开始

```bash
picspec init --lang zh             # 生成一份中文的 PICSPEC.md 模板
picspec lint                       # 列出所有规则，报告文件里的错误
picspec compile "雨后的小巷里，一位撑伞的年轻女子"     # 只显示将要发给模型的内容，不调用任何接口

export OPENAI_API_KEY=sk-...       # Windows 命令行用 set OPENAI_API_KEY=sk-...
picspec generate "雨后的小巷里，一位撑伞的年轻女子" --baseline -n 2
```

`generate` 会把图片和一份 `run.json` 记录写到 `picspec-out/<时间>/`。加上 `--baseline` 会用原始提示词再出一张，方便左右对比。

| 命令 | 作用 |
| --- | --- |
| `picspec init [路径]` | 生成 `PICSPEC.md` 模板 |
| `picspec lint [规格文件]` | 列出每条规则和它的核对问题，按行号报告错误 |
| `picspec fmt [规格文件]` | 把文件整理成标准排版，并给每条规则补上编号 |
| `picspec compile "提示词"` | 显示某个后端实际会收到的提示词、反向提示词和参考图 |
| `picspec generate "提示词"` | 按规格出图 |

`compile` 和 `generate` 可以用 `--only t1,c1`、`--skip f2` 选择规则，用 `--size 1536x1024`、`--quality high` 调整尺寸和质量，用 `--spec 文件` 指定规格文件。不指定时使用当前文件夹或最近的上级文件夹里的 `PICSPEC.md`，所以一份规格可以管一整个项目。

## 后端

| 后端 | 怎么选 | 参考图 | 反向提示词 | 种子 |
| --- | --- | --- | --- | --- |
| gpt-image-2（默认） | `--backend gpt-image-2` | 最多 16 张 | 不支持 | 不支持 |
| 任何兼容 OpenAI 图片接口的模型 | `--backend 模型名 --base-url 地址` | 最多 16 张 | 不支持 | 不支持 |
| ComfyUI（本地） | `--workflow workflow_api.json` | 暂不支持 | 工作流里有 `%negative%` 时支持 | 工作流里有 `%seed%` 时支持 |
| mock | `--backend mock` | 4 张 | 支持 | 支持 |

**gpt-image-2。** 密钥来自 `--api-key`、`PICSPEC_OPENAI_API_KEY` 或 `OPENAI_API_KEY`；地址来自 `--base-url`、`PICSPEC_OPENAI_BASE_URL` 或 `OPENAI_BASE_URL`，所以中转网关也能用。用到的规则带参考图时，请求会走编辑接口并附上图片，提示词里会写明每张图只参考哪一方面。尺寸在发送前先检查：宽高都能被 16 整除，宽高比在 1:3 到 3:1 之间，最大 3840x2160。

**ComfyUI。** 启动 ComfyUI，用“Save (API Format)”导出工作流，在对应位置填上占位符 `%prompt%`，以及可选的 `%negative%`、`%seed%`、`%width%`、`%height%`。[examples/comfyui](examples/comfyui) 里有 8GB 显卡能跑的 Qwen-Image GGUF 工作流。地址默认是 `http://127.0.0.1:8188`，可以用 `--base-url` 或 `PICSPEC_COMFYUI_URL` 修改。发给本地模型的规则会合并成一段普通的描述，因为它们的文本编码器读整段话比读列表更好。示例里的两个工作流为了提速把 CFG 设成了 1，这种设置下反向提示词不起作用。

**mock** 只画一张纯色图，用来在没有密钥和显卡的情况下试用各个命令。

## PICSPEC.md 的格式

规格文件就是普通的 Markdown，在 GitHub 上能直接阅读，手工编辑也方便。

- **设置**（可选）写在文件开头的两行 `---` 之间：`size`、`quality`、`backend`、`lang`（`zh` 或 `en`）。
- **标题下面的那段话**是整体风格，每次出图都会带上。
- **每个 `##` 小节**是一组规则，小节标题决定规则的类型：标题里有“质感、画质、光、色”的是画面质感；有“主体、构图、姿态、动作”的是主体与构图；有“禁忌、禁止、不要、避免”的是禁忌。其他标题是普通小节。
- **每个一级列表项是一条规则。** 开头反引号里的是规则编号，可以不写，`picspec fmt` 会自动补上。
- **缩进的列表项是这条规则的字段：**

| 字段 | 含义 | 不写时 |
| --- | --- | --- |
| `核对` (`check`) | 针对成品图的一个是非题，用来判断这条规则有没有做到 | 用规则原文生成一个通用问题 |
| `期望` (`expect`) | 哪个回答算“做到了”：`是` 或 `否` | `是` |
| `级别` (`level`) | `必须`，或者 `尽量`（锦上添花的规则） | `必须` |
| `适用` (`when`) | 规则在什么情况下适用，比如“画面中有人物” | 总是适用 |
| `提示词` (`prompt`) | 发给模型时用的说法，代替规则原文 | 用规则原文 |
| `反向` (`negative`) | 写进反向提示词的词，只对支持反向提示词的后端有效 | 无 |
| `参考图` (`ref`) | 一张参考图，写成 `路径 \| 参考它的哪一方面`。多张图就写多行 | 无 |
| `类型` (`kind`) | 不按标题、单独指定类型：`质感`、`构图`、`禁忌`、`其他` | 按标题 |

禁忌小节里的规则直接写不想要的东西本身（比如“文字、水印或标志”），核对问题问“是否出现”，期望填“否”。写反了 `picspec lint` 会提醒。

字段名中英文都可以用，冒号全角半角都可以。注释、引用和代码块会原样保留，不会被当成规则。完整的示例见 [examples](examples)。

## 在 Python 里使用

```python
from picspec import load, build_request
from picspec.backends import make_backend

spec = load("PICSPEC.md")
request = build_request(spec, "雨后的小巷里，一位撑伞的年轻女子")
backend = make_backend("gpt-image-2")
print(backend.render(request).prompt)      # 将要发送的内容
result = backend.generate(request)
result.image.save("out.png")
```

一个后端就是一个很小的类：声明自己支持什么（参考图、反向提示词、种子），在 `render` 里把请求翻译成自己模型习惯的说法，在 `_run` 里出图。见 [src/picspec/backends](src/picspec/backends)。

## 路线图

1. **规格文件与适配器。** v0.1 已完成，就是当前版本。
2. **逐条核对与定向重试。** 视觉模型针对成品图逐条回答规则的核对问题，下一次只强调没做到的那几条。
3. **从反馈学规则。** 你说一句“人脸太糊”，PicSpec 提出一条新规则或修改已有规则，由你确认后写回文件。
4. **更多用法。** MCP 服务、ComfyUI 节点、本地模型的参考图、前后对比图集。
5. **评测基准。** 测各个生图模型对颗粒、清晰度、动作方向这类细粒度效果指令的服从程度。

## 许可

Apache-2.0
