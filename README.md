# 算法社团训练台

**A-Algorithm-Club-Training-Platform**

This project was born out of the need to make it easier to compile statistics on members’ training records and to encourage club members to train themselves.

这是一个 Django + PostgreSQL + Celery 的团队训练平台。当前版本保留了原有前端视觉，并提供团队、学期、周次、提交审核、展示权限、排行榜、成员历史和 Excel 导出接口。

## 界面展示

### 训练总览

工作台以当前周训练目标、积分进度和下一步提交动作作为入口。

![训练总览](docs/screenshots/dashboard.png)

### 提交成功反馈

提交成功后，页面会显示明确的反馈状态，并将记录送入审核队列。

![提交成功](docs/screenshots/submission-success.png)

### 管理员审核工作台

管理员可以集中处理待审核提交、查看材料并配置展示权限。

![管理员审核工作台](docs/screenshots/admin-review.png)

### 提交展示

团队成员可以在权限允许的范围内浏览已通过的训练材料。

![提交展示](docs/screenshots/showcase.png)


## 本地启动

1. 安装 Docker Desktop，并确保代理可以拉取 Docker Hub 镜像。
2. 复制 `.env.example` 为 `.env`，替换密钥和数据库密码。
3. Windows 推荐运行 `powershell -ExecutionPolicy Bypass -File deploy/start.ps1`。脚本会自动使用稳定的传统构建器。
4. 访问 `http://localhost/`。
5. 创建管理员：`docker compose -p club-platform exec web python manage.py createsuperuser`。

开发团队可以用 `docker compose -p club-platform exec web python manage.py seed_demo` 创建演示团队，账号为 `林同学`，密码取命令参数默认值。演示团队的普通加入密码默认是 `join-me-2026`，管理员邀请码默认是 `admin-me-2026`；不填写或填写错误的管理员邀请码只会以普通成员加入。

## 正式部署

将项目上传到 Debian 12 服务器，配置 `.env` 中的域名和密码，开放 80/443 端口后运行 Docker Compose。Nginx 负责反向代理和媒体文件，PostgreSQL、Redis、Celery Worker/Beat 由 Compose 管理。

生产环境 `.env` 至少需要设置：

```dotenv
DJANGO_ALLOWED_HOSTS=redbloodcell.cn,www.redbloodcell.cn
DJANGO_CSRF_TRUSTED_ORIGINS=https://redbloodcell.cn,https://www.redbloodcell.cn
DJANGO_SECURE_COOKIES=1
DJANGO_SECURE_SSL_REDIRECT=1
DJANGO_HSTS_SECONDS=31536000
```

如果前面使用 Cloudflare，请将 SSL 模式设为 Full (strict)，并确保 Cloudflare 的 `X-Forwarded-Proto` 被 Nginx 转发给 Django。

更新前端或后端后，需要重新构建 Web、Worker、Beat 镜像并重启 Compose 服务；只替换浏览器里的 HTML 不会更新服务器数据库接口。

HTTPS 证书可以用 Certbot 写入 `deploy/certbot/conf`，证书更新后重新加载 Nginx。

## 重要规则

- 周次使用 `Asia/Shanghai`，每周一 00:00 开始，周日 24:00 截止并切换到下一周。
- 截止后禁止向该周提交；截止前提交的材料仍可审核，计分归入原周次，并同步更新学期累计与达标周数。
- 截图、写题逻辑、Blog 独立审核和计分。
- 团队级展示权限统一控制；管理员始终可见，成员在“仅管理员可见”模式下仍可查看自己的材料。
- 学期结束 30 天后由 Celery 自动清理提交详情和媒体文件，保留成员姓名、学期累计积分、有效提交次数与达标周数。归档后不可再审核，历史页面和 Excel 导出读取归档汇总。


## 本次修复的升级步骤

升级前备份数据库和媒体文件，暂停 Worker / Beat，先更新 Web 并执行迁移，再审核旧周次。本文命令中的 Compose 项目名必须与已有部署一致；本地脚本使用 `algorithm-club-local`。

1. 执行 `python manage.py migrate`，新增归档标记、姓名快照和清理文件清单；已完成的旧清理任务会保留其归档分数。
2. 执行 `python manage.py repair_weeks`。默认只报告周次日期和提交归属差异，不写数据库。
3. 对报告中的每个学期检查结果后，执行 `python manage.py repair_weeks --semester 学期ID --apply`。命令按上海时区的提交时间重算归属，修正周次和结算状态，并刷新统计；若有效提交时间超出学期范围，则整次操作回滚，留待人工核对。已归档学期不会重算。
4. 执行 `python manage.py collectstatic --clear --noinput`，删除旧版本错误收集的源码。Compose 的 Web 启动命令已包含此步骤。前端根目录文件仍通过明确列出的页面/资源路由提供，新增可收集资源仅放入 `static/`。
5. 更新并重新加载 Nginx 配置，再恢复 Worker / Beat。周次日期异常的学期会暂停自动结算和归档，并在任务返回值 `needs_week_repair` 中报告；提交接口也会拒绝异常周次。

Compose 自动设置 `DJANGO_USE_X_ACCEL_REDIRECT=1`。附件经 `/api/attachments/材料ID` 验权后由 Nginx 内部路径发送；旧 `/media/` 链接及直接访问内部路径均返回 404。直接运行 Django 时默认由 Django 发送附件，同样检查权限。不要重新开放媒体目录或通过 CDN 缓存附件。

提交 API 现在要求表单携带 `week_id`。前端在打开提交窗口时固定目标周次，跨过截止时间后不会把旧表单悄悄计入下一周。截图验证真实图片内容；Blog 仅接受 HTTP/HTTPS 链接。

归档先在事务内保存汇总、文件清单并删除明细，再删除附件。文件删除失败会保留清单，定时任务重试时不会重新计算已经归档的分数。修复无法恢复旧版本已经删除的明细；发现旧汇总异常时需要从备份核对。

## 回归测试

使用独立 PostgreSQL 测试数据库执行 `python manage.py test club`。覆盖截止边界、跨团队/空目标审批、并发审核与归档、私密附件、图片校验、历史日期修复和清理重试。测试不得指向生产数据库账号。
