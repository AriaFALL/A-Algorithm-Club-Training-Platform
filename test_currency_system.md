> 历史手工测试草稿：其中旧截图AI审核、跨月连签等说明不作为现行验收标准。当前规则以 README.md、docs/contest-calendar.md 及 docs/audits/2026-10-29-稳定性审查报告.md 为准。

# 货币系统测试指南

## 问题说明
之前的数据**没有被清理**！Docker重建使用了持久化卷(volumes)，所有数据都保存在：
- `a-algorithm-club-training-platform_postgres_data` - 数据库数据
- `a-algorithm-club-training-platform_media_data` - 媒体文件
- `a-algorithm-club-training-platform_redis_data` - Redis缓存

您的用户账户、团队和所有提交记录都完好无损。

## 货币系统开关位置

现在货币系统配置已经添加到**管理工作台 → 团队配置**中：

### 访问步骤：
1. 以系统管理员身份登录
2. 点击左侧菜单 **"管理工作台"** (⚙ 图标)
3. 滚动到 **"团队配置"** 部分
4. 点击你要配置的团队的 **"团队配置"** 按钮
5. 表单会展开，向下滚动找到 **"货币系统配置"** 部分

### 货币系统配置项：
- ✅ **启用 RBC 货币系统** - 复选框
- 💰 **每日签到奖励 (RBC)** - 数字输入框（默认1）

## 测试流程

### 1. 启用货币系统
```bash
# 登录系统管理员账户
# 进入管理工作台 → 团队配置
# 勾选"启用 RBC 货币系统"
# 设置"每日签到奖励"为 1
# 点击"保存团队配置"
```

### 2. 验证前端显示
启用后，刷新页面应该看到：
- ✅ 右上角出现 RBC Coins 余额显示
- ✅ 左侧菜单出现"RBC商店"入口
- ✅ 点击余额可以打开交易记录浮窗

### 3. 测试签到功能
```bash
# 作为普通团队成员登录
# 提交一条训练记录（截图/题解/Blog）
# 首次提交会自动触发签到
# 检查余额是否增加
```

### 4. 测试API接口
```bash
# 获取余额
curl -X GET http://localhost/api/currency/balance \
  -H "Cookie: sessionid=YOUR_SESSION_ID" \
  -H "Content-Type: application/json"

# 获取交易记录
curl -X GET http://localhost/api/currency/transactions \
  -H "Cookie: sessionid=YOUR_SESSION_ID"

# 获取商店商品
curl -X GET http://localhost/api/currency/shop/items \
  -H "Cookie: sessionid=YOUR_SESSION_ID"
```

### 5. 配置高级功能（可选）

启用货币系统后，系统会自动初始化：
- ✅ 默认连签奖励（7天+2, 30天+5）
- ✅ 默认比赛奖励（2题+1, 4题+2, AK+5）
- ✅ 默认补签券商品（3 RBC）

要自定义这些配置，可以通过以下API：

```javascript
// 在浏览器控制台执行
const response = await fetch('/api/currency/admin/config', {
  method: 'POST',
  credentials: 'include',
  headers: {
    'Content-Type': 'application/json',
    'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value
  },
  body: JSON.stringify({
    currency_enabled: true,
    daily_checkin_reward: 1,
    streak_rewards: [
      { days: 7, reward: 2 },
      { days: 30, reward: 5 }
    ],
    contest_rewards: [
      { problems_solved: 2, reward: 1, is_ak: false },
      { problems_solved: 4, reward: 2, is_ak: false },
      { problems_solved: 0, reward: 5, is_ak: true }
    ]
  })
});
console.log(await response.json());
```

## 常见问题排查

### Q: 看不到货币系统配置选项
A: 确保：
1. 以系统管理员(superuser)身份登录
2. 在"管理工作台"中打开"团队配置"
3. 点击具体团队的"团队配置"按钮
4. 向下滚动到表单底部

### Q: 启用后看不到余额显示
A: 检查：
1. 刷新页面（Ctrl+F5 强制刷新）
2. 打开浏览器控制台查看是否有JavaScript错误
3. 检查 `/api/currency/balance` 返回是否正常

### Q: 签到没有奖励
A: 确认：
1. 货币系统已在该团队启用
2. 是当天的首次提交
3. 查看交易记录确认是否已发放

## 数据库检查命令

```bash
# 检查团队货币配置
docker-compose exec web python manage.py shell -c "
from club.models import Team
for team in Team.objects.all():
    print(f'{team.name}: currency_enabled={team.currency_enabled}, reward={team.daily_checkin_reward}')
"

# 检查用户余额
docker-compose exec web python manage.py shell -c "
from club.models import CurrencyBalance
for balance in CurrencyBalance.objects.all():
    print(f'{balance.member.display_name}: {balance.balance} RBC')
"

# 查看交易记录
docker-compose exec web python manage.py shell -c "
from club.models import CurrencyTransaction
for tx in CurrencyTransaction.objects.all()[:10]:
    print(f'{tx.member.display_name}: {tx.amount:+d} RBC - {tx.get_transaction_type_display()}')
"
```

## 重要提醒

### 数据安全
- ✅ 所有数据都在Docker volumes中持久化存储
- ✅ 重建容器**不会**删除数据
- ⚠️ 只有运行 `docker-compose down -v` 才会删除volumes

### 货币图标上传
货币图标需要通过Django Admin上传，或直接复制到容器：
```bash
# 复制货币图标到容器
docker cp E:\Downloads\helloworld_coin.svg a-algorithm-club-training-platform-web-1:/app/media/currency_icons/
```

### 后续开发
- 比赛过题提交需要集成AI识别API
- 可以通过管理面板自定义连签奖励和比赛奖励规则
- RBC商店管理功能已实现，管理员可以添加自定义商品
