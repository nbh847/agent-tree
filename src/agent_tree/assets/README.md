# 侧栏图标

运行资源为 32 × 48 PNG（图案 32 × 32，上下各八像素背景留白），仅用于识别当前会话种类；程序加载本地资源，不在运行时联网或处理图片。

- `codex.png`：按用户提供的 OpenAI 结形图标参考，取本机 ChatGPT 应用的 `/Applications/ChatGPT.app/Contents/Resources/electron.icns`，经 macOS `sips` 提取 PNG 后缩小。它是 OpenAI／ChatGPT 图形，用户指定用于 Codex 条目，不代表 Codex 当前独立应用图标。图形归 OpenAI 所有。
- `claude_code.png`：Claude 官方网站图标，2026-10-05 从 [官方图标资源](https://assets.claude.com/95a868946ac8a31e5ff832e2899f294aa368b836.png?w=32&h=32) 获取。图形归 Anthropic 所有。
- `shell.png`：本项目绘制的终端窗口与 `>_` 图形，适用项目许可证。
- `codebuddy.png`：采用用户于 2026-10-05 提供并指定用于 CodeBuddy 的绿色像素机器人参考图；经 imagegen 调整为侧栏深色背景，再用 macOS `sips` 裁去外部留白、按原有宽高比例缩小并居中置于 32 × 48 画布。来源为用户提供的图片，不将其描述为官网 favicon。

- `pi.png`：2026-10-05 获取 [Pi 官网 SVG](https://pi.dev/logo.svg) ，保留原始三色几何路径与颜色，栅格化为 32 × 32 后置于 32 × 48 深色画布中央。图形归 Pi／Earendil 品牌所有。

资源处理范围见各图标来源说明；生成阶段使用临时图像工具，未增加运行时依赖。保留品牌归属，不将品牌图形作为项目自身标识。
