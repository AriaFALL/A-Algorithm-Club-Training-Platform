# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

算法社团队员在日常训练中使用平台记录每周训练材料、查看审核状态、跟踪积分与排名。团队管理员处理提交审核、展示权限和每日擂台。

## Product Purpose

平台把截图、写题逻辑和 Blog 等训练材料组织成每周训练闭环，帮助队员持续完成训练并让团队看见进步。成功表现为队员能快速找到下一步行动，管理员能顺畅处理审核队列。

## Positioning

以提交材料换取训练积分，把个人训练过程转化为团队可追踪的节奏、反馈和长期记录。

## Operating Context

用户通过浏览器访问平台，按团队、学期和周次工作。典型流程包括登录、选择团队、查看本周进度、提交材料、等待审核、查看排行榜和成员历史。

## Capabilities and Constraints

- 支持账号登录、注册、创建团队和加入团队。
- 支持总览、我的提交、排行榜、每日擂台、提交展示、成员列表和管理员审核工作台。
- 提交材料包括通过截图、写题逻辑和 Blog；审核结果会影响积分与展示权限。
- Django、数据库、API、权限、业务规则和现有数据字段保持兼容。
- 前端使用现有静态 HTML、CSS 和 JavaScript 文件。

## Brand Commitments

- 产品名称为“算法社团训练台”。
- 语气清晰、鼓励持续训练，使用中文产品术语。
- 视觉方向为浅色、鲜艳但不刺眼、优雅且有活力。

## Evidence on Hand

- 主工作台：`index.html`、`styles.css`、`app.js`。
- 鉴权与团队流程：`auth.html`、`register.html`、`team-select.html`、`create-team.html`、`join-team.html`。
- 现有 API 传输层：`api.js`。

## Product Principles

- 让队员先看见下一步行动。
- 用真实训练状态建立反馈，而不是用装饰替代信息。
- 让每周节奏、审核状态和团队进步可被快速扫描。
- 保持高频操作直接、可预测、可恢复。
