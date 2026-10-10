# agent-tree

为运行 tmux 的终端提供 Agent 会话侧栏，将同一目录下的会话聚合起来，显示 Agent 名称、图标、执行状态，并支持定位到对应终端。

已确定采用 tmux 专用 pane 内的 TUI 侧栏，不使用宿主原生侧栏。当前处于源码实施阶段：参考调研、设计文档与本地 Git 初始化已完成，Goal 1 的检查点 1、2、3 均已完成。技术栈为 Python 3.14，界面层用 textual，其余模块仅用标准库；侧栏保持方式为迁移单个自建侧栏。

已实现：在当前 window 左侧创建自建侧栏 pane；按 tmux server／socket 列出当前附着会话的 pane，普通 shell 也计入；detached pane 中当前进程树仍有非 shell 程序（含 Claude Code／Codex／CodeBuddy／Pi 与普通服务）的也显示，重启侧栏后仍可见，历史启动命令不能单独触发保留；空闲 detached shell 不自动纳入，但本次运行期间曾附着过的会话会继续保留，避免「选走之后原窗口消失」；识别 Claude Code、Codex、CodeBuddy（`codebuddy`／`cbc`／`codebuddy-code`）与 Pi（`pi`）；按 **Git 仓库根目录**分组（不在仓库内时退回工作目录），因此同一仓库下不同子目录的会话聚在一起；暗色主题下以方括号目录名、树形连接线 `├─`／`└─`、普通正文色的会话名称与低调的选中背景块呈现；上下键只在子会话行间移动高亮、跳过路径根节点，Enter／鼠标点击／`→`／`Esc` 进入目标 pane；跟随启动终端的 tmux 原生 window／session 切换，同步高亮当前 pane、展开所在分组并滚动到对应行；在目录下一键新建会话（路径行右侧 `[+]` 按钮或 `n`）；侧栏旁的会话全部关闭（如 shell 退出）时自动补位到同目录分组的第一个会话、否则整个列表的第一个，列表为空则自动退出；退出或崩溃只清理自建侧栏 pane。首次扫描完成前先显示「正在扫描会话…」占位帧。

图标已接入（名称右侧、垂直居中）：支持 Kitty Graphics 图片位置标记的 iTerm2 中，Codex、Claude Code、CodeBuddy、Pi、Shell 使用本地 PNG；五种图片每次启动各上传一次，由 tmux 保存位置标记，鼠标悬停、两侧 pane 焦点切换、滚动和跨窗口迁移不重新上传图片。未知身份显示 `?`，其他终端或图片输出暂停时使用 `O`／`C`／`B`／`P`／`$` 字符标识，名称始终保留。Codex 按用户指定使用 OpenAI 结形图标。图片透传只在自建侧栏 pane 上启用，不修改窗口或全局设置，不新增运行时依赖。

执行状态以图标右侧的小圆点显示，与名称垂直居中，间隔一列：蓝点每 0.6 秒明暗交替表示进行中，黄点表示等待操作，绿点表示空闲，灰点表示未知；其余状态点保持静态；普通 Shell 不显示状态点。窄栏为状态点预留两列，过窄时优先名称。Codex、Claude Code、CodeBuddy 按当前输入区的运行指示、选择框与就绪输入框识别；Pi 目前只识别明确带中断提示的运行状态，其余回退未知。空闲表示可以接收下一条输入，包括初始就绪、结束或中断后的输入框，不承诺任务成功完成。默认每 2 秒重新采样；不读取滚动历史、不修改 Agent 配置或安装 hook，复制／历史查看模式、采样失败与未匹配信号立即回退未知。仅按进程树确认仍存活的 Agent 读取屏幕，文本不落盘。

## 运行

需要 Python 3.13+、tmux，以及界面依赖 `textual`（已装在项目内 `.venv`）。侧栏默认占窗口宽度的 24%，可用 `--width` 指定其他宽度。界面采用近黑底色、疏朗树线和蓝色选中竖线；窄屏下优先保留项目名，空间不足时隐藏父路径。

图片目前使用 Kitty Graphics 协议的 Unicode 图片位置标记和 tmux 的 pane 级 `allow-passthrough`；本机 iTerm2 3.7.3／tmux 3.7c 已验证协议路径。窗口缩放（zoom）、client 裁剪窗口或侧栏不可见时停止发送图片并回退字符；不足 13 列时优先保留名称。更新代码后，已有侧栏需按 `q` 退出，再运行 `bin/agent-tree` 加载新版本。

```bash
# 首次准备（已就绪则跳过）
python3 -m venv .venv && .venv/bin/pip install textual

# 免安装启动脚本：优先使用 .venv/bin/python，自动设置 PYTHONPATH
bin/agent-tree

# 指定宽度与 tmux socket
bin/agent-tree --width 35% --socket <socket 名>

# 一次性打印聚合树：不依赖终端，也不需要 textual
PYTHONPATH=src python3 -m agent_tree --snapshot
```

侧栏键位：`↑`／`↓`（或 `j`／`k`）只在子会话行间移动高亮，跳过路径根节点，**不会打断你当前的视图**；`Enter`（或鼠标点击）**进入选中会话**--切换视图并把输入焦点交给目标 pane；`n` 在选中行所属目录下新建一个 session（默认 shell）；点击路径行右侧的 `[+]` 可直接在该目录下新建，无需先用快捷键回到侧栏；`空格` 展开／折叠目录；`→`／`Esc` 与 `Enter` 等价；`q` 退出侧栏。回到侧栏用 tmux 默认的 `last-pane`（`prefix + ;`）。原生切窗跟随每 0.25 秒检查一次，列表发现默认每 2 秒刷新；只跟随启动它的终端，其他终端不会抢走侧栏。目标窗口不足 60 列或已有另一个侧栏时不迁入。

进入其他 session 的会话时会执行 tmux `switch-client`：**你发起操作的那个终端会跟着切到目标 session**，原 session 变为 detached。一个 tmux client 同一时刻只能看一个 session，所以跳转多次后可能出现两个终端停在同一个 session 上，此时侧栏对该 session 只列一条——两边看的是同一个窗口。

**退出侧栏（`q`）时会把被带走的终端送回它原来的 session**，所以各标签页会回到各自初始的 session，不会出现「退出后某个窗口的 session 一直空着、重启侧栏就少一条」。若你在侧栏仍开着时自己又切换过该终端，则不再干预。

侧栏导航将迁移、切窗和焦点设置一次提交到 tmux 命令队列，减少分步调用的中间画面；目标 pane 的尺寸变化仍可能触发程序重绘。原生快捷键切窗仍由每 0.25 秒的检查跟随。

会话扫描在后台执行，同一实例最多一轮扫描在途，扫描缓慢时仍可操作列表或按 `q` 退出；tmux 命令与进程查询各有 2 秒超时。扫描失败保留当前列表并提示错误，后续刷新可恢复。导航到已有其他侧栏的窗口时会拒绝迁入并提示，避免重开后的双侧栏叠加；已有实例需要退出后才能加载新版。

侧栏所在窗口的宽度或 pane 集合变化时，按 `--width` 校正自建侧栏宽度，避免关闭相邻 pane 后侧栏占据多余空间；同一布局下手动拖动的宽度保留，zoom 期间不调整。

在 macOS 的 iTerm2 中，后台每 5 秒通过系统 AppleScript 查询绑定终端的鼠标报告模式；当终端停止报告、tmux mouse 仍开启且自建侧栏可见时，只向该 client 的 TTY 恢复鼠标协议。正常模式、mouse off、zoom、侧栏不可见或 client 断连时不恢复；不修改持久配置，不向 Shell／Agent 发送输入。脚本访问失败、权限拒绝或查询超时会停用本次运行的自动恢复并在底栏提示，键盘与列表仍可使用；其他宿主不启用此检查。

退出侧栏只关闭自建 pane：用户进程与布局保留，未被你改动过的布局自动还原，已改动过的布局保持你的新结构。除你按 `n` 或点击 `[+]` 主动新建会话、以及侧栏旁的会话全部关闭时的自动补位迁移外，侧栏不创建、迁移、关闭或重启你的 pane，也不向其发送输入，且不修改 tmux 全局配置与快捷键。

## 测试

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -t tests     # 含 textual 界面用例
AGENT_TREE_RUN_TMUX_TESTS=1 PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -t tests
```

## 文档入口

- [Goal 1 施工清单](/Users/mac/workspace/agent-tree/goals/20261004-1321-tmux-sidebar-mvp.md) ：tmux 原型与基础侧栏的施工计划与执行记录。

- [产品设计](/Users/mac/workspace/agent-tree/docs/product-design.md) ：使用场景、界面结构与功能边界。
- [架构文档](/Users/mac/workspace/agent-tree/docs/architecture.md) ：tmux 集成、目录聚合和状态来源。
- [参考调研](/Users/mac/workspace/agent-tree/docs/reference-review.md) ：参考仓库证据与借鉴判断。
- [验证记录](/Users/mac/workspace/agent-tree/docs/validation.md) ：宿主与功能验证的环境、结果与未覆盖范围。
- [实施路线图](/Users/mac/workspace/agent-tree/ROADMAP.md) ：下一步与阶段验收。
- [项目规范](/Users/mac/workspace/agent-tree/AGENTS.md) 。

参考项目：[Agents Go](https://github.com/zhangxq0606-ctrl/agents-go) 。本项目目前为独立文档与源码项目，未复制其源码。
