# 宿主可行性验证记录

本文件保存 agent-tree 的阶段验证过程、环境版本、结果与未覆盖范围。只记录实际执行过的验证，未运行的事项标为未验证。

## 2026-10-05 08:32：detached Agent 发现修复

完整回归 172 项全部通过（含隔离 tmux 与真实 textual／pty）；离线执行 172 项，9 项集成跳过。

- 单元测试确认：detached Codex 与包装启动的 Claude Code 在空 keep_sessions 下仍可见，模拟侧栏重启后仍保留；普通 detached shell、未知进程、历史 Agent 启动命令、缺失进程不自动纳入；Agent 退出回到 shell 后取消存活 Agent 例外。
- 隔离 tmux 确认：detached Codex 在重新扫描时保留，旁侧普通 detached shell 隐藏，关闭 Codex session 后条目移除。
- 默认 server 只读运行 `bin/agent-tree --snapshot`，agent-tree 组同时显示 %0 与 %4 两个 Codex；没有修改用户 session、client 或 pane，也没有重启用户正在运行的侧栏。已运行的侧栏需要退出后重新启动以加载新版发现规则。

## 2026-10-05 08:19：原生切窗跟随与当前行同步

环境：macOS、Python 3.14.8、tmux 3.7c；项目 `.venv` 中的 textual。验证使用独立随机 socket、两个真实 pty client 和真实侧栏进程，不接触用户 session。

- `AGENT_TREE_RUN_TMUX_TESTS=1 PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -t tests`：169 项全部通过，无跳过。
- `tests/test_integration_tmux.py`：prefix+n 原生切窗后侧栏迁到目标窗口；跨 session 跟随，ANSI 渲染高亮落到对应目录的 Shell 行；35% 宽度保持，用户 pane 持续接收输入，旧窗口布局还原；另一个 client 切换 session 不抢走侧栏；用户 PID 不变，q 退出后只剩原有用户 pane，测试 server 与 pty client 清理。
- `tests/test_ui.py`：headless textual 的 50 条列表中，当前 pane 更新后对应行滚动进入可视区域，回到侧栏后保留浏览选择。
- `tests/test_sidebar.py`、`tests/test_tui.py`：绑定 client 断开不接管其他 client，目标失效／迁移失败不关闭用户 pane，窄屏和重复侧栏拒绝，当前分组展开、条目重排保留身份、新目标在侧栏聚焦时只同步一次、手动跨 session 后取消旧还原记录。

测试环境修正：macOS 会以 -9 终止复制后签名失效的 `/bin/sleep`，旧夹具改用 `codex` 软链接，仍通过启动命令识别；pty 无色终端下 textual 将选中背景映射成灰度，ANSI 断言同时覆盖实测灰度与真彩色背景。

未覆盖：不同 tmux 版本、真实 iTerm2 鼠标切窗、同窗多 client 的初始绑定仲裁；共享 session 的 window／布局仍受 tmux 自身共享语义影响。跟随范围是启动 client 所连接 server，不跨 tmux socket 或 tmux 外部终端。

## 2026-10-04 检查点 3：导航与侧栏生命周期

### 方法

隔离 socket 上运行两个端到端脚本，脚本自建 session／window／pane，并以控制模式 client 模拟真实交互，通过 `tmux send-keys` 驱动键盘：

- `.tmp/tmux-sidebar-mvp/verify_cp3.py`：22 项，覆盖创建、选中即切换、交出焦点、退出清理与布局还原。
- `.tmp/tmux-sidebar-mvp/verify_cp3_resilience.py`：14 项，覆盖窄屏、重复启动、多 client、崩溃清理与 `--in-pane` 接管拒绝。

单元测试同时扩到 119 项（含 `--width` 参数回归、鼠标点击映射与 pane 接管守卫）。

### 结果

- **创建**：默认 `agent-tree` 在当前 window 左侧创建带 `@agent_tree_sidebar` 实例标记的侧栏 pane，宽度占 30%，焦点落在侧栏，用户 pane 保留，布局按预期改变。
- **选中即切换**：按一次 `Down` 即完成导航，无需回车；侧栏 `pane_id` 与 `pid` 均不变（界面状态连续）；侧栏迁移到目标 window；发起 client 切到目标 session；焦点仍在侧栏；源 window 布局由 tmux 自动还原；目标 agent pane 未被关闭、未被写入任何导航字符。
- **交出焦点**：`Right`／`Esc` 后发起 client 的活动 pane 变为目标 pane，侧栏仍存在。
- **退出**：`q` 关闭侧栏 pane，目标 window 布局还原，用户 pane 与 agent 进程保留，无遗留自建 pane。
- **韧性**：40 列窄 window 拒绝创建且不改变布局；重复启动不新增侧栏 pane；两个 client 时只有发起 client 被切换，另一个 client 不受影响；`kill -9` 侧栏进程后 pane 被 tmux 关闭、布局还原为初始、用户 pane 与 agent pane 均保留。

### 关键发现

1. **argparse help 中的 `%` 会让启动器崩溃**：help 文本按格式串处理，「占总宽 30%」会抛 `ValueError: badly formed help string`，程序在创建侧栏前直接退出。已改为 `%%` 并新增 `tests/test_cli.py` 回归。
2. **导航只由用户操作触发**：刷新、条目增删与排序变化都不调用导航，`generation` 随每次刷新递增。
3. **退出即清理**：侧栏进程结束时 tmux 关闭该 pane，未被用户改动的布局自动还原；程序不做旧快照回写，因此用户改动过的新布局不会被覆盖。
4. **不改用户配置**：没有绑定 tmux 快捷键，也没有改动 `mouse` 等选项；未开启 tmux 鼠标时只在侧栏底部提示。交出焦点后可用 tmux 默认的 `last-pane`（`prefix + ;`）回到侧栏。
5. **环境限制（非产品问题）**：本机沙箱内 zsh 的 compinit 无法写 `~/.zcompdump` 而卡住启动，验证脚本改用 `sh` 作为测试壳。

### 验证后修复（2026-10-04）

1. **`--in-pane` 接管守卫**：此前 `--in-pane` 会无条件把所在 pane 标记为自己并启用导航，若被误用在用户的 shell pane 上，一次选中即切换就会把该用户 pane 迁移到别的 window。现在 `claim_pane` 只接受「启动命令来自 agent-tree」或「已属于本实例」的 pane，其余明确拒绝；已在隔离环境补三项负向验证。
2. **启动器错误处理**：`_launch` 此前只捕获 `SidebarError`，来自 tmux 的 `TmuxError`（如目标 window 消失）会以原始 traceback 退出；现统一捕获并输出可读信息。
3. **集成测试残留**：`tests/test_integration_tmux.py` 会在 tmux socket 目录留下空壳文件；现在 tearDown 会读取并删除自己创建的 socket，重复运行验证后目录仅剩 `default`。

### 未覆盖范围

- 鼠标点击未在真实终端验证：点击到行的映射与「点会话即切换、点目录即折叠」逻辑已由单元测试覆盖，但向 pane 投递鼠标事件需要 tmux 开启 `mouse`，本环境无法可靠模拟，未做端到端确认。
- socket 断开、以及导航瞬间目标 pane 被删除的在线时序未做端到端验证；失效目标的错误语义已有单元测试覆盖。
- 同一 window 被多个 client 同时注视时，发起 client 取 `client_activity` 最大者；该策略未在真实多 client 交互中验证。
- 跨 window 侧栏保持仅验证了由侧栏发起的导航；用 tmux 自身快捷键切换 window 时侧栏不跟随（已在架构中登记为已知限制）。

## 2026-10-04 检查点 2：发现、识别与目录树

### 方法

源码位于 `src/agent_tree/`（`model` / `tmux` / `processes` / `discovery` / `grouping` / `tui` / `__main__`），仅用标准库。验证分三层：

1. 离线单元测试 `tests/`：78 项通过（其中 4 项集成测试默认跳过）。
2. 隔离 tmux 集成测试 `tests/test_integration_tmux.py`：显式启用后 4 项通过。
3. 真实环境检查：在独立 socket 上启动真实 `claude` 2.1.285 与 `codex` 0.160.0 运行 `--snapshot`；另对默认 socket 只读执行一次。

命令：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -t tests
AGENT_TREE_RUN_TMUX_TESTS=1 PYTHONPATH=src python3 -m unittest discover -s tests -t tests
PYTHONPATH=src python3 -m agent_tree --snapshot
```

### 结果

- 真实 `claude` 的 `pane_current_command` 实测为版本号 `2.1.285`，`codex` 为 `codex`；实现不依赖该字段，改用进程子树与启动命令，两个 Agent 均被正确识别。
- 真实环境首次运行输出：

```text
Agent Tree · 2 个会话 · /private/tmp/tmux-501/at-probe-int
▾ x  /private/tmp/at-probe/x
  [C] Claude Code  状态未知  %0
  [O] Codex  状态未知  %1
```

- 只对默认 socket 只读运行 `--snapshot`，在 9 个 session 中正确聚合出 5 个 Agent pane（4 个 Codex 与 1 个未知），普通 shell 未计入。
- 交互层在 tmux pane 中实机渲染成功，`q` 可退出并恢复终端：

```text
Agent Tree  1 个会话
▾ agent-tree  1 个会话  /Users/mac/workspace/agent-tree
  [?] 未知  状态未知  %1

↑↓ 选择  空格 展开/折叠  q 退出
```

- 空状态：只有普通 shell 时输出「未发现 Agent 会话」；不存在的 socket 明确报错并返回退出码 2。

### 关键发现

1. **身份识别必须用进程证据**：`pane_current_command` 可能是版本号（claude）或包装进程名（node），实现以「进程子树可执行文件名 → 进程参数中的明确路径 → 启动命令名」三级证据识别，启动命令只取命令名、跳过 `VAR=VALUE` 前缀，避免 `grep codex file` 之类误判。
2. **普通 shell 判断要用前台进程名**：仅看子树叶会把 shell 启动期的短暂子进程（补全初始化等）误判成程序，导致空闲 shell 被展示为「未知」；改为以 `pane_current_command` 为主、子树全为 shell 作为回退。
3. **`--snapshot` 不依赖终端**：交互模式需要 TTY 与可用 `TERM`；分离会话中 `TERM` 缺失时，curses 会以 `cbreak() returned ERR` 失败，现统一包装为可读的退出码 3 错误。
4. **stdout 必须是 tty**：curses 不能把 stdout 重定向到文件；验证时只能重定向 stderr。
5. 会话键为「socket 路径 + pane_id」，`join-pane` 后保持不变（集成测试覆盖）。

### 未覆盖范围

- 未用真实多 window／多 session 的交互式点击验证导航与焦点（属检查点 3）。
- 未接入字体图标与字符回退效果验证。
- 多个 client 同时注视同一 window 时「发起 client」的判定策略仍未实现与验证。
- 未验证 tmux 3.7c 以外的版本。

## 2026-10-04 检查点 1：tmux 宿主与交互可行性

### 环境

| 项 | 值 |
| --- | --- |
| 宿主 | macOS，tmux 3.7c（`/Users/mac/.local/bin/tmux`） |
| Python | 3.14.8，`curses` 可用（ncurses 5.7.20081102） |
| 验证方式 | 独立 socket `agent-tree-cp1` + 独立目录 `/tmp/at-probe`，不接触默认 socket 用户会话 |

### 方法

可复现原型 `.tmp/tmux-sidebar-mvp/probe_cp1.py`，按步骤增量执行（`setup` / `a` / `b` / `c` / `d` / `teardown`），全部 tmux 调用使用参数数组，字段解析用 `\x1f` 分隔以避免路径含空格被截断。结果：步骤 A 8/8、B 12/12、C 14/14、D 11/11，共 45 项通过。

### 关键发现

1. **枚举与稳定 ID**：`list-panes -a -F` 可跨 session/window 枚举；`pane_id`（`%N`）全局唯一，与 window/pane 序号解耦，可作稳定会话键。
2. **cwd 已规范化**：`pane_current_path` 返回 macOS 真实路径（`/private/tmp` 而非 `/tmp`），且 tmux 直接解析软链接。因此分组按该值本身即可归并软链接与直连目录，侧栏无需重复 realpath；父子目录仍需按完整路径分别成组。
3. **用户配置泄漏**：独立 socket 仍加载 `~/.tmux.conf`，实测 `mouse=on`、`base-index=1`。侧栏不得假设 window/pane 序号从 0 开始，且对 mouse 等选项的修改必须限定窗口级并恢复。
4. **侧栏迁移无损**：`join-pane` 跨 window/跨 session 后 `pane_id` 与 `pane_pid` 均不变，TUI 状态连续；`kill-pane` 在无其他改动时会精确还原目标 window 原布局，无需手动 `select-layout`。
5. **client 上下文读取**：control client 无 tty（`client_tty` 为空，`client_name` 形如 `client-<pid>`），`display-message -c <name>` 会回退默认 client 读到错误上下文；必须用 `list-clients` 逐 client 读取。`switch-client -c` 本身有效且只影响指定 client。
6. **共享 session 影响**：同一 session 的多个 client 共享当前 window，切换 window 会影响该 session 的全部 client，UI 需提示。
7. **自排除**：pane 级用户选项 `@agent_tree_sidebar` 可写入并跨 `join-pane` 保留，普通 pane 不含该标记，可作稳定的实例所有权与自排除依据。
8. **身份识别证据**：`pane_current_command` 对脚本/包装启动不可靠（假 `codex` 二进制观测为 `sleep`，`node` 包装观测为 `node`）；应结合 `pane_start_command` 与进程树（`ps`）证据。普通 shell 可识别并可回退。
9. **窄屏**：`split-window -l 30%` 在 8 列 window 下仍成功（侧栏仅 2 列），不报错；应用层需要最小宽度门槛与拒绝提示，而不是依赖 tmux 报错。
10. **错误路径**：过期 `pane_id` 与不存在的 socket 均返回明确错误且不改变当前视图。

### 方案对比：迁移单个侧栏（M） vs 每个 window 各建侧栏（W）

| 维度 | M：join-pane 迁移 | W：每 window 各建 |
| --- | --- | --- |
| 进程数 | 1 | N |
| 导航时动作 | 迁移侧栏 + 切换 client | 仅切换 client |
| 布局影响 | 每次导航改变源与目标 window | 每个 window 被持久改变 |
| 跟随 tmux 自身切窗 | 否 | 是 |
| 生命周期 | 单实例，无需 hook | 需要按 window 焦点创建，依赖 hook |
| 已验证 | 是（步骤 B/C） | 结构已验证（步骤 B） |

选择结论见 [架构文档](/Users/mac/workspace/agent-tree/docs/architecture.md) 。

### 未覆盖范围

- 未用真实 Claude Code／Codex 进程验证身份识别，仅用合成二进制与包装进程验证解析分支。
- 未验证真实终端下的鼠标点击、上下键与拖选体验，仅用控制模式 client 验证等价操作。
- 未验证字体图标与字符回退效果。
- 未验证多个 client 同时注视侧栏所在 window 时的发起 client 判定策略。
- 未验证 tmux 3.7c 以外的版本兼容性。