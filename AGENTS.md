# agent-tree 项目规则

## 项目定位

为现有终端提供按目录聚合的 Agent 会话侧栏。已实现 tmux 专用 pane 内的 TUI 侧栏（界面用 textual）；iTerm2 等仅作为承载 tmux 的终端，不开发宿主原生侧栏。

## 目录与工作流

- `README.md`：当前状态与文档导航。
- `ROADMAP.md`：实施阶段、待验证事项及验收记录。
- `docs/product-design.md`：需求、交互、范围与验收场景。
- `docs/architecture.md`：集成方式、数据模型、识别与状态规则。
- `docs/reference-review.md`：参考源码证据、可借鉴内容及复用边界。
- `docs/validation.md`：宿主与功能验证记录，保存环境版本、验证过程、结果与未覆盖范围。
- `goals/`：按时间命名的施工清单，记录目标、边界、检查点、验收与交付；当前清单不代表 Goal 已启动。
- `.tmp/<task-slug>/`：临时调研及验证产物，不作为运行依赖。
- `src/agent_tree/`：源码，Python 3.14。仅界面层依赖第三方库 textual；其余模块只用标准库。`__main__.py` 入口；`model.py` 数据模型；`tmux.py` tmux 访问层；`processes.py` 进程快照与进程树；`discovery.py` 身份识别与会话发现；`grouping.py` 按 Git 仓库根目录分组与树；`tui.py` 侧栏纯逻辑（行、折叠、选中、刷新、回调），不依赖界面框架；`ui.py` textual 界面；`sidebar.py` 自建侧栏生命周期、导航与新建会话。
- `tests/`：标准库 `unittest` 单元测试与隔离的 tmux 集成测试；依赖 textual 的用例在缺依赖时自动跳过。
- `pyproject.toml`：包声明与命令入口；运行时依赖仅 `textual`。
- `.venv/`：本地虚拟环境，装有 textual；`bin/agent-tree` 优先使用它。不入库。

进入项目先读本文件与 ROADMAP，再按任务读取设计文档。未来新增源码目录前先在本文件明确职责。CLAUDE.md 仅引用本文件。

## 工程边界与验证

侧栏绑定启动它的 tmux client；该 client 通过原生快捷键或命令切换 window／session 时，只迁移自建侧栏到当前窗口，保留用户输入焦点，并同步当前 pane 的高亮位置。其他 client 的活动不改变绑定；绑定 client 断开时不接管其他终端。不安装全局 hook 或修改用户快捷键。

侧栏默认只观察和导航既有会话，不创建、迁移、关闭或重启用户的终端，也不发送输入。**例外一**：用户显式按 `n` 时，在选中行所属目录下新建一个 session（跑默认 shell）；该操作只新增 session，不改动既有 pane 与布局，也不向新 pane 发送输入。**例外二**：侧栏所在 window 的用户 pane 全部关闭（如 shell 执行 exit）时，自动迁移侧栏补位——先取被关会话所在路径分组的第一个会话，该分组不在了取整个列表的第一个——并把 client 一起带过去；列表为空时侧栏退出，只关闭自己的 pane，session 与终端交由 tmux 自然收摊。tmux 侧栏只迁移／回收自己创建的 pane，退出必须保留用户进程与布局。不得把进程存活、输出活动或静默直接解释为任务正在执行、完成或失败。

优先验证宿主集成，再确定技术栈；不直接搬入参考项目的完整终端运行时。复用源码时记录上游 commit、文件与改动，保留适用的许可证、NOTICE 和第三方归属。

当前文档检查入口：本地链接、表格、尾随空白、来源与状态一致性。代码阶段至少验证路径聚合、识别降级、过期事件、焦点切换及无损退出。阶段与关键验收变化同步 workspace 总览。

验证命令（界面层需 textual，其余模块仅用标准库；需 Python 3.13+ 与 tmux，推荐用 `.venv/bin/python`）：

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -t tests      # 含 textual 界面用例
AGENT_TREE_RUN_TMUX_TESTS=1 PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -t tests   # 隔离 tmux 集成测试
PYTHONPATH=src python3 -m agent_tree --snapshot              # 一次性打印聚合树，不依赖终端与 textual
bin/agent-tree                                               # 在 tmux 内启动侧栏
```

集成测试只使用独立 socket 与自建 pane，结束后清理，不接触用户会话。为不破坏用户鼠标与布局设置，侧栏对 tmux 选项的修改必须限定窗口级并恢复。textual 需要所在 pane 的 client 附着才会渲染，验证侧栏外观时须让该 session 有 client 附着（例如 `script -q /dev/null tmux -L <socket> attach -t <session>`）。
