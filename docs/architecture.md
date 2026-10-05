# 架构草案

## 集成决策

已确定采用「tmux CLI → 会话快照 → 目录聚合与检测 → TUI 侧栏」结构。观察面只读取 pane 信息；操作面仅定位已有 pane，生命周期管理只涉及自建侧栏 pane。tmux 拥有用户终端与 Agent 生命周期。

侧栏放在当前 window 左侧专用 pane 中，观察同一 server／socket 内各 session、window 的 Agent pane，并排除所有 agent-tree 自建 pane。iTerm2 等终端仅承载 tmux，不使用其原生 API、Toolbelt 或网页服务。

导航明确记录发起操作的 client 和目标 session／window／pane；跨 session 操作不切换其他 client 的 session。共享 session 的 window 选择可能影响其他 client，需通过原型确认实际行为与提示策略。跨 window 持续显示采用**迁移单个自建侧栏（join-pane）**方案：仅在当前 window 维护一个侧栏实例，导航时把侧栏迁移进目标 window 再切换发起 client。不采用「每个 window 各建侧栏」，因为它需要按 window 焦点创建、依赖 hook，并持久改变所有 window 布局，超出最小范围。实测见 [验证记录](/Users/mac/workspace/agent-tree/docs/validation.md) 。启动时绑定注视目标窗口的 client（多个时取最近活跃者），将 client 名、初始目标 pane 和宽度传给侧栏进程。每 0.25 秒读取绑定 client 的当前位置；用户原生切换 window／session 后，以当前 pane ID 为目标执行 `join-pane -d`，只迁移自建侧栏且不切换 client、不抢输入焦点。绑定 client 断开时不接管其他终端；目标已有其他侧栏或不足 60 列时拒绝迁入。单 pane 窗口迁移仍沿用导航的销毁顺序保护。

方向键只移动高亮，Enter／右方向键／Esc／鼠标点击进入选中会话并将焦点交给目标 pane。绑定 client 的当前用户 pane 改变时，同步高亮、展开所在分组并滚动到对应行；焦点回到侧栏后保留浏览中的选择。刷新导致条目重排时按稳定会话键保留选择。用户主动跨 session 切换后取消之前导航的还原记录，退出时不拉回旧起点。

当前技术栈为 **Python 3.14 + textual**，界面以外的 tmux 访问、进程识别与目录聚合只用标准库；测试用 `unittest`。不复制上游终端工作台。

## 数据模型与分组

会话记录建议字段：`session_key`、`host_key`、`backend`、`backend_target`、`cwd`、`canonical_cwd`、`cwd_source`、`agent_id`、`display_name`、`state`、`state_source`、`confidence`、`observed_at`、`generation`、`is_active`。

会话键必须包含宿主身份：使用 tmux server／socket 身份加 pane ID；PID、名称、window 序号都不能单独作为稳定 ID。项目分组键使用 host 身份与规范化绝对路径；不盲目小写 macOS 路径，不假设卷一定不区分大小写。旧连接或旧 generation 的异步结果不能覆盖新快照。

tmux 优先读取 pane 的 current path、current command、PID 等元数据，再对同一 TTY／进程子树补充识别。pane 的 cwd 不一定反映 Agent 内部切换的目录，无法确认时保留最近可信来源并标注。包装命令与 hook 可提供更强证据，但属于后续可选集成，不要求用户改变启动方式才能看到基础条目。

## Agent 与状态检测

身份与执行状态分别判断：识别出 Codex 不代表知道它是否正在执行。身份优先用可信启动元数据和进程可执行文件／参数，屏幕特征作为补充；node、python、shell 包装不能单靠进程名定性。

状态证据建议顺序为已验证的结构化事件、活跃界面或 OSC 信号、低可信启发式。事件必须关联目标会话并处理乱序、过期和退出；屏幕检测限制到当前可变区域，避开历史记录与 transcript viewer。无输出或进程存活只能作为观察事实。

| 状态 | 充分证据要求 | 无证据时 |
| --- | --- | --- |
| `working` | 有效执行事件或已验证的实时执行界面 | `unknown` |
| `idle` | 有效回合结束／就绪事件或明确空闲提示 | 不从静默推断 |
| `blocked` | 当前等待输入或授权的事件／实时交互框 | 不从历史文案推断 |
| `unknown` | 身份或状态证据不足、采样不可用 | 显示「状态未知」 |

`stale` 是数据新鲜度标记，不是执行状态。错误／完成提示只在有明确事件时追加，不把任意进程退出认作任务成功。状态短时抖动使用有限延迟确认；具体时间与刷新频率通过原型测试确定。

## 运行与安全边界

侧栏不提供网页服务或网络控制面。屏幕文本只在内存中短暂匹配，默认不记录完整输出、提示词或命令参数。

tmux 调用用参数数组，目标路径与文本不能拼接执行；不覆盖用户全局配置、快捷键和 hook。对已有布局的改变必须只围绕自建侧栏，并在退出时核对用户期间的布局变化，不用旧快照强行覆盖新布局。侧栏崩溃和宿主断连不能结束用户进程。

初期可使用单进程与内存快照，不引入数据库和常驻 daemon。首版只连接启动上下文指定的 tmux server／socket。重复发现按 backend target 去重；多个 sidebar 实例需要各自所有权标记，禁止互相回收。

## 检查点 1 已确认的宿主行为

以下行为已在 tmux 3.7c 上实测，实现层应直接依赖；完整证据见 [验证记录](/Users/mac/workspace/agent-tree/docs/validation.md) 。

- 枚举用 `list-panes -a -F`，字段以 `\x1f` 分隔；`pane_id` 为稳定会话键。
- `pane_current_path` 已是 macOS 真实路径且 tmux 已解析软链接，分组直接采用，不重复 realpath；会话键包含 server／socket 身份。
- 独立 socket 仍加载用户 `~/.tmux.conf`，不假设序号从 0 开始；对 `mouse` 等选项的修改限定窗口级并在退出时恢复。
- 侧栏用 `join-pane` 迁移，`pane_id` 与 `pane_pid` 不变；`kill-pane` 在无其他改动时自动还原原布局，不强制套用旧快照。
- 读取 client 上下文必须走 `list-clients`，不能用 `display-message -c`；导航用 `switch-client -c` 只影响发起 client。
- 同一 session 的多个 client 共享当前 window，导航后须提示共享影响。
- 用 pane 级 `@agent_tree_sidebar` 标记实例所有权并排除自身，标记跨 `join-pane` 保留。
- 身份识别不依赖 `pane_current_command`，结合 `pane_start_command` 与进程树证据。
- 窄屏下 `split-window` 不报错，应用层须自设最小宽度门槛。

## 原型验证入口

检查点 1 已完成，原型脚本保留在 `.tmp/tmux-sidebar-mvp/probe_cp1.py`（不属运行依赖）。后续验证沿用独立 socket 与明确归属的测试会话，完成后仅清理原型创建的对象。
