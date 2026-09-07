# 阶段 3.1：客户 / 坐席双端设计

日期：2026-09-06。交付属性：设计提案与独立离线原型，不是生产功能完成声明。

## 1. 授权边界与交付方案

本次只新增 `docs/product/` 与 `design/phase-3.1/` 文件。不修改 Vue、Flask、业务状态、数据库、环境配置，不启动业务服务，不调用模型或真实 API，不提交或推送 Git，不使用浏览器工具。

沿用已明确的客户 `/chat`、坐席 `/agent/login`、`/agent/inbox`、`/agent/review` 双端边界。选择零依赖 HTML/CSS/JS、hash 路由、内存虚构数据，避免误接现有服务。相比直接重构 Vue（超出 3.1）或纯图片（无法验证操作语义），静态可点击原型既隔离业务，又能交付交互。品牌“知序”、所有人物、评分、时间和回复均为演示构造。

执行分解：只读代码检查 → 明确路由与 API 缺口 → 原型状态函数测试 → 四页交互与响应式 → 语法、资源和新增范围检查。运行方式及逐步验收见 `design/phase-3.1/README.md`。

## 2. 现状代码依据

下表行号对应本次只读检查版本；路径均相对项目根 `E:/mye盘项目/jianli project/customer-service-ai-agent/`。历史设计文档不等于当前实现，以下以代码为准。

| 文件 / 行 | 当前实际能力 | 双端设计影响 |
|---|---|---|
| `frontend/src/App.vue:1-25` | 所有页面共用客户聊天、工单台、会话回放导航；挂载就调用 `store.startSSE()` | 客户端不得共享内部导航或启动工单队列 SSE；后续拆 CustomerLayout / AgentLayout |
| `frontend/src/router/index.js:6-12` | history 模式，仅 `/`、`/tickets`、`/sessions`，没有登录路由或守卫 | 四个目标路由是待实现方案，而非当前可用业务 URL |
| `frontend/src/views/ChatView.vue:13-65,72-99` | 拉会话列表、读取历史、删除/清空；同步 `sendMessage`，消息只有用户/非用户分组 | 客户应只见所属会话；不能把内部会话枚举当客户入口；缺人工等待状态及人工角色标识 |
| `frontend/src/views/TicketsView.vue:17-39,65-77` | 打开抽屉即预填 AI 草稿，提交后关闭；有 loading 和 degraded 提示 | 设计改为显式采纳、编辑、预览确认；原型不改现有提交行为 |
| `frontend/src/views/SessionsView.vue:10-35,57-65` | 展示 conversation_history 与 decision_trace；已映射 classify / quality_check / handoff / suspended / final_response | 可复用事件阅读结构，但人工采纳、修改、提交审计不在现有轨迹契约中 |
| `frontend/src/stores/tickets.js:7-28` | 单例 EventSource，收到 init/update 改角标；仅有 new_ids 且有 callback 才通知刷新；无 stop 方法 | App 首次无 callback 建连接；后续 startSSE 会提前返回，TicketsView 也未注册更新回调，不能声称列表实时刷新已完善 |
| `frontend/src/api/index.js:3-14` | axios 同步聊天、会话列表/详情/删除/清空、工单列表/resolve | 没有登录、客户消息订阅、工单详情封装、认领或保存草稿封装 |
| `web_app.py:59-78` | frontend/dist 静态托管与 history fallback，api 前缀排除 | 将来可承载新前端路由；原型不需要构建 dist |
| `web_app.py:81-117,124-189` | chat 返回 response/session_id/thread_id；chat/stream 为 POST；会话读写接口存在 | 没有统一 customer service_state；new_session 创建 Flask 侧占位 ID，不应未经确认等同 LangGraph thread |
| `web_app.py:211-269` | 工单列表仅支持 open/resolved 筛选；详情；工单 SSE；resolve 先写线程再关闭工单，失败可返回 degraded=true | “工单已处理”不等于“客户已收到”；必须区分投递状态与工单状态 |
| `chat_web_service.py:54-68,304-343,354-390` | 非用户轮次统一 role=assistant；线程搜索 json={}，详情带 decision_trace | 已检查链路没有用户所有权筛选，不能作为生产权限边界；human 角色会丢失 |
| `chat_web_service.py:447-535,538-629` | 同步/流式均触发 LangGraph run；stream 轮询后产出完整回答并结束 [DONE] | 不是持续客户消息订阅，也不是逐 token 实时生成保障 |
| `chat_web_service.py:632-657` | 每约 2 秒轮询 open IDs，仅推 init(open_count)、update(open_count,new_ids) 或 error | **工单 SSE 是队列变化，不是客户人工消息实时通道**；无正文、thread 定向投递、事件 ID 或补发游标 |
| `chat_web_service.py:660-682` | 人工回复追加 persisted_dialogue，is_user=false，并以 final_response 写回 state | 没有独立 message_id、author_kind=human、delivery_status；无法可靠区分人工与 AI |
| `ticket_store.py:13-27,62-83,106-132` | SQLite 字段含草稿、评分、理由、quality_dims、open/resolved、人工回复；条件 UPDATE 防止重复关闭 | 无 assignee、版本号、草稿保存、投递状态与审计表；条件 UPDATE 不覆盖此前外部写回的竞态 |

安全结论只针对检查过的上述应用链路：未见登录、角色鉴权和会话所有权校验。前端隐藏入口不能替代服务端鉴权。`_current_thread_id` 为模块全局（chat_web_service.py:37-47、447-464），多客户隔离需要专项核查；本阶段不修复。

## 3. 信息架构与角色权限

| 目标业务路由 | 访问身份 | 页面内容 | 禁止内容 |
|---|---|---|---|
| `/chat` | 客户身份 / 将来受约束的访客会话 | 当前咨询、AI/人工消息、等待状态、输入区 | 工单列表、其他客户历史、草稿、质检分、内部决策、坐席导航 |
| `/agent/login` | 未登录坐席 | 登录说明与身份入口 | 真密码出现在原型中、暗示演示登录已经安全 |
| `/agent/inbox` | 已鉴权坐席 | 左队列、中会话与编辑、右质检和轨迹 | 未确认即发草稿、越权客户资料 |
| `/agent/review` | 已鉴权坐席 / 后续独立复盘权限 | 只读对话、分类/质检/人工事件 | 修改历史、删除审计或重新提交已结工单 |

原型 URL 为 `index.html#/chat` 等 hash 地址；直接访问坐席受限页会进入模拟登录，勾选声明即可进入，刷新恢复未登录。顶端“原型演示入口”是评审控制条，不属于生产客户导航。四页在同一标签内共享虚构内存，DEMO-101 人工提交可在客户演示页看到；不同标签不互通。状态下拉是展示控件，不代表服务器流转。

后续路由兼容建议：`/` → `/chat`；`/tickets` → `/agent/inbox`；`/sessions` → `/agent/review`，坐席重定向必须先经过真实身份验证。3.1 未实施任何业务重定向。

## 4. 页面与视觉规范

- 风格：克制企业服务风格，低饱和蓝灰，白色操作面板，颜色辅助状态但不独立传意；不使用夸张渐变、大面积高饱和背景或无意义图表。
- 颜色：背景 `#f2f5f7`、面板 `#ffffff`、正文 `#172b3a`、次级 `#617381`、主操作 `#245a78`、线框 `#dce4e9`；等待琥珀色、完成绿色，均有文字标签。
- 字体：系统字体 / Microsoft YaHei；正文 14px / 1.6，说明 12px，标题 19–27px；手机表单 16px 避免输入缩放。
- 间距：基准 8px，面板内距 16/24px；控件圆角 7px，卡片 12px；主按钮每个操作区保持一个。
- 桌面处理台：≥1180px 三栏，280px 队列 / 弹性会话 / 310px 依据；超宽限制 1800px。客户页为服务说明 + 独立聊天卡片。
- 761–1179px：队列 260px、中栏弹性；右栏移到详情下方，默认折叠，原生 details 可展开。无需水平拖动才能回复。
- ≤760px：客户隐藏装饰说明，聊天单栏、输入安全区；坐席队列变横向可滚动卡片，中栏和折叠依据纵向排列，复盘单列，登录单列。
- 可访问性：真实 button / label / select / dialog / details；焦点轮廓；消息 log、反馈 status；弹窗可取消/Escape；支持键盘输入和中文组合输入；动画尊重 reduced-motion。控件触达与色彩对比、焦点恢复及软键盘遮挡仍须后续真实设备验收。

## 5. 交互语义与状态矩阵

### 客户服务状态（与工单状态分离）

| 状态 | 可见文案/消息 | 输入与动作 | 转移 |
|---|---|---|---|
| normal | 智能助手为您服务，AI 身份标识 | 可输入；空白不发；Enter 发、Shift+Enter 换行 | 演示下拉 → waiting/human；发消息只生成固定模拟回复 |
| waiting | 已转交人工、无虚构 SLA/队列名次 | 原型禁用发送，防重复咨询；已有输入切状态须确认丢弃 | 演示下拉或 DEMO-101 坐席提交 → human |
| human | 人工客服已回复，明确人工署名 | 可继续咨询；后续一轮由 AI 接待 | 发消息 → normal |

等待期间能否追加消息需要 3.2 契约确认；3.1 采用保守禁发，不暗示后端已支持人工多轮接管。原型下拉可任意切展示，既不创建工单也不回滚工单状态。

### 坐席编辑/提交

| 状态 / 动作 | 原型行为 | 生产约束 |
|---|---|---|
| open 未编辑 | 草稿独立内部卡片，编辑器为空；提交禁用 | 不在客户对话里渲染内部草稿 |
| 采纳草稿 | 仅填编辑器，记录 draft_adopted；已有内容先确认覆盖 | 采纳绝不调用 resolve |
| 编辑中 | 显示未提交；允许修改；空白提交禁用 | 将来草稿若落库需 owner 与 revision |
| 切换工单/路由/退出/状态 | 弹窗取消留在原处，确认才丢弃；刷新/关闭触发 beforeunload | 浏览器原生离开提示行为由浏览器决定 |
| 搜索/筛选 | 按客户、问题、编号搜索，all/open/resolved 筛选；无结果有清除入口 | 筛选不自动切换详情、不丢未保存内容；真实分页由后端承担 |
| 预览确认 | 显示客户、工单编号、最终全文；取消保留编辑；确认才提交 | 防止把未经修改草稿误当已核实内容 |
| submitting | 前端互斥标志与按钮禁用，确认窗口不能重复打开 | 必须有服务器幂等键与原子状态检查，不能只防双击 |
| resolved | 只读人工回复、禁止再次提交、可进入复盘 | 服务端 409 时刷新状态、保留待比对文本 |
| 投递失败 / degraded | 设计态：工单已处理但客户未收到，不显示送达成功 | 生产需明确恢复动作、幂等补投、审计；原型不模拟真实失败网络 |
| 网络异常/断连 | 设计态：保留编辑、标注未送达、允许明确重试 | 不能将 SSE transport onopen 当业务健康；不自动重发有副作用请求 |

原型没有真实异步请求，确认后同步本地提交；防重依靠互斥标志和 open→resolved 检查，不能证明分布式幂等。客户输入和回复均做 HTML 转义，只作为纯文本渲染，不支持富文本或附件。

### 复盘事件

初始虚构事件：classify → quality_check → handoff → suspended；历史完成工单含 human_submitted。当前操作会追加 draft_adopted、human_submitted，带本地演示时间；编辑动作本身不形成持久审计。只读复盘可选工单，分开显示客户消息与内部事件。后续建议补 draft_edited、submit_requested、delivery_succeeded/failed、ownership_changed，字段至少 event_id、ticket_id、thread_id、actor、timestamp、版本号、关联 message_id；这些均不是当前接口已有字段。

## 6. API 能力与缺口交接

| 能力 | 现有接口 | 必须补齐 / 明确 |
|---|---|---|
| 客户聊天 | POST `/api/chat`；POST `/api/chat/stream` | 返回独立 service_state、author_kind、message_id；会话所有权与请求隔离；客户端消息幂等键 |
| 客户人工消息到达 | 无对应常驻订阅 | 新增受身份约束的会话消息通道，或先用详情轮询并按 message_id 去重；不得订阅全局工单 SSE 给客户 |
| 会话历史 | GET `/api/sessions`、`/api/sessions/<id>` | 客户只可读自己的会话；坐席按权限范围读取；脱敏、分页；保留 human/ai 区别 |
| 工单队列 | GET `/api/tickets?status=open|resolved` | 搜索分页、认领/归属、版本、状态刷新；不能假定客户端全量过滤可生产使用 |
| 工单详情 | GET `/api/tickets/<id>` | 可复用字段；quality_dims 当前为 JSON 文本/空值，适配解析且不可伪造缺失维度 |
| 队列实时 | GET `/api/tickets/stream` | 限坐席权限；连接释放、业务 error 显示、重连后全量校准、解决仅关闭时列表刷新；无变化不发心跳也需治理 |
| 人工处理 | POST `/api/tickets/<id>/resolve`，body human_reply | 工单与外部会话写入一致性、服务端幂等、degraded 补偿与最终投递可观测 |
| 登录权限 | 所检查路由中无 | 坐席认证、客户会话身份、后端 RBAC/所有权、CSRF/会话配置、退出撤销；前端守卫只是体验 |
| 复盘 | 详情 decision_trace | 人工操作审计与投递轨迹、消息作者；不能把本地原型事件当真实审计 |

**最重要的实时性界线**：工单 SSE 的 update 只带 open_count 和 new_ids，即使人工处理使 open 数量下降，也没有客户消息正文或送达确认。`POST /api/chat/stream` 是一轮 run 完成后的有限流，也不会在结束后接收人工回复。客户展示“人工回复已到达”必须建立独立可靠的消息读取/推送与去重链路。

**提交竞态**：当前 Flask 先 get_ticket 检查 open，再 inject_human_reply，最后条件 UPDATE；两个请求可能都在 UPDATE 前写入线程。SQLite 条件更新防止重复关闭，不保证回复恰好一次。且写线程失败后仍关闭工单；必须分别建模 ticket.status 与 delivery.status，不能把 HTTP 200 或 resolved 当送达证据。

## 7. 3.2–3.5 建议交接（本次不执行）

以下为建议拆分与验收门槛，不宣称存在已批准的后续阶段实施授权。

| 阶段 | 建议工作 | 开始/完成门槛 |
|---|---|---|
| 3.2 契约与身份边界 | 确认四路由、客户会话所有权、坐席认证、角色字段、服务状态、waiting 追加消息策略、投递幂等协议 | 先人工审阅本设计；有脱敏 fixture、权限负例、契约测试；不凭 UI 推断已有能力 |
| 3.3 客户端实现 | Vue CustomerLayout、/chat、消息角色、等待态、消息读取/订阅与补拉 | 不加载全局工单 SSE；手机适配与断线/重发去重通过；客户无法读其他会话 |
| 3.4 坐席实现 | AgentLayout、login/inbox/review、三栏、编辑保护、确认防重、队列 SSE 生命周期、人工审计 | 真鉴权前不得发布内部页；并发 resolve、degraded、409、重连覆盖；草稿不直接发送 |
| 3.5 联调验收 | 以隔离测试数据走 AI→转人工→人工提交→客户到达→复盘，补无障碍与设备验收 | 单测/集成/浏览器人工验收证据；无真实数据；投递失败可恢复，权限与幂等有后端证据 |

## 8. 原型验收与已知局限

交付四页、客户三态、三栏坐席与窄屏折叠、搜索筛选、采纳/编辑/确认、防重复、未保存提示、复盘事件。代码使用本地 CSS/JS，无 fetch、XHR、EventSource、WebSocket 或外部 CDN；CSP connect-src 'none' 禁止联网。

验证采用 Node 语法检查、独立状态单测与文件检查，不导入业务 Python、不连接数据库、不运行应用健康/模型测试。禁止浏览器工具，因此没有截图、真实点击、布局像素、屏幕阅读器或移动设备软键盘验收结论。测试不是 DOM 端到端测试。原型只在当前标签内存保存，刷新重置；没有真实登录、分配、草稿持久化、消息实时投递、超时/失败模拟、跨标签同步或审计安全保障。
