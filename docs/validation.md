# 宿主可行性验证记录

本文件保存 agent-tree 的阶段验证过程、环境版本、结果与未覆盖范围。只记录实际执行过的验证，未运行的事项标为未验证。

## 2026-10-08 15:08：点击后无法留在侧栏的现场检查

用户报告当前窗口侧栏点击无反应，按 q 输入到右侧，随后确认蓝点仍在闪动。只读现场：侧栏 %58 的 Python PID 91694 从 2026-10-06 08:39 运行；tmux mouse on、MouseDown1Pane 默认 select-pane/send-keys -M 绑定、pane 的鼠标与 SGR 请求均正常，非复制模式。1 秒系统采样显示事件循环、外部查询与输入线程仍存在，不足以认定死锁或终端鼠标事件丢失。

在自建侧栏上尝试 respawn-pane 后该 pane 意外退出，原因未确认；使用正常启动入口重新创建 %74（PID 4177），验证已绘制、鼠标协议开启，右侧 Codex %68 PID 30883 与输入焦点保留。没有重启用户进程或发送按键，没有修改全局鼠标设置或快捷键，也未操作另一侧栏 %73。当前代码点击会话行立即导航并交出输入焦点，q 此时会进入右侧；已请用户点击底栏空白并按方向键，以区分正常交接与真正输入失效。用户随后确认点击底栏空白再按方向键已能移动选中项，当前输入恢复通过真实验收；原始点击失效根因仍未确认，不声称已根治。本次没有新增代码或重复运行测试。

## 2026-10-08 15:00：Codex 运行提示与 Tip 间隔

只读核对真实 Codex pane，看到 `• Working (32s • esc to interrupt)` 后有 `└ Tip:` 和空行，再出现输入框。原规则只保留输入框前 3 行，运行提示被裁掉，随后就绪输入框匹配为空闲。修复仅跨过紧邻输入框的空行和 Tip 行，遇到正文停止，采样仍限当前屏幕底部 12 行，不根据输出活动推断任务结果。

新增回归覆盖带 Tip、多个空行、计时运行指示与旧状态被正文隔开；既有界面回归验证 WORKING 状态点动画。普通回归 234 项通过（13 项集成跳过）；沙箱内强制集成因 socket 访问限制失败，权限通道首次审批超时，重试后独立 socket 完整回归 234 项全部通过，无跳过。未操作用户会话，真实侧栏动画外观待用户退出并重启侧栏后验收。

## 2026-10-08 09:20：异常宽度与退出结果回调

针对第二张截图的单侧栏异常变宽，在独立 tmux 3.7c socket 中复现：200 列窗口依次分出两个 `24%` 侧栏，实际为 48 列与 36 列；关闭前一个后，tmux 将空出的宽度并入相邻侧栏，使后者变成 85 列，占 42.5%。这复现了相同的宽度现象；原始现场的完整操作顺序未记录，不能据此推断所有触发步骤。

绑定 client 的跟随检查现在同时校正宽度：窗口宽度或 pane 集合变化时按 `--width` 计算，百分比相对整个窗口，绝对列数保持指定值；核对所有权后仅调整自建 pane，同布局手动拖动保持，zoom 不调整。54 项相关回归通过，真实隔离 tmux 测试覆盖相邻侧栏关闭后恢复、窗口缩放、绝对列数与用户 pane 保留；离线分支验证 zoom 和所有权失败不写入。

首轮 231 项完整回归发现一个界面退出时序错误：扫描结果在控件卸载后仍尝试绘制。已针对退出状态保护后台结果与定时器，并新增停止后不应用结果的回归；33 项界面测试通过。最终独立 socket 完整回归 232 项全部通过，无跳过；文档链接、尾随空白与差异检查通过。未关闭用户窗口、未验证新的真实 iTerm2 外观，长期持续运行仍待验收。

## 2026-10-08 09:13：双侧栏冲突与扫描阻塞

用户报告持续运行约一两天后侧栏点击无响应，重新启动后出现双侧栏。只读检查与离线模拟确认 `navigate()` 未检查目标窗口的其他侧栏，仍会提交迁移；长期卡死现场未保留，同步扫描与无超时查询是代码中确认存在的阻塞风险，尚不能认定为原始故障的唯一诱因。

修复后，冲突导航在任何迁移、切窗与焦点命令前拒绝；会话扫描在后台执行，仅一轮在途，通过队列回到界面线程更新。tmux 命令与进程查询各有 2 秒超时；扫描失败保留列表并提示，后台线程不阻止退出。图片宿主查询、导航查询与退出恢复的访问错误不会因新增超时而直接中断界面或掩盖退出结果。

验证环境沿用项目 `.venv`、Python 3.14 与本机 tmux。105 项相关单元回归通过；随后执行 `AGENT_TREE_RUN_TMUX_TESTS=1 PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -t tests`，228 项全部通过，无跳过。新增隔离 tmux 测试核对冲突拒绝后双方 window 布局及侧栏所有权不变；界面测试阻塞扫描后仍可选择、折叠并按 `q` 退出，重复触发不启动并行扫描，失败保留当前树并能恢复；查询超时分支通过离线测试。首轮失败来自测试未等待初始异步结果及在子会话行使用仅路径行适用的折叠键，已修正测试前提。文档链接、尾随空白与 `git diff --check` 通过。

本次未关闭、重启或迁移用户会话，未做新的真实 iTerm2 外观检查，也未完成连续一两天的运行验收。已运行实例需要退出后重新启动才能加载修复。

## 2026-10-06 08:22：导航命令队列

侧栏迁移、切窗和焦点设置改为单次 tmux 命令序列提交，迁移使用 `-d`，仅最终命令设置焦点。原窗口只剩侧栏时仍先切 client；队列失败停止后续操作，已经切走的 client 保留退出恢复记录。原生切窗轮询不变。

50 项侧栏单元回归通过，覆盖单次队列、顺序、迁移失败停止与前置切窗恢复记录；11 项独立 socket tmux 集成回归全部通过，覆盖原生切窗跟随、图片缓存、导航、焦点及退出；30 项界面回归单独复跑通过。首次沙箱内集成测试因测试 socket 不可用失败，沙箱外运行通过。完整回归的 tmux 用例通过，但一个原有界面用例在退出时发生 `_sync_host` 查询已卸载 `#scroll` 的时序错误；单独复跑界面通过，未修改该退出时序逻辑。用户于 2026-10-06 08:39 确认实际切换已正常并要求提交；尺寸变化仍可能引起程序重绘。


## 2026-10-06 08:05：当前输入区状态识别

实现当前屏幕只读匹配：Codex、Claude Code、CodeBuddy 支持执行指示、带数字选项及控制提示的选择框、就绪输入框；Pi 只识别明确带中断提示的运行状态。只对当前进程树确认的 Agent 采样；默认每 2 秒更新，不保留旧状态。复制模式、pane 消失、未匹配信号立即回退未知。屏幕不落盘，不安装 hook，不修改 Agent 配置。空闲包含初始就绪、结束和中断，不承诺任务成功。

219 项独立 socket 完整回归通过，无跳过。新增 8 项状态用例、1 项 Textual 状态刷新用例和 1 项真实 tmux 屏幕／历史模式用例；覆盖历史启动命令不触发采样、旧运行指示排除、当前确认框、采样失败、状态不沿用、图标位置和选中行稳定、scrollback 排除及复制模式降级。首次完整回归暴露旧集成测试仍预期固定状态来源，修正为当前采样未匹配来源后完整通过；没有放宽状态断言。

默认 server 只读快照识别 Codex %21、%47 与 Claude Code %24 均空闲；未发送输入或改变用户布局。官方 Codex 状态／授权源码与本机 Claude Code 输入区、CodeBuddy 2.161.0／Pi 1.0.3 实现已核对，来源见架构文档。真实执行／授权、CodeBuddy／Pi 状态与新增状态文字的 iTerm2 外观尚未验收；特殊主题、长输入、窄屏、冻结画面和结构化结束事件不在已验证范围内。

## 2026-10-05 20:33：detached 普通服务重开可见

只读核对默认 server：kzz-radar %32 所在 session 19 为 detached，进程树含 zsh → bash → Python、Node，服务未退出；旧发现过滤仅放行已识别 Agent，因此重开后漏掉服务。改为依据当前非 shell 进程保留，支持前台与后台服务，不以历史启动命令保留空闲 shell。

独立 socket 完整回归 200 项全部通过，无跳过；服务退出重开、后台运行与停止后的过滤均有回归。集成测试的空闲 shell 显式使用 /bin/sh，避免用户 shell 初始化子进程干扰空闲条件。修复后的实际只读发现使用空 keep_sessions，返回 7 条，包含 %32；空闲 %25 不显示。未操作用户 pane 或重启服务，用户侧栏需重开加载新版，未做界面外观验收。

用户于 2026-10-05 20:36 确认可用并要求提交；提交前复核改动范围与文档一致性，沿用上述 200 项完整回归结果。

## 2026-10-05 20:23：选中背景完整覆盖

复现：40 列会话行包含四个图片位置标记及 12 个零宽组合字符，Textual 实际渲染后仅剩 28 列。Textual Content 与 Rich Text 的换行处理均按字符数执行 `rstrip_end`，误删行尾 12 个空格。列表关闭自动换行并设置溢出裁剪，继续由行构建逻辑按终端列宽截断；上下留白行补满背景并同步选中蓝色竖线。宽度取 resize 事件，避免控件旧尺寸导致缩窄后仍保留图片。

独立 socket 完整回归 199 项全部通过，无跳过。新增 headless 渲染用例核对三行均为 40 列、每个片段背景为选中色、图片 ID 前景颜色仍保留、下一条背景未被染色；已有窄栏、滚动、折叠与跨 window／session 焦点回归通过。真实 pty 集成的颜色断言改为解析跨行继承的 SGR 背景状态，避免三行连续背景只在第一行输出颜色造成误判。用户于 2026-10-05 20:25 确认问题已解决，实际外观验收通过；未重新获取 iTerm2 截图。

## 2026-10-05 20:00：缓存 PNG 与 tmux 图片位置标记

用户要求必须保留图片，拒绝改成字体图标。重新核对 [iTerm2 图片文档](https://iterm2.com/documentation-images.html) 确认支持 Kitty Graphics；[协议中的 Unicode 图片位置标记](https://sw.kovidgoyal.net/kitty/graphics-protocol/#unicode-placeholders) 可以让普通字符画面保存实际 PNG 的显示位置。此前「焦点切换无法避免补画」的结论仅适用于旧 OSC 1337 叠图方式，不适用于这条缓存路径。

实现：三种 32 × 48 PNG 原样上传，创建四列／三行的虚拟画布，每种资源每个实例只上传一次。实例随机分配三个 24 位 ID，位置标记的前景 RGB 编码 ID，显式携带高字节为零的第三枚组合标记，避免 iTerm2 对省略高字节的历史兼容问题。tmux 重绘自己的字符画面即可恢复终端缓存图片；没有向宿主直接写绝对图片坐标。删除旧清图与补画逻辑，滚动、裁剪、折叠交给普通文字处理；正常与异常退出只回收本实例缓存。未增加运行依赖、替换 tmux 或修改全局选项。

原型：独立 socket `agent-tree-persistent-20261005`、iTerm2 窗口 580。原型上传三个 PNG 后进入 sleep，不再输出图片；切换两侧 pane 焦点后，`prototype-focus.png` 和 `prototype-settled.png` 仍显示三种真实图片，tmux capture 保存 U+10EEEE 与行列组合标记。`prototype-return.png` 为黑帧，不用作验收证据。

正式验证：29 项图标／界面回归通过；独立 socket 完整回归 198 项全部通过，无跳过，日志为 `.tmp/icon-persistent/full.log`。真实 pty 首帧采集每个 PNG 恰好一次及三个虚拟画布，之后三轮两侧鼠标点击、60 次无按键移动、选中变化和同尺寸跨窗口迁移都没有图片上传或画布重建；同时断言 tmux 宿主重绘包含图片位置标记，每次点击的目标 pane 确实获得焦点。q 输出只删除本实例的三个图片 ID，用户 pane 仍存活。首轮选项断言在子进程设置透传前执行，出现启动竞态；改为采集首帧后再核对原有隔离断言，不放宽图片、焦点或资源回收断言。

真实外观：`formal-agents.png` 确认 Codex／Claude 的 PNG 与名称右侧居中，`formal-shell-focus.png` 显示 Shell 焦点下的图片；`final-shell-focus.png` 和 `final-sidebar-focus.png` 同一可见列表同时包含三种 PNG，两侧焦点下图片均保留。`formal-folded.png` 显示正确鼠标折叠后无图片残影；展开与滚动后的图片由位置标记自然恢复。截图与探针保存在 `.tmp/icon-persistent/`。部分立即抓取的画面为黑帧，不将其认定为图片消失，也不作为外观通过证据。

清理：预览 socket 已关闭，iTerm2 仅剩用户原窗口 72；隔离回归的 socket／pty 由夹具回收。未重启用户侧栏或更改用户窗口。当前真实验收限于本机 iTerm2 3.7.3、tmux 3.7c 与保留 RGB ID 的终端链路；旧版宿主、不同真彩色配置、zoom 与更多多 client 外观仍待验收，用户于 2026-10-05 20:10 明确确认问题修复，当前本机使用验收通过。

## 2026-10-05 19:33：两侧 pane 焦点切换

用户报告在 Shell 与侧栏之间点击会刷新全部图片。Textual 的 `app_focus` 默认是触发重绘的 Reactive；新增焦点回归在原实现出现覆盖图片的 LayoutUpdate。将其改为 `repaint=False`、保留原有焦点 watcher 后，界面层不再整屏重绘。

仅禁用界面层重绘不足以解决问题：第一版 pty 用例只断言没有图片发送，因此通过；真实 iTerm2 窗口 570 的 `shell-focus.png` 和 `sidebar-focus.png` 却显示图片消失。随后采集宿主输出，确认切换 pane 包含整窗文字与 ECH 擦除。核对 [tmux 3.7 的 window_set_active_pane 源码](https://github.com/tmux/tmux/blob/3.7/window.c#L508-L536) ，它调用 `server_redraw_window`；透传 PNG 不在 tmux 的字符画面里，宿主重绘会覆盖图片。不能以「不再发送图片」作为图片保留的验收条件。

最终实现保留焦点状态处理，取消 Textual 额外的整屏重绘；收到 AppFocus／AppBlur 后只恢复可见图片，不清旧图、不再输出文字帧。原有内容更新、选中变化、滚动、折叠、尺寸与窗口迁移照常重绘。该方案消除应用层的额外清理与重绘，但 tmux 自身重绘仍存在，不能认定完全不刷新或零闪烁；完全消除需要改变图片集成方式，本轮未改 tmux、全局配置或项目架构。

真实 pty 用例开启独立 server 的焦点事件和独立窗口的鼠标选项，实际来回点击三轮，并检查每次目标 pane 确实获得焦点；每次仅一轮四个可见图片包，图片后没有覆盖文字。第一次点击用例没有开启测试窗口鼠标，未真正切换 pane，断言失败后已补齐夹具。headless 验证焦点状态随事件变化、没有覆盖图片区的文本帧、每次一张图片输出且不清旧图、恢复后键盘导航可用。模拟真实 driver 限定在同步图片输出函数内，避免异步 headless 循环误读取真实终端尺寸。

完整验证：196 项独立 socket 完整回归全部通过，无跳过，日志为 `.tmp/icon-focus/full-final.log`；`git diff --check` 通过。

真实外观：窗口 570 最终截图 `shell-focus-final.png`、`sidebar-focus-final.png` 确认两侧焦点下图片均保留，仍保持右侧居中。用户默认 server 的 `focus-events on` 仅只读核对；本实现不修改该选项，未开启时的焦点恢复不在此次验收范围。预览 socket `agent-tree-icons-20261005` 已退出，iTerm2 仅剩原窗口 72。截图、修复前失败日志及最终测试日志保存在 `.tmp/icon-focus/`。

## 2026-10-05 19:17：鼠标移动图标闪烁

复现：Textual headless 测试让鼠标经过目录、树线、名称、图片占位及留白，记录 `_display` 的覆盖区域；修复前出现多次覆盖图片的 `ChopsUpdate`，新增回归失败。本机 Textual 的 `Widget.watch_hover_style` 默认把文字样式的 `link_id` 写入触发重绘的 `highlight_link_id`，即使没有链接也会刷新。关闭三个 Static 的 `auto_links` 后，同样的悬停序列不再覆盖图片区域；没有拦截鼠标事件或跳过正常内容重绘。

验证：22 项界面回归通过；独立 socket 完整回归 195 项全部通过，无跳过。真实 pty 在稳定侧栏焦点下发送 60 次 SGR 无按键鼠标移动，跨过列表和底栏后图片协议发送次数为零；原有点击、滚动、折叠、迁移、三类资源和无损退出用例继续通过。日志保存在 `.tmp/icon-hover/before.log`、`ui.log` 和 `full.log`；测试 socket 与 pty 由夹具清理，未操作用户会话。本轮未另行获取 iTerm2 外观截图。

## 2026-10-05 19:05：名称右侧与垂直居中

按用户截图反馈，将左侧图标移到会话名称右侧，名称从树线后直接开始。图标跟随截断后名称的位置，按 Rich 显示列宽计算，保留一列间隔；空间不足 13 列时优先名称。

两行高图案与单行文字无法用原来的两行区域精确居中；改为三行条目，名称置于中间行。PNG 画布由 32 × 32 改为 32 × 48，上下各加入八像素背景留白，图案不变；输出四列宽、三行高画布，内部图案占两行，名称与图案中心对齐。背景统一为界面近黑色，避免原透明边缘继承宿主紫色背景。清理同步覆盖三行，继续在文本帧之前清旧图，所有可点击行指向同一会话，滚动保证完整图标可见。

验证：194 项完整回归全部通过，无跳过；补充三行滚动边界后 21 项界面测试通过。坐标测试确认名称行位于图标画布的正中间，右侧位置使用显示列宽；已有字符回退、窄栏、点击导航、无关点击、折叠、迁移与无损退出继续覆盖。独立 iTerm2 窗口 557 的真实截图 `.tmp/icon-right-align/centered.png` 确认 Shell 图标位于名称右侧且垂直居中。Codex／Claude 同样通过真实截图核对，证据为 `.tmp/icon-right-align/agents-centered.png`。预览窗口 557 和独立 socket 已清理，iTerm2 仅剩原窗口 72，用户三个 client 绑定不变。素材来源沿用资源说明，没有新增运行依赖。

## 2026-10-05 18:55：两倍宽高与点击残影修复

用户真实截图确认初版三类图标显示，但反馈图标过小、点击任意位置会补画并产生残影。代码核对确认 `_display` 曾对每个非空 Textual 帧无条件作废全部图片缓存；真实 pty 又确认点击过程中 Textual 的文本选择和焦点切换会引发重绘。不能仅凭上一轮字节流断言认定外观无残影。

- 显示范围从两列宽／一行高改为四列宽／两行高，宽度和高度均加倍；复用子会话前一行留白，不增加列表总行数，图片上半部点击同样可导航。素材仍为 32 × 32 PNG，运行时仅改变显示范围，编码量不增大；不足 12 列时优先名称。
- 帧的 region／spans 未覆盖图标且位置未变化时，不发送图片。需补画时，通过同一 driver 队列先用背景色空格覆盖旧图完整两行，再写 Textual 文本帧，最后发送新图片。跨窗口或越出当前自建 pane 的旧位置不清理，避免误写用户 pane。
- 禁用导航列表的 Textual 文本选择及滚动控件点击聚焦；保留真正宿主焦点变化所需的重绘。测试最初混入 `select-pane` 引起的合法焦点重绘，后改为先等待焦点稳定，再检查普通点击；没有禁止必要补画。
- 真实首帧曾被启动命令返回后的 shell 提示符重绘清掉，因此启动后延迟一秒只补画一次；之后仍按需发送。空闲测试在这一次启动帧结束后验证三秒零图片输出。
- 最终完整回归 194 项全部通过，无跳过；新增四列／两行协议、完整两行清理、清理与文本顺序、无关帧不补画、稳定焦点下点击底栏不重传的用例。已有点击导航、刷新、折叠、窄栏、迁移、进程识别和无损退出继续通过。
- 自建 iTerm2 窗口 508／独立 socket `agent-tree-icons-20261005` 的真实截图确认三种图标宽高放大；真实鼠标协议点击目录行后列表折叠，原图区域无残留；再次点击展开后图标恢复，长列表滚动仍对齐。证据位于 `.tmp/icon-ghost-fix/`：`large-settled.png`、`folded-click.png`、`restored-click.png`、`scrolled.png`。`folded.png` 不是有效折叠证据：键盘 h 在子会话行不折叠，之后已改用真实目录行点击。

最终版本启动后无需点击即可显示三类放大图标，证据为 `.tmp/icon-ghost-fix/final-startup.png`。自建窗口 508 与独立 socket 已回收，iTerm2 只剩原窗口 72；用户三个 client 的 TTY／session 绑定及全局 `allow-passthrough off` 保持不变。文档链接与 `git diff --check` 检查通过。

未覆盖：zoom 恢复、多个不同尺寸 client 同时注视的图片外观与长时间运行；不据有限截图声称全部残影场景已消除。协议尺寸语义核对 [iTerm2 官方图片协议](https://iterm2.com/documentation-images.html) 。

## 2026-10-05 18:36：缩略图与正式侧栏接入

沿用 iTerm2 3.7.3／tmux 3.7c；正式运行仍仅依赖 Textual，没有安装系统级工具、替换 tmux 或新增正式图片依赖。

- **小图原型可按需显示**：样例编码从约 74 KB 降到约 5 KB。相同独立 pty 探针中，滚动捕获从 1,103,925 字节降到 103,758 字节；这是同一探针的输出量对照，不是吞吐或延迟基准。末张图片之后未再捕获到擦除图片位置的文本重绘，空闲两秒输出为零。真实截图 `thumbnail-scroll.png`、`thumbnail-restored.png` 确认滚动第 11～16 行图标及折叠恢复后的对齐；文件位于 `.tmp/sidebar-image-probe/`。大图透传后的延迟重绘与 tmux 缓冲行为相符，但未取得 tmux 内部调试日志，不能认定已追踪到具体分支。
- **正式资源与界面**：`assets/` 中三张 32 × 32 PNG，单张 Base64 为 1,648～3,088 字节。Codex 按用户参考使用 OpenAI 结形图形，Claude 使用官网图标，Shell 为项目绘制的终端窗口图案；资源来源随包保存。子会话行预留两列宽、一行高，只发送可见区域内图标；未知身份与不可用图片条件保持字符和名称。
- **正式宿主集成**：独立 socket 确认 pane 级 `allow-passthrough` 可用，全局值仍为 `off`；正式代码仅设置本实例自建 pane，迁移保留该选项。读取 pane 偏移、顶部 status 和 window ID；不可见、zoom 或 client 裁剪窗口时停止透传。Textual 帧后通过同一 driver 队列叠图，不透传光标恢复。
- **空闲问题定位与修复**：首次真实 pty 回归发现 `Static.update` 在文字内容不变时仍导致周期重绘及图片重传；正式界面增加文字内容比较，未变化不提交新帧。单元测试核对无重复更新，真实 pty 的三秒空闲采集确认没有图片输出。
- **采集边界**：固定二／三秒采集曾出现迁移或帧尾断言不稳定。保留 pty 输出诊断后，夹具改为等待完整 OSC 包并且输出安静 0.3 秒（上限 20 秒），没有放宽三类资源、末图后无覆盖文本、空闲无图或迁移断言。诊断记录中八张图片共 23,008 字节，末图之后仅 139 字节终端控制序列；原始证据在 `.tmp/sidebar-icons/formal-frame.bin`。
- **最终验证**：`AGENT_TREE_RUN_TMUX_TESTS=1 PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -t tests` 共 192 项全部通过，无跳过。新增真实 pty 用例验证三种图片数据、完整包、末图之后没有覆盖图标行的名称重绘、空闲、同尺寸切窗补画、用户 pane 未设置透传以及 q 后用户 pane 保留；headless 验证滚动、折叠、窄栏、未知身份和偏移。`git diff --check` 与受影响文档本地链接检查通过。

限制：正式版独立 iTerm2 窗口已启动并通过文本快照确认三类条目，但 `screencapture` 对窗口和显示屏均无法生成截图，未确认原因，因此未认定正式版的真实外观、残影或缩放恢复通过。原型截图不能替代正式侧栏外观验收。当前没有重新启动用户既有侧栏；需 q 后重启加载源码。安装 wheel 内资源未独立构建验证，已声明 package-data 并验证源码运行资源读取。

清理：自建预览窗口 470 与 socket `agent-tree-icons-20261005` 已退出；原型 socket 无 server，iTerm2 只剩用户原窗口 72。用户 client `/dev/ttys000 → 0`、`/dev/ttys002 → 3`、`/dev/ttys004 → 2` 保持一致，默认 server 全局 `allow-passthrough off` 未改变。完整回归的独立 socket／pty 由夹具清理。

## 2026-10-05 18:03：图片显示失败的对照定位

沿用 17:45 的环境与原始 PNG 样例，新增原始终端协议对照、独立 pty 外层输出捕获，以及 Textual 重绘对照；没有改动正式源码、依赖或用户配置。

### 已确认结果

- **全屏模式不是阻塞项**：不使用 Textual 的 alternate screen 对照中，裸 OSC 1337 图片透传正常显示；tmux 原生光标定位后仅透传图片也正常显示。截图为 `.tmp/sidebar-image-probe/phase-1.png`、`phase-2.png`。
- **透传内的光标恢复是一个明确触发条件**：把终端原生 `ESC 7`、CUP、图片与 `ESC 8` 一起透传时，截图没有图片；让 tmux 处理光标保存／定位／恢复、只透传图片时显示成功。Textual 原型移除透传内的 `ESC 8` 后，初始列表六个完整可见图标成功显示，截图为 `.tmp/sidebar-image-probe/no-restore.png`。这些对照确定了可规避的触发条件，尚未追踪到 iTerm2 内部为什么在光标恢复后丢失图片。
- **定位指令需要考虑外层终端状态**：tmux 3.7c 的 `tty_cmd_rawstring` 直接转发数据并使 tty 状态缓存失效，不自动把图片定位到 pane 光标。本轮在完整窗口的自建 pane 内验证，正式侧栏需要额外处理 pane 偏移与跨 window 迁移。
- **滚动后需要重新补画**：仅根据列表坐标和选中项缓存图片绘制结果，滚动后的截图再次没有图片；跟随 Textual `_display` 使用同一 driver 输出队列也未完全解决。每 0.3 秒持续补画的诊断对照中，第 11～16 行图片重新显示且对齐，截图为 `.tmp/sidebar-image-probe/continuous-scroll.png`。因此只能认定原型显示路径可行，不能认定按需重绘已经稳定。
- **折叠清理通过有限验证**：此前能显示初始图标的原型折叠列表后，截图中没有残留图标，证据为 `.tmp/sidebar-image-probe/fixed-fold.png`；连续补画版本没有独立完成折叠回归。

### 限制与后续

持续补画会反复传输完整样例 PNG；本轮截图命令曾等待超过 10 秒，不能将该对照方案作为可交付的性能实现。已停止该诊断，并取消 launcher 默认开启持续补画。下一步应解决图片对 Textual／tmux 后续重绘的失效通知与补画时序，再以小尺寸正式图标验证性能；无需仅因为初版失败就判定必须替换 tmux。部分可见图片裁切、三类正式素材、真实身份动态切换、窄栏、迁移与无损退出的图片验收仍未完成。

清理：三个自建 socket `agent-tree-image-probe-20261005`、`agent-tree-image-isolate-20261005`、`agent-tree-image-wire-20261005` 均无 server；自建窗口 431、439、443、449、450、454 均已消失，iTerm2 只剩原窗口 72。原有三个 tmux client 的 TTY、终端类型与 session 绑定一致，原 server 的全局 `allow-passthrough` 仍为 `off`。

源码依据：[tmux 3.7c 原始透传实现](https://github.com/tmux/tmux/blob/3.7c/tty.c#L2037) 。本地 Textual driver 的 `write()` 使用 writer thread 队列；原型将图片放入该队列，但目前没有因此获得完整滚动验收。

## 2026-10-05 17:45：真实图片图标可行性原型

环境：iTerm2 3.7.3、tmux 3.7c、项目现有 Textual；图片库 textual-image 0.14.0 与 Pillow 12.3.0 仅装入 `.tmp/sidebar-image-probe/deps`，没有加入正式依赖。使用用户上传的完整截图作为 PNG 样例，没有制作正式 Codex／Claude／Shell 素材。

使用独立 socket `agent-tree-image-probe-20261005`，仅对自建测试 window 开启 `allow-passthrough`。通过 iTerm2 原生脚本接口指定测试命令，避开默认 profile 的 tmux 启动命令；没有修改 profile 或用户 tmux 配置。

- **普通终端画面通过**：OSC 1337 `File=inline=1;width=4;height=2` 经 tmux DCS 透传，真实窗口截图确认 PNG 显示。截图保留在 `.tmp/sidebar-image-probe/baseline.png`。
- **本机原生 Sixel 路径不可用**：独立 server 的 `display-message -p '#{sixel_support}'` 返回 `0`，终端响应探针也未报告 Sixel。给独立 server 声明终端 sixel 特性不能替代 tmux 编译支持。
- **Textual 行内原型未通过**：同步渲染控制序列与文本帧之后定时叠加两种原型均执行过；截图中会话名称可见，但没有稳定保留图片。样例采用 30 行列表、4 列 × 2 行图片区；未确定图片消失的完整根因，不能断言正式侧栏支持图片。证据为 `.tmp/sidebar-image-probe/inline-rows.png` 与 `.tmp/sidebar-image-probe/overlay.png`。
- **图片库启动边界**：能力探针曾因逐字节 UTF-8 解码抛出 `UnicodeDecodeError`；原型改为读取完整字节串，未修改上游库或正式源码。
- **清理通过**：原型发送 `q` 后独立 socket 无 server；iTerm2 窗口列表中自建窗口 ID 404、418、420、425、426、427 均已消失。用户原有三个 client 的 TTY、终端类型与 session 绑定保持一致。

结论：仅证明普通画面的图片透传可行，不接入正式侧栏。下一步建议使用开启 Sixel 编译支持的隔离 tmux 构建验证 Textual 原型；未修改或安装系统 tmux。滚动残影、折叠清理、窄栏裁切、跨 window 迁移及退出恢复均未完成图片验收。

协议依据：[iTerm2 图片协议](https://iterm2.com/documentation-images.html) 、[iTerm2 原生脚本接口](https://iterm2.com/documentation-scripting.html) 、[textual-image 的 tmux 支持与限制](https://github.com/lnqs/textual-image#tmux) 。上游支持声明不替代本机验收。

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
