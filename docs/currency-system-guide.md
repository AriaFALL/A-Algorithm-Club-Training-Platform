# RBC Currency System Implementation Guide

## Overview
This document describes the RBC (Rainbow Coin) currency system implemented for the Algorithm Club Training Platform.

## Features Implemented

### 1. Currency System Core
- **Database Models**: Complete set of models for managing currency balances, transactions, check-ins, rewards, and shop items
- **Service Layer**: Business logic for all currency operations (add/deduct currency, check-ins, purchases, etc.)
- **API Endpoints**: RESTful APIs for both users and administrators

### 2. Daily Check-in System
- Automatic check-in on first submission of the day
- Configurable daily rewards (default: +1 RBC)
- Consecutive streak tracking
- Make-up check-in using make-up tickets (补签券)
- Configurable streak rewards:
  - 7-day streak: +2 RBC (default)
  - 3-day streak: +1 RBC (default; each tier once per natural week)
  - Custom streak rewards can be added by admin

### 3. Contest Progress and Rewards
- Current automatic rewards use synchronized per-problem AC evidence from the contest calendar.
- Known timestamps must fall inside the formal contest window; proven AC with unavailable timestamps uses the requested relaxed fallback.
- Difficulty tiers and beginner/experienced amounts are configurable. Claims are transactional and deduplicated.
- The legacy screenshot endpoint stores materials only. Its old reward configuration is retained, but no AI screenshot review or automatic payout is implemented there.

### 4. RBC Shop
- Customizable shop items
- Make-up tickets (补签券) as default item (3 RBC)
- Support for unlimited or limited stock items
- Purchase history tracking
- User inventory system for consumable items

### 5. Admin Features
- Enable/disable currency system per team
- Configure daily check-in rewards
- Manage streak reward tiers
- Set contest reward configurations
- Adjust member balances manually
- Shop item management (create, edit, delete, toggle active status)
- View transaction history for all members

### 6. UI Integration
- Currency balance display in topbar with icon
- Transaction history modal
- RBC Shop navigation menu item (auto-shows when enabled)
- Shop interface with item cards
- Admin configuration panel
- Member balance display in member lists (admin only)
- Contest submission interface with image upload

## File Structure

```
club/
├── models.py                 # Updated with currency fields for Team model
├── currency_models.py        # All currency system models (deprecated, moved to models.py)
├── currency_services.py      # Business logic for currency operations
├── currency_views.py         # API endpoints for currency features
└── urls.py                   # URL routing for currency APIs

Frontend:
├── currency.js               # Client-side currency module
├── currency-admin.js         # Admin panel JavaScript
├── currency-styles.css       # Styles for currency UI
├── index.html                # Updated with currency UI integration
└── app.js                    # Updated with RBC shop view handling

Static Assets:
└── E:\Downloads\helloworld_coin.svg  # Currency icon (to be moved to media/currency_icons/)
```

## Setup Instructions

### 1. Database Migration
Run the following commands to create the database tables:

```bash
python manage.py makemigrations
python manage.py migrate
```

### 2. Move Currency Icon
Move the currency icon to the proper location:

```bash
mkdir -p media/currency_icons
cp E:\Downloads\helloworld_coin.svg media/currency_icons/
```

### 3. Enable Currency System
For each team that wants to use the currency system:

1. Login as a system administrator
2. Navigate to **管理工作台** (Admin Workbench)
3. Go to **团队配置** (Team Configuration)
4. Toggle **启用货币系统** (Enable Currency System)
5. Upload the currency icon SVG
6. Configure daily check-in rewards and streak bonuses
7. Set up contest reward tiers

### 4. Initialize Default Shop Items
When enabling the currency system, the following default items are auto-created:
- **补签券** (Make-up Ticket): 3 RBC, unlimited stock

## API Endpoints

### User Endpoints
- `GET /api/currency/balance` - Get current balance and streak
- `GET /api/currency/transactions` - Get transaction history
- `POST /api/currency/checkin` - Perform daily check-in
- `POST /api/currency/checkin/makeup` - Use make-up ticket
- `GET /api/currency/checkin/calendar` - Get check-in calendar
- `POST /api/currency/contest/submit` - Submit contest screenshot
- `GET /api/currency/shop/items` - Get shop items
- `POST /api/currency/shop/purchase` - Purchase an item
- `GET /api/currency/inventory` - Get user inventory

### Admin Endpoints
- `POST /api/currency/admin/adjust` - Adjust member balance
- `GET /POST /api/currency/admin/config` - Get/update currency config
- `GET /POST /PUT /DELETE /api/currency/admin/shop` - Manage shop items

## Usage Examples

### Client-Side JavaScript

```javascript
// Initialize currency system
await CurrencyModule.init();

// Perform check-in
await CurrencyModule.performCheckin();

// Purchase an item
await CurrencyModule.purchaseItem(itemId, quantity);

// Submit contest screenshot
await CurrencyModule.submitContestScreenshot(
  contestName,
  contestUrl,
  screenshotBase64
);

// Show transaction history
CurrencyModule.showTransactionHistory();
```

### Admin Panel

```javascript
// Load currency configuration
const config = await CurrencyAdminModule.loadConfig();

// Save configuration
await CurrencyAdminModule.saveConfig({
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
});

// Adjust member balance
await CurrencyAdminModule.adjustBalance(memberId, amount, description);
```

## Integration Points

### AI Verification for Contest Submissions
The contest submission feature includes a placeholder for AI verification. To integrate:

1. Configure an AI API endpoint in your settings
2. Update `club/currency_views.py` > `api_contest_submission` to call your AI service
3. The AI should analyze the screenshot and return the number of problems solved
4. Automatic reward calculation and distribution will follow

Example integration:

```python
# In api_contest_submission view
from .ai_verification import verify_contest_screenshot

# After creating submission
problems_solved = await verify_contest_screenshot(submission.screenshot.path)
submission.problems_solved = problems_solved

# Calculate and award reward
reward = calculate_contest_reward(problems_solved, is_ak=False, team=member.team)
if reward > 0:
    add_currency(member, reward, CurrencyTransaction.CONTEST_REWARD,
                 f"比赛过题 {problems_solved} 题奖励")
    submission.reward_amount = reward

submission.status = ContestSubmission.APPROVED
submission.save()
```

### Daily Check-in Trigger
Check-in is triggered automatically on the first submission each day. The trigger is in the submission creation logic:

```python
# In your submission view
from .currency_services import perform_checkin

# After successful submission
try:
    perform_checkin(member)
except ValueError:
    # Already checked in today
    pass
```

## Customization

### Adding New Shop Items
Administrators can add custom shop items through the admin panel:
1. Navigate to RBC商店 (RBC Shop)
2. Click the edit button (visible to admins)
3. Click "添加商品" (Add Item)
4. Fill in item details (name, description, price, stock, type)
5. Upload an icon (optional)
6. Save

### Custom Reward Tiers
Both streak rewards and contest rewards can be customized:
- Add/remove tiers as needed
- Set custom day counts for streaks
- Configure problem-count thresholds for contests
- Adjust reward amounts

## Security Considerations

- All currency operations are atomic (database transactions)
- Balance checks prevent negative balances
- Admin-only endpoints require authentication and authorization
- User can only modify their own data
- File uploads are validated (size limits, file types)

## Future Enhancements

Potential additions to the currency system:
1. **Leaderboard for RBC**: Show top earners
2. **Currency Decay**: Optional expiration of old coins
3. **Team Events**: Special reward events or sales
4. **Gifting**: Allow members to gift RBC to each other
5. **Achievement Badges**: Earn special items through achievements
6. **Analytics Dashboard**: Currency flow and spending patterns
7. **Notification System**: Alert users of rewards, purchases
8. **Mobile App Integration**: API ready for mobile clients

## Troubleshooting

### Currency System Not Showing
- Verify currency_enabled is True for the team in database
- Check browser console for JavaScript errors
- Ensure all script files are loaded (currency.js, currency-admin.js)

### Check-in Not Working
- Verify user has active team membership
- Check if already checked in today
- Review transaction logs for errors

### Shop Purchase Failing
- Check user balance is sufficient
- Verify item is active and in stock
- Check for database transaction errors in logs

## Support

For issues or questions:
- Check application logs in Django admin
- Review browser console for frontend errors
- Verify database migrations are applied
- Ensure all currency system files are properly uploaded


## 2026-10-29 稳定性复核补充

现行连签奖励按北京时间的自然周（周一至周日）计算最长连续签到，每个团队、用户、自然周、连签天数档位只发一次。有效训练提交与签到记录取日期并集；补签只在记录提交成功后计入，扣券开放权限不计入。配置删除重建或成员关系删除不会清除已发奖凭证。30天档位不适用于此规则。

自动比赛奖励有时间时核验正式赛内AC，已确认AC但无法核验时间时宽松发奖；旧截图保存入口不会执行AI自动审核或直接发币。商店购买使用请求编号防止网络重试重复扣款，已购或持有库存的商品请下架，不能删除历史依赖或修改商品类型。
