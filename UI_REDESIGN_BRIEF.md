# Pulse Atlas 前端设计与后端对接交接单

> 版本：2026-10-03  
> 适用范围：静态前端页面、浏览器交互和现有 Django API 的联调  
> 设计原则：只改变前端表现和交互，不改变后端业务事实

## 1. 选定的整体风格

Pulse Atlas 将算法训练表现为一条可追踪的每周节拍：用户进入页面后先看到当前周次、积分完成度和下一步提交动作，再查看审核、排行榜和团队内容。

- 视觉基调：浅色、鲜艳、优雅、有活力；以暖白/薄荷背景承载内容，以深绿蓝文字建立锚点。
- 结构语言：开放式信息行、轻量分隔线、少量任务卡和一个具有记忆点的训练舞台。
- 关键组件：`TRAINING ATLAS` 当前周舞台、`WEEKLY PULSE` 周次节拍带、审核状态节点、提交成功反馈层。
- 动效语言：页面切换、周次选择、提交成功、审核通过各自独立；动效不改变布局尺寸，不阻塞后续操作。
- 禁止事项：不使用装饰性假数据替代真实状态，不新增 API，不通过前端绕过权限，不把玻璃拟态卡片作为默认容器。

## 2. 色板和语义颜色

| Token | 色值 | 使用语义 |
| --- | --- | --- |
| `--canvas` | `#f5fbf8` | 页面主背景 |
| `--panel` | `#ffffff` | 表单、弹窗和需要明确边界的任务表面 |
| `--ink` | `#173b38` | 正文和导航文字 |
| `--ink-strong` | `#102e2c` | 页面标题和关键数字 |
| `--muted` | `#6b8580` | 时间、说明和辅助信息 |
| `--line` | `#dcebe5` | 分隔线、输入框边框 |
| `--teal` | `#1fb39f` | 主操作、已通过、完成进度 |
| `--teal-dark` | `#087d73` | 主操作悬停、强调文字 |
| `--coral` | `#f17f72` | 截止临近、退回、错误 |
| `--lemon` | `#f2ca57` | 待审核、里程碑、积分节点 |
| `--blue` | `#5a8ff0` | 未来周、排行榜数据、辅助操作 |
| `--violet` | `#8b78d5` | 提交展示筛选和内容类型 |

颜色必须表达业务状态：灰色只表示次要信息，不能用鲜艳色装饰没有状态含义的内容。

## 3. 字体和字号层级

- 字体栈：`Aptos`, `Segoe UI`, `PingFang SC`, `Microsoft YaHei`, sans-serif。
- 展示标题：`clamp(29px, 3vw, 42px)`，字重 750，行高约 1.08。
- 页面标题：24–29px，字重 750，行高 1.2。
- 区块标题：16–20px，字重 700。
- 正文：14px，行高 1.5。
- 标签和元信息：9–12px，字重 700 或常规，适度字距；中文不得依赖过窄宽度显示。
- 标题、按钮、状态标签都必须允许换行或省略，不得裁切字符。

## 4. 页面布局

### 登录/注册与团队流程

- `auth.html`、`register.html` 使用 Pulse Field / Pulse Atlas 入口场景：桌面为左侧训练叙事、右侧表单；移动端隐藏叙事，仅保留完整表单。
- `team-select.html` 显示当前账号的真实团队列表；空列表时提供加入和创建团队入口。
- `create-team.html`、`join-team.html` 使用单列表单，创建团队的规则字段在桌面两列、移动端单列。

### 登录后工作台

- 固定侧边导航：总览、我的提交、排行榜、每日擂台、提交展示、成员列表；管理员额外显示审核工作台。
- 主内容顺序：当前周任务 -> 周次节拍 -> 指标 -> 最近提交/排行榜 -> 每日擂台。
- 移动端侧边栏收缩为图标轨道，内容区域单列；主要提交按钮全宽，表格/行内容允许横向安全折叠，不得遮挡状态标签。
- 弹窗只用于提交、审核详情和成员历史，关闭后焦点回到触发按钮。

## 5. 导航结构

| 导航项 | 页面状态 | 真实数据来源 |
| --- | --- | --- |
| 总览 | 当前周、积分、下一步行动 | `GET /api/dashboard`、`GET /api/submissions?mine=1` |
| 我的提交 | 当前成员提交历史 | `GET /api/submissions?mine=1` |
| 排行榜 | 本周/本学期切换 | `GET /api/leaderboard?scope=week|term` |
| 每日擂台 | 当前公开擂台或空状态 | `GET /api/arena` |
| 提交展示 | 团队可见的通过内容 | `GET /api/showcase` |
| 成员列表 | 成员进度和历史入口 | `GET /api/members`、`GET /api/members/<member_id>/history` |
| 管理工作台 | 审核、展示权限、擂台配置 | 管理员 API，服务端权限决定可见性 |

## 6. 按钮、切换、表格、卡片和表单规范

### 按钮与切换

- 主按钮使用青绿色实心，文字清晰描述动作，如“提交本周记录”“通过审核”。
- 次按钮为白色表面和细边框；文字按钮只用于次级导航。
- 排行榜、提交展示等 segmented 控件使用浅色轨道、实体胶囊和移动指示器；每个按钮保留 `aria-selected`。
- 所有按钮必须有 `type`，图标按钮提供 `aria-label` 或 `title`。
- 所有交互控件提供可见 `:focus-visible` 焦点环。

### 表格/列表

- 训练记录和审核队列使用开放式行：状态节点、成员/内容、时间、积分、状态标签、操作。
- 待审核使用柠檬/暖黄色，通过使用薄荷绿色，退回使用珊瑚色。
- 列表加载、空数据、网络错误必须有明确状态，不显示静态演示数据覆盖真实响应。
- 提交展示中的通过截图直接使用 API 返回的 `parts[].upload`；点击可打开审核详情查看大图。

### 卡片和表单

- 卡片只在任务需要边界时使用，圆角 10–18px，阴影克制。
- 表单字段使用真实 `name` 与后端字段一致；必填项使用原生 `required` 和可读提示。
- 提交表单字段：`proof`（文件）、`logic`（文本，可选）、`blog`（URL，可选）。
- 错误显示在表单附近并使用 `role="status"` / `aria-live`；请求期间禁用提交按钮，避免重复写入。

## 7. 移动端规则

- 基准视口：390px；不得出现横向页面滚动。
- 侧边导航折叠为 64px 图标栏，图标按钮保持足够触控尺寸。
- 两列规则表单在 600px 以下变为单列；工作台网格在 760px 以下变为单列。
- 长标题、成员名、状态标签允许换行；积分和关键状态不得被 `overflow:hidden` 截断。
- 提交、审核和关闭按钮在移动端全宽或保持最小 44px 触控高度。
- 周次节拍与 segmented 控件在必要时允许自身横向滚动，但不撑破页面宽度。

## 8. 必须保留的 API 和表单字段

### 鉴权和团队

- `GET /api/csrf`
- `POST /api/auth/login`：`account`, `password`
- `POST /api/auth/register`：`account`, `password`, `confirm_password`
- `POST /api/auth/logout`
- `POST /api/auth/join`：`team_code`, `join_password`, `name`, `admin_invite`
- `POST /api/auth/create-team`：`team_name`, `team_code`, `term_days`, `min_score`, `screenshot_points`, `logic_points`, `blog_points`, `join_password`, `admin_invite`
- `POST /api/team/select`：`team_id`
- `GET /api/me`

### 训练和内容

- `GET /api/dashboard`
- `GET|POST /api/submissions`：POST 使用 `multipart/form-data` 字段 `proof`, `logic`, `blog`；截图由后端校验 PNG/JPG/WebP 和 5MB 限制。
- `GET /api/showcase`
- `GET /api/leaderboard?scope=week|term`
- `GET /api/members`
- `GET /api/members/<member_id>/history?week=<number>`
- `GET|POST /api/arena`

### 管理员

- `POST /api/admin/submissions/bulk-approve`：`submission_ids`, `action`, `note`
- `GET|PUT /api/admin/team-settings`
- `GET|DELETE /api/admin/arena`
- `GET /api/export`

CSRF 和会话由 `api.js` 统一处理；不得在页面脚本中绕过 `clubApi.request` 直接写入业务 API。

## 9. 不允许修改的后端行为

- 不修改 Django URL、视图、模型、数据库字段、权限装饰器、序列化结构和审核/积分规则。
- 不新增后端接口，不在演示模式写入数据库。
- 服务器返回的权限结果优先于前端展示；管理员入口只由 `/api/me` 的角色结果决定。
- 截止周次的有效性、审核状态、积分发放、团队展示权限和清理策略全部由后端决定。
- 前端只负责把成功响应转换成反馈动画和稳定的页面状态；失败、401、403、409 必须显示错误且不能播放成功反馈。

## 10. 联调与验收清单

- `node --check app.js`、`node --check auth.js`。
- 登录 -> 团队选择 -> 总览路径可完成；无团队账号可进入创建/加入流程。
- 提交成功后顺序为：API 成功 -> 关闭弹窗/清空表单 -> 成功反馈 -> 刷新列表；失败不触发成功动画。
- 管理员单条或批量审批后，状态先完成动效，再刷新真实数据；审批失败不改变行状态。
- 桌面 1440px 和移动 390px 检查文字溢出、焦点环、空状态、加载状态、错误状态。
- 浏览器控制台无新增错误；静态演示只由 `?demo=1` 启用。
