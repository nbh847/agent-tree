# agent-tree 实施路线图

## 当前状态

参考调研与设计文档初版已完成。已确定采用 tmux 专用 pane 内的 TUI 独立侧栏，iTerm2 原生侧栏不在实施范围内。检查点 1 宿主可行性验证已完成，技术栈确定为 Python 3.14 + textual（界面以外仅用标准库，测试用 `unittest`），侧栏保持方式确定为迁移单个自建侧栏（join-pane）。

检查点 2 已完成：`src/agent_tree/` 已实现发现、身份识别、目录树与浏览界面。检查点 3 已完成：默认 `agent-tree` 在当前 window 左侧创建自建侧栏 pane，方向键移动高亮，Enter／鼠标点击／`→`／`Esc` 进入目标 pane；跟随启动 client 的原生 window／session 切换并同步当前条目，退出与崩溃只清理自建 pane。

[Goal 1 施工清单](/Users/mac/workspace/agent-tree/goals/20261004-1321-tmux-sidebar-mvp.md) 于 2026-10-04 启动执行，检查点 1～3 完成，正在做检查点 4 的验收与交付。执行状态识别在基础闭环验收后作为后续 Goal。

## 下一步与检查点

| 阶段 | 工作与交付 | 验收标准 |
| --- | --- | --- |
| 1：宿主可行性（已完成） | 核对本机 tmux 版本；制作隔离的枚举、cwd 与导航原型，形成验证记录 | 已开和新增会话可发现；明确权限／目录缺失边界；导航准确；不破坏既有会话。 |
| 2：基础侧栏（已完成） | 确定技术栈与源码目录，实现按路径分组、Claude Code／Codex 标识和导航 | 同目录多会话聚合、同名异路径隔离、软链接处理、shell 回退、关闭后更新；侧栏退出不结束 Agent。 |
| 3：状态显示 | 收集本地 CLI 版本样本，适配可信事件或实时屏幕规则，加入过期与抗抖 | 执行／空闲／等待确认／未知可区分；历史内容不误报；静默不判完成；乱序和断连降级正确。 |
| 4：宿主完善（部分完成） | TUI 字符标识与可选字体图标；处理窄屏、多 window／session、多 client 与跨 window 侧栏保持 | 图标缺失不影响名称；跨窗口导航可用；无重复条目；只回收自建资源，退出保留用户布局与进程。 |

阶段 1～3 的宿主与导航部分已完成并更新架构决策；窄屏拒绝、多 client 隔离与异常清理已在检查点 3 验证。字符标识已实现，字体图标与执行状态仍待后续。没有真实验收证据的事项保持未完成。

## 未验证范围

- 父子目录与 worktree 不自动合并；该分组规则已由单元与集成测试覆盖，真实终端效果待阶段 3 端到端验收。
- 真实 Claude Code／Codex 身份识别已验证；包装启动（如 `node /path/claude`）仅有离线分支测试。
- 鼠标点击已通过真实 pty client 的 SGR 鼠标协议端到端验证（需要 tmux `mouse` 开启）；用户已确认实际鼠标切换正常。
- socket 断开、导航瞬间目标 pane 被删除的在线时序未做端到端验证。
- 启动窗口被多个 client 同时注视时，初始绑定取最近活跃者；该初始判定策略未在真实共享窗口中验证。绑定后不再按其他 client 的活跃度转移，隔离性已有真实双 client 验证。
- 原生切窗后原侧栏窗口不可见，textual 定时器仍能完成迁移与重绘，已有端到端验证；导航到初始 detached session 的首帧延迟仍未独立测量。
- 未确认字体图标与字符回退效果。
- 上游仅做静态源码核对，没有构建或运行；不继承其验收声明。

## 最近完成

- 2026-10-05 09:01：修复点击路径节点不折叠子会话的问题：路径行点击直接展开／折叠，右侧 `[+]` 保持仅新建，不触发导航。

- 2026-10-05 08:59：路径节点右侧新增 `[+]` 按钮，直接沿用 `n` 的目录新建回调；按钮点击不导航、不折叠，折叠组仍可新建，窄栏保留按钮，未知目录与只读模式不显示。同步项目规则、使用说明与交互文档。

- 2026-10-05 08:59：上下键（含 j／k）只在可见子会话行间移动，跳过路径根节点与折叠内容，首尾停留；保留鼠标路径行操作。同步键位说明，补充跨组、边界、折叠、空树与 Textual 按键回归。

- 2026-10-05 08:52：修复鼠标点击侧栏无法进入会话：Textual 点击事件已是控件局部坐标，删除重复减去控件屏幕位置的计算；保留留白不响应，补充普通点击与滚动后点击回归。

- 2026-10-05 08:46：参考侧边栏截图美化界面：近黑底色、标题与操作条留白、疏朗树线、蓝色选中竖线；窄屏优先保留项目名并按空间隐藏父路径。默认宽度由 30% 缩为 24%，显式宽度参数保持可用；更新说明与默认宽度测试。

- 2026-10-05 08:39：提交 detached Agent 修复，并合并远程独立初始化历史；README 保留当前完整项目说明，远程 MIT LICENSE 原文纳入，双方历史保留，采用正常推送。

- 2026-10-05 08:32：修复 detached Codex／Claude Code 被附着过滤隐藏的问题。发现时先检查当前进程树，存活 Agent 即使 detached、且本次 keep_sessions 为空也显示；普通遗留 shell 与仅有历史 Agent 启动命令的 pane 不自动纳入。172 项完整回归通过，默认 server 只读快照中 agent-tree 同时列出 Codex %0 与 %4。

- 2026-10-05 08:24：将当前文档、源码、启动脚本和测试纳入首次 Git 基线提交，为独立 worktree 开发提供起点；忽略本地虚拟环境、临时产物与真实环境配置，不推送远程。

- 2026-10-05 08:19：实现原生切窗跟随：侧栏绑定启动 client，每 0.25 秒追踪 window／session，用 `join-pane -d` 迁移自建 pane 并保留目标焦点；同步当前 pane 高亮、展开分组与滚动位置，刷新按稳定会话键保留浏览选择。宽度传入侧栏子进程；用户主动跨 session 切换后不还原旧导航起点。目标过窄、已有其他侧栏、失效或 client 断开时不接管其他终端。新增单元、真实 pty／textual 集成及 headless 滚动测试，169 项全部通过。

- 2026-10-05 07:40：新增「旁 shell 关闭后自动补位」。散帅报告：侧栏旁的 shell 执行 `exit` 后侧栏独占整窗。行为（`tui.py` 纯逻辑 + 宿主回调）：刷新时若树里没有侧栏所在 window 的条目（用户 pane 全部关闭），按「被关会话所在路径分组的第一个 → 全列表第一个」自动迁移补位并把焦点交给新 pane（分组取自上一轮树）；列表为空则退出侧栏，pane 关闭后 session 与终端交由 tmux 自然收摊。顺带修一个由补位暴露的导航顺序 bug：侧栏独占原 window 且目标在别的 session 时，先 `switch-client` 再 `join-pane`，否则原 window 因无剩余 pane 被销毁、client 所在 session 随之消亡，client 会被直接断开而非跟去目标 session。离线 154 项通过。

- 2026-10-04 18:56：修「按 `n` 新建 shell 后侧栏变宽」。根因：`new-session -d` 默认按 80x24 建 session，`join-pane -l 30%` 按 80 列算出侧栏宽度，`switch-client` 后窗口放大到 client 实际宽度时 tmux 重排，侧栏被摊宽（178 列窗口下实测 53 → 73 列）。修复：`new_session` 先读侧栏当前窗口尺寸，用 `-x`／`-y` 按该尺寸创建新 session，让 30% 从 join 那一刻就按真实宽度计算。离线测试 142 项通过。

- 2026-10-04 18:25：修「退出侧栏再启动就少一条」的真因。用户猜测正确：跨 session 导航会把发起终端 `switch-client` 到目标 session，但**退出侧栏时不还原**，于是那个终端一直占着别人的 session、它自己原来的 session 一直 detached；而侧栏范围是「只看附着会话」，`keep_sessions` 每次启动又是空集，重启后自然少列一条。修复：`SidebarManager` 记录被借走的 client `(name, 原 session, 带到 session)`，新增 `restore_client()`，在 `--in-pane` 退出流程与 `teardown()` 中调用，把它送回原 session；多次跳转只保留最初起点；若用户自己又切换过则不干预。离线测试 140 项通过。

- 2026-10-04 18:05：修「选中 shell 后按 Enter 进不去」。根因是上一轮把 Enter 的 `focus_target` 留成 False：目标与侧栏在同一个 window 时既不迁移也不换 window，只剩 `select-pane` 指回侧栏，所以毫无反应；而 `→` 会把焦点交给目标 pane 才显得「能进去」。散帅要求 Enter 与 → 一致，据此把两个回调统一为 `open_target`：进入选中会话并把输入焦点交给目标 pane。上一轮为拦跨 session 而加的 `switch_client` 开关、`sidebar_session`、中性 `hint` 一并移除（不再有生产者）。保留同 session 换 window 时的 `select-window` 修复。离线测试 134 项通过。

- 2026-10-04 17:50：修「选中就把用户终端夺走」。经散帅反馈，该拦截属过度设计，18:05 已按「Enter 与 → 一致」的要求回退。

- 2026-10-04 17:35：查清「4 个窗口只显示 3 条」。证据：每个 iTerm2 标签页（profile 启动命令 `tmux new-session`）确实各建了一个 session，且 `session_created` 与对应 client 的 `client_created` 逐一吻合；但 `ttys029`（16:33:02 创建 session 17）现在附着在 `ttys006` 创建的 session 20 上，session 17 变为 detached，即跨 session 导航把发起终端重新绑定了。该现象导致本轮修复。

- 2026-10-04 17:15：分组改为按 **Git 仓库根目录**。散帅指出 `kzz-radar/web` 被显示成 `[web]`，他要的是「某个路径下聚合的所有窗口」，即同一项目下不同子目录合成一组。`grouping.py` 新增 `find_project_root`（逐级向上找 `.git`，纯文件系统判断、不调 `git`）与 `group_key`（仓库根优先，否则退回规范化工作目录）；worktree／submodule 的 `.git` 是文件也算命中，故各自独立；家目录本身不作为仓库根，避免 dotfiles 仓库把所有家目录会话并成一组。真实 server 上 `kzz-radar/web` 已归入 `[kzz-radar]  ~/workspace`。离线测试 133 项通过。

- 2026-10-04 17:00：新增「在选中目录下新建会话」。散帅要求能方便地在某个路径下开新窗口，确认取「新建独立 session + 用选中行所属目录 + 默认 shell」。`SidebarManager.new_session` 用 `new-session -d -c <dir>` 建会话后再复用 `navigate`，因此只迁移自建侧栏 pane 并把 client 一起带过去，不触碰用户既有 pane、也不向新 pane 发送输入；侧栏纯逻辑新增 `on_new_session` 与 `current_directory`，目录未知时拒绝新建并提示。键位 `n`，底部提示按宽度逐级降级。AGENTS.md 的工程边界据此改为「唯一例外：按 `n` 新建 session」。离线测试 127 项通过。

- 2026-10-04 16:45：按散帅选择把交互从「选中即切换」改为「高亮 + Enter 切换」：`↑`／`↓` 只移动高亮，不打断当前视图；`Enter`（或鼠标点击会话）才切换，焦点仍留在侧栏；`→`／`Esc` 切换并交出焦点。删除了方向键里的隐式 `activate_current` 调用，新增 `enter` 绑定与「move 不触发导航」的测试。产品设计与 README 键位说明同步。

- 2026-10-04 16:35：修散帅报告的 bug「选了另一个窗口后原来的窗口没了」。根因是两处设计互相冲突：导航用 `switch-client` 把 client 切到目标 session，原 session 因此变成 detached，而「只看附着会话」的范围过滤随即把它从列表移除。修复：`discover` 新增 `keep_sessions`，记录本次运行期间曾附着过的 session，断开后仍继续显示。真实 server 上确认已断开的 session 10（`[mac]`）重新出现在列表中。离线测试 118 项通过。

- 2026-10-04 16:20：按散帅「可以使用现成 TUI 框架」的指示，界面层由 curses 重写为 textual 8.2.8。`tui.py` 收敛为不依赖界面框架的纯逻辑（行、折叠、选中、刷新、回调），新增 `ui.py` 承载 textual 界面：暗色主题、标题栏/底部操作条面板、目录间留白、方括号目录名、`├─`／`└─` 连接线、按种类着色的名称、铺满整行的低调选中背景块；行按显示列宽截断而非折行。新增项目内 `.venv` 与 `textual` 依赖，`bin/agent-tree` 优先使用它；`--snapshot` 仍只依赖标准库。离线测试 115 项通过。

## 最近验证

- 2026-10-05 09:03：提交前在沙箱外运行独立 socket 完整回归，181 项全部通过，无跳过；覆盖上下键跨组选择、路径点击折叠与新建按钮。`git diff --check` 与受影响文档本地链接检查通过。沙箱内首次运行 9 项集成因 socket 无法建立失败。

- 2026-10-05 09:02：用户确认当前交互可用；提交前独立 socket 完整回归 181 项全部通过，无跳过，覆盖新建按钮、路径点击折叠与上下键跳过路径节点；`git diff --check` 与受影响文档本地链接检查通过。

- 2026-10-05 09:01：181 项离线回归通过，9 项 tmux 集成按默认配置跳过；新增 Textual 实际点击覆盖折叠后隐藏子会话、刷新保留折叠、再次点击展开与不触发导航；已有新建按钮回归通过。未做真实终端点击验收。

- 2026-10-05 08:59：新建按钮 headless Textual 点击回归覆盖对应目录、非按钮区域、折叠组与不触发导航；渲染覆盖窄栏、中文路径及未知目录。沙箱外独立 socket 完整回归 179 项全部通过，无跳过；`git diff --check` 通过。真实终端按钮外观与点击已由用户确认可用。

- 2026-10-05 08:59：上下键导航改动离线完整回归 180 项执行成功，9 项 tmux 集成按默认配置跳过；Textual headless 实际按键验证跨组跳过路径、首尾停留与不触发导航。未重复真实终端验证。

- 2026-10-05 08:54：用户确认侧栏画面与鼠标切换均正常；提交前复核改动范围，`git diff --check` 与受影响文档本地链接检查通过。源码沿用已通过的 174 项完整回归及真实 pty 鼠标端到端验证结果。

- 2026-10-05 08:52：鼠标修复完整回归 174 项全部通过，无跳过；独立 socket + 真实 pty client + SGR 鼠标协议点击 beta 组 Shell，侧栏迁到目标 window 且输入焦点交给目标 pane，测试资源已清理。只读核对用户 tmux `mouse=on`，未修改用户鼠标设置。探针为 `.tmp/sidebar-mouse/verify.py`。

- 2026-10-05 08:46：侧栏样式与宽度改动完整回归 172 项全部通过，无跳过，覆盖隔离 tmux 原生切窗、焦点、宽度保持与长列表滚动；行渲染测试覆盖 14 列长路径截断与选中竖线。导出 34／14 列 headless SVG，普通预览核对树线与留白；Quick Look 彩色 SVG 转 PNG 的文字渲染异常，用户随后确认实际终端画面正常。

- 2026-10-05 08:39：提交前完整回归 172 项全部通过，无跳过；`git diff --check` 与受影响文档本地链接检查通过。已核对远程 master 仅含独立初始化 README 与 MIT LICENSE，合并后保留两侧历史与远程 LICENSE，README 冲突按当前完整说明解决，源码与测试未改变。

- 2026-10-05 08:32：完整回归 `AGENT_TREE_RUN_TMUX_TESTS=1 PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -t tests`：172 项全部通过；离线执行 172 项、9 项集成跳过。新增重启时 detached Agent 保留、包装启动识别、普通 shell／未知程序／缺失进程／历史启动命令过滤、Agent 退出与关闭后移除的单元和隔离 tmux 验证。`bin/agent-tree --snapshot` 只读默认 server，agent-tree 组包含 %0 与 %4 两个 Codex。

- 2026-10-05 08:24：首次提交前运行 `AGENT_TREE_RUN_TMUX_TESTS=1 PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -t tests`，169 项全部通过、无跳过；Markdown 本地链接检查通过。沙箱内首次运行有 9 项 tmux 集成错误（测试 socket 不存在），申请沙箱外执行后全量通过。

- 2026-10-05 08:19：`AGENT_TREE_RUN_TMUX_TESTS=1 PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -t tests`：169 项全部通过、无跳过。真实 pty client + textual 验证 prefix+n 切窗、跨 session 跟随、ANSI 高亮、35% 宽度、输入焦点、双 client 隔离、原窗布局还原、用户 PID 保留和 q 退出；headless textual 验证 50 条列表末行滚动可见。旧集成夹具改用软链接模拟 Codex，避免 macOS 复制签名二进制后以 -9 终止。详见 [验证记录](/Users/mac/workspace/agent-tree/docs/validation.md) 。

- 2026-10-05 07:40：真实进程端到端（`.tmp/sidebar-companion/verify.py`，独立 socket + pty client + 真实 textual 侧栏）通过：A 同 session 换 window 补位且 client 不动（你的 tmux 开了 renumber-windows，旧 window 销毁后索引重排，断言按「与目标 pane 同窗」）；B 跨 session 补位、client 跟随、宽度保持 53 列，其中目标 session 先经临时 client 附着一轮写入 keep_sessions；C 列表为空时侧栏 pane 关闭、session 消亡（client 短暂滞留属纯 tmux 行为，对照实验证明无侧栏时同样发生）。探针在哑 pty 下 textual 启动有几率滞后，已加「等标题栏渲染完成」的引导等待。新增 9 项离线决策测试与 1 项无 client 的集成测试（kill 旁 pane 后侧栏迁到目标 session）。离线 154 项、`AGENT_TREE_RUN_TMUX_TESTS=1` 时同批 154 项通过。

- 2026-10-04 18:56：在隔离 socket 上用真实 pty client（178x40）逐步复现并验证：修复前 `new_session()` 后侧栏由 53 列被摊到 73 列（复现散帅报告的变宽）；修复后 launch、join、`switch-client` 各步侧栏均保持 53 列（30%）。新增单元测试断言 `new-session` 携带 `-x`／`-y`，新增无 client 的集成测试断言 `new_session()` 后侧栏宽度不变。离线 142 项、`AGENT_TREE_RUN_TMUX_TESTS=1` 时同批 142 项通过。探针脚本存于 `.tmp/sidebar-width/repro.py`。

- 2026-10-04 18:25：在附着两个 client 的独立 socket 上完整复现并验证散帅的场景：初始 `ttys036→A`、`ttys037→B`；在 B 的条目上按 Enter 后两者都变成 `→B`、`A attached=0`（复现「A 被丢下」）；按 `q` 退出侧栏后 `ttys036→A`、`ttys037→B`、`A attached=1`（终端被送回原 session）；随后重新启动侧栏，正常列出 A 与 B 两组共 3 个 pane，不再少一条。新增 6 项单元测试覆盖还原、跨多跳只回起点、用户自行切换后不干预、无导航时为空操作、幂等。离线 140 项、`AGENT_TREE_RUN_TMUX_TESTS=1` 时同批 140 项通过。

- 2026-10-04 18:05：在附着两个 client 的独立 socket 上端到端验证 Enter 能「进去」：同 session 场景下高亮 A 的 Codex 后按 Enter，A 窗口的活动 pane 由侧栏 `%4` 变为 `%0`（焦点确实落到目标），clients 不变；跨 session 场景下高亮 B 的 Codex 后按 Enter，发起方 client 切到 B、侧栏迁入 B、B 的活动 pane 为 `%2`。离线 134 项、`AGENT_TREE_RUN_TMUX_TESTS=1` 时同批 134 项通过。

- 2026-10-04 17:50：在附着两个 client 的独立 socket 上验证当时的拦截版本：`Enter` 不移动 client 并显示提示，`→` 才切。该行为已被 18:05 的修复取代，记录备查。

- 2026-10-04 17:35：对默认 socket 只读核对：`session_created` 与各 client 的 `client_created` 逐一吻合（每个 iTerm2 标签页各建了一个 session），但 `ttys029` 已从它创建的 session 17 移到 session 20，session 17 变 detached —— 证实跨 session 导航会夺走发起终端。该结论直接触发了 17:50 的修复。

- 2026-10-04 17:15：对默认 socket 只读运行新分组：`/Users/mac/workspace/kzz-radar/web` 的分组键由自身变为 `/Users/mac/workspace/kzz-radar`；用 `ui.group_line` 按 34 列渲染，条目显示为 `▾ [kzz-radar]  ~/workspace`，`[deepseek-harness]`、`[workspace]` 等仍各自成组。新增单元测试覆盖同仓库子目录合并、非仓库目录保持独立、worktree 的 `.git` 文件、嵌套仓库取最近者、家目录不当仓库根。离线 133 项、`AGENT_TREE_RUN_TMUX_TESTS=1` 时同批 133 项通过。

- 2026-10-04 17:00：在附着两个 client 的独立 socket 上端到端验证 `n`：初始高亮在 `[other]` 目录行，按 `n` 后新建 session 出现，其 shell pane 的 `pane_current_path` 正是选中目录（`/private/tmp/…/other`），原在 A 的 client 切到新 session，侧栏随之迁入且 pane 仍存活，用户既有 pane 未受影响；侧栏随即显示 4 条（新增的 Shell 出现在该目录下）。离线 127 项、`AGENT_TREE_RUN_TMUX_TESTS=1` 时同批 127 项通过。
