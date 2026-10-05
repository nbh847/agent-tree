# Agents Go 参考调研

## 来源与核对范围

2026-10-04 通过 GitHub API 获取仓库信息，并下载 main 分支源码，核对 commit `db4ae594a4ed92bddeeefbb5788d635e452cc349`。本次为静态源码调研，未构建或运行上游；不能据此认定其 macOS 运行正常。

仓库名含 go，但实现是 Rust。README 说明其源自 Herdr，可执行文件仍叫 herdr，维护者仅声明 Windows 手动验证，其他平台改动未手动验证。Cargo.toml 包版本为 0.9.3，使用 ratatui、crossterm、portable-pty、tokio 和 ghostty-vt。

## 实现证据与借鉴判断

| 关注点 | 固定版本源码 | 判断 |
| --- | --- | --- |
| 项目与对话树 | [task_tree.rs](https://github.com/zhangxq0606-ctrl/agents-go/blob/db4ae594a4ed92bddeeefbb5788d635e452cc349/src/client/shell/task_tree.rs) | 树引用内部 workspace／pane ID；可借鉴目录、会话与关注数量的组织方式，不能直接用于枚举现有 tmux pane。 |
| Agent 与状态 | [detect/mod.rs](https://github.com/zhangxq0606-ctrl/agents-go/blob/db4ae594a4ed92bddeeefbb5788d635e452cc349/src/detect/mod.rs) | 定义 24 种 Agent 枚举及 Idle／Working／Blocked／Unknown；存在屏幕信号可信度与历史浏览跳过标记，枚举数量不代表本项目适配数量。 |
| 规则清单 | [claude.toml](https://github.com/zhangxq0606-ctrl/agents-go/blob/db4ae594a4ed92bddeeefbb5788d635e452cc349/src/detect/manifests/claude.toml)、[codex.toml](https://github.com/zhangxq0606-ctrl/agents-go/blob/db4ae594a4ed92bddeeefbb5788d635e452cc349/src/detect/manifests/codex.toml) | 按活跃区域、提示符、OSC 标题／进度信号区分状态；可借鉴规则与样本组织，需针对本地 CLI 版本重新验证。 |
| 状态稳定 | [agent_detection.rs](https://github.com/zhangxq0606-ctrl/agents-go/blob/db4ae594a4ed92bddeeefbb5788d635e452cc349/src/pane/agent_detection.rs) | 有工作到空闲的延迟确认、启动宽限和未变化屏幕跳过；应借鉴抗闪烁与过期处理，不能照搬所有时间常量。 |
| 侧栏字段 | [sidebar.rs](https://github.com/zhangxq0606-ctrl/agents-go/blob/db4ae594a4ed92bddeeefbb5788d635e452cc349/src/config/sidebar.rs) | 可组合 Agent、工作区、状态与标题等字段；首版固定必要字段即可。 |
| 终端运行时与依赖 | [Cargo.toml](https://github.com/zhangxq0606-ctrl/agents-go/blob/db4ae594a4ed92bddeeefbb5788d635e452cc349/Cargo.toml)、[README](https://github.com/zhangxq0606-ctrl/agents-go/blob/db4ae594a4ed92bddeeefbb5788d635e452cc349/README.md) | 属于自己管理终端的完整工作台。直接 fork 会引入 PTY、终端渲染、远程连接等超出当前需求的职责。 |

## 建议路线与复用边界

建议以独立侧栏项目起步，借鉴交互与检测思想；待宿主集成通过后，再决定是否抽取少量检测规则。现已确定采用 tmux TUI 独立侧栏，源码继承与技术栈仍待原型验证后决定。

上游保留 Apache-2.0、LICENSE、NOTICE 与第三方归属。复制或修改代码前核对具体文件许可证并保留对应声明；仓库许可证不代表所有依赖和品牌图标可以无条件复用。本次没有复制源码或图标。

## 宿主一手资料

当前实施仅采用 tmux。下列 iTerm2 资料保留为初次调研记录，不属于实施范围或待办。

- [iTerm2 Python API](https://iterm2.com/python-api/index.html) ：提供控制及扩展接口。
- [iTerm2 Tool](https://iterm2.com/python-api/tool.html) ：可注册 Toolbelt WebView 工具，是原生侧栏的候选入口。
- [iTerm2 Session](https://iterm2.com/python-api/session.html) ：提供会话激活、屏幕读取、变量获取等接口；tmux 命令接口限定在 tmux integration session。
- [tmux 官方入门](https://github.com/tmux/tmux/wiki/Getting-Started) ：说明 server、client、session、window 与 pane 的关系。

上述文档已在线读取。接口存在不等于本机权限、目录数据、跨窗口导航及侧栏刷新链路已经验证。
