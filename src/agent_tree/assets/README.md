# 侧栏图标

会话图标资源为 32 × 48 PNG（图案 32 × 32，上下各八像素背景留白），仅用于识别当前会话种类；程序加载本地资源，不在运行时联网或处理图片。

顶部资源另有 `logo.png`：用户于 2026-10-14 指定采用参考截图中的蓝色箭头／方块与白色 One。通过 macOS AppKit 的矢量路径和系统字形重新绘制为 640 × 160 透明 PNG，没有裁取截图像素；保持参考名称，不代表项目改名或官方品牌关系。使用单独的 24 列 × 3 行虚拟画布与缓存 ID，正文会话图标保持原资源。资源生成不增加运行时依赖。

Logo 的大图分块与列编码依据 [Kitty Graphics 传输规则](https://sw.kovidgoyal.net/kitty/graphics-protocol/#remote-client) 和 [官方列组合标记表](https://github.com/kovidgoyal/kitty/blob/master/gen/rowcolumn-diacritics.txt) ：每块 Base64 最多 4096 字符，前 24 项列标记支持顶部画布，会话图标使用两列位置标记。

`folder.png` 与 `branch.png` 是按用户参考形态以矢量路径重新绘制的 32 × 32 透明 RGBA：灰蓝文件夹轮廓与粉色分叉节点。各使用两列 × 一行虚拟画布，分配独立缓存 ID，避免依赖终端字体的近似字形。会话 PNG 文件保持原样，直接展示完整源图，不使用来源裁取参数，缩为两列 × 一行并与名称同行；上方树干与下方信息树枝不放置会话图片。

- `codex.png`：按用户提供的 OpenAI 结形图标参考，取本机 ChatGPT 应用的 `/Applications/ChatGPT.app/Contents/Resources/electron.icns`，经 macOS `sips` 提取 PNG 后缩小。它是 OpenAI／ChatGPT 图形，用户指定用于 Codex 条目，不代表 Codex 当前独立应用图标。图形归 OpenAI 所有。
- `claude_code.png`：Claude 官方网站图标，2026-10-05 从 [官方图标资源](https://assets.claude.com/95a868946ac8a31e5ff832e2899f294aa368b836.png?w=32&h=32) 获取。图形归 Anthropic 所有。
- `shell.png`：本项目绘制的终端窗口与 `>_` 图形，适用项目许可证。
- `codebuddy.png`：采用用户于 2026-10-05 提供并指定用于 CodeBuddy 的绿色像素机器人参考图；经 imagegen 调整为侧栏深色背景，再用 macOS `sips` 裁去外部留白、按原有宽高比例缩小并居中置于 32 × 48 画布。来源为用户提供的图片，不将其描述为官网 favicon。

- `pi.png`：2026-10-05 获取 [Pi 官网 SVG](https://pi.dev/logo.svg) ，保留原始三色几何路径与颜色，栅格化为 32 × 32 后置于 32 × 48 深色画布中央。图形归 Pi／Earendil 品牌所有。

资源处理范围见各图标来源说明；生成阶段使用临时图像工具，未增加运行时依赖。保留品牌归属，不将品牌图形作为项目自身标识。

`card-left.png` 与 `card-right.png` 为 AppKit 原生路径绘制的 16 × 108 透明 RGBA，分别对应选中条目的左／右一列 × 三行画布；左侧包含连续蓝色竖线，右侧圆角避开终端最后一列。资源只绘制空白边缘，正文与树线仍由 Textual 渲染；不修改用户字体或宿主配置。
