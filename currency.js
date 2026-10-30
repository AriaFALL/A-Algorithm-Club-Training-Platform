/**
 * RBC Currency System - Frontend JavaScript
 */

const CurrencyModule = (() => {
  let currencyData = {
    balance: 0,
    streak: 0,
    currencyIcon: null,
    enabled: false,
  };

  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let initVersion = 0;

  // Initialize currency module
  async function init() {
    const version = ++initVersion;
    try {
      const response = await window.clubApi.request("/api/currency/balance", {
        credentials: "include",
      });

      if (version !== initVersion) return false;
      if (response.ok) {
        const data = await response.json();
        if (version !== initVersion) return false;
        currencyData = {
          balance: data.balance,
          streak: data.streak,
          currencyIcon: data.currency_icon,
          enabled: true,
          canPurchase: data.can_purchase,
          siteAdmin: data.site_admin,
        };

        updateCurrencyDisplay();
        showCurrencyNavItem();
        return true;
      } else {
        // Currency system not enabled
        currencyData.enabled = false;
        hideCurrencyElements();
        return false;
      }
    } catch (error) {
      if (version !== initVersion) return false;
      currencyData.enabled = false;
      hideCurrencyElements();
      console.error("Failed to initialize currency system:", error);
      return false;
    }
  }

  // Update currency balance display in topbar
  function updateCurrencyDisplay() {
    const profileChip = document.querySelector(".profile-chip");
    if (!profileChip || !currencyData.enabled) return;

    // Add currency balance display
    const existingBalance = profileChip.querySelector(".currency-balance");
    if (existingBalance) {
      existingBalance.remove();
    }

    const balanceEl = document.createElement("div");
    balanceEl.className = "currency-balance";
    balanceEl.innerHTML = `
      <button class="currency-button" type="button" title="RBC Coins余额">
        ${currencyData.currencyIcon ? `<img src="${escape(currencyData.currencyIcon)}" alt="RBC" class="currency-icon" />` : '<span class="currency-icon">💎</span>'}
        <strong>${currencyData.balance}</strong> RBC
      </button>
    `;

    balanceEl.querySelector(".currency-button").addEventListener("click", showTransactionHistory);
    profileChip.insertBefore(balanceEl, profileChip.querySelector(".logout-button"));
  }

  // Show RBC Shop navigation item
  function showCurrencyNavItem() {
    const nav = document.querySelector(".nav-list");
    if (!nav) return;

    // Check if shop nav already exists
    if (document.querySelector('[data-view="rbcshop"]')) return;

    const shopNav = document.createElement("button");
    shopNav.className = "nav-item";
    shopNav.setAttribute("data-view", "rbcshop");
    shopNav.type = "button";
    shopNav.addEventListener("click", () => setView("rbcshop"));
    shopNav.innerHTML = '<span class="nav-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" focusable="false"><path d="M3 10l2-7h14l2 7M4 13v8h16v-8M3 10a3 3 0 0 0 6 0 3 3 0 0 0 6 0 3 3 0 0 0 6 0M9 21v-6h6v6"/></svg></span>RBC商店';

    // Insert before admin nav or at the end
    const adminNav = document.querySelector('[data-view="extensions"]');
    if (adminNav && adminNav.parentElement === nav) {
      nav.insertBefore(shopNav, adminNav);
    } else {
      nav.appendChild(shopNav);
    }
  }

  // Hide currency elements when not enabled
  function hideCurrencyElements() {
    const currencyBalance = document.querySelector(".currency-balance");
    if (currencyBalance) currencyBalance.remove();

    const shopNav = document.querySelector('[data-view="rbcshop"]');
    if (shopNav) shopNav.remove();
    document.getElementById("transactionModal")?.remove();
    const view = document.getElementById("rbcshopView");
    if (view?.classList.contains("active")) setView("dashboard");
    if (view) view.innerHTML = "";
  }

  // Show transaction history modal
  async function showTransactionHistory() {
    try {
      const response = await window.clubApi.request("/api/currency/transactions?limit=50", {
        credentials: "include",
      });

      if (!response.ok) {
        throw new Error("Failed to fetch transactions");
      }

      const data = await response.json();
      displayTransactionModal(data.transactions);
    } catch (error) {
      console.error("Failed to fetch transaction history:", error);
      alert("无法加载交易记录");
    }
  }

  // Display transaction history modal
  function displayTransactionModal(transactions) {
    // Remove existing modal if any
    const existingModal = document.getElementById("transactionModal");
    if (existingModal) existingModal.remove();

    const modal = document.createElement("div");
    modal.id = "transactionModal";
    modal.className = "modal-overlay";
    modal.innerHTML = `
      <div class="modal-content currency-modal">
        <div class="modal-header">
          <h2>RBC Coins 余额变动记录</h2>
          <button class="modal-close" type="button">×</button>
        </div>
        <div class="modal-body">
          <div class="currency-summary">
            <div class="currency-summary-item">
              <span>当前余额</span>
              <strong>${currencyData.balance} RBC</strong>
            </div>
            <div class="currency-summary-item">
              <span>连签天数</span>
              <strong>${currencyData.streak} 天</strong>
            </div>
          </div>
          <div class="transaction-list">
            ${transactions.length === 0 ? '<div class="empty-state">暂无交易记录</div>' : transactions.map(t => `
              <div class="transaction-item">
                <div class="transaction-info">
                  <div class="transaction-type">${escape(t.type_display)}</div>
                  <div class="transaction-desc">${escape(t.description)}</div>
                  <div class="transaction-time">${new Date(t.created_at).toLocaleString('zh-CN')}</div>
                </div>
                <div class="transaction-amount ${t.amount > 0 ? 'positive' : 'negative'}">
                  ${t.amount > 0 ? '+' : ''}${t.amount}
                </div>
                <div class="transaction-balance">
                  余额: ${t.balance_after}
                </div>
              </div>
            `).join('')}
          </div>
        </div>
      </div>
    `;

    document.body.appendChild(modal);

    // Close modal handlers
    modal.querySelector(".modal-close").addEventListener("click", () => modal.remove());
    modal.addEventListener("click", (e) => {
      if (e.target === modal) modal.remove();
    });
  }

  // Perform daily check-in
  async function performCheckin() {
    try {
      const response = await window.clubApi.request("/api/currency/checkin", {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
        },
      });

      const data = await response.json();

      if (response.ok) {
        currencyData.balance += data.reward + (data.weekly_bonus || 0);
        currencyData.streak = data.streak;
        updateCurrencyDisplay();

        alert(`签到成功！获得 ${data.reward} RBC${data.weekly_bonus ? `，本周连签奖励 +${data.weekly_bonus} RBC` : ''}\n连签 ${data.streak} 天`);
        return true;
      } else {
        alert(data.error || "签到失败");
        return false;
      }
    } catch (error) {
      console.error("Check-in failed:", error);
      alert("签到失败，请稍后重试");
      return false;
    }
  }

  // Perform makeup check-in
  async function performMakeupCheckin(checkinDate, {alreadyOpen = false} = {}) {
    try {
      if (!alreadyOpen) {
        const inventoryResponse = await window.clubApi.request('/api/currency/inventory');
        const inventory = await inventoryResponse.json();
        if (!inventoryResponse.ok) throw new Error(inventory.error || '无法读取补签券数量');
        const remaining = (inventory.inventory || []).filter(item => item.item_type === 'makeup_ticket')
          .reduce((total, item) => total + Number(item.quantity || 0), 0);
        if (remaining <= 0) {
          const goToShop = await window.clubDialog.confirm({title:'补签券不足',
            text:`补交 ${checkinDate} 的记录需要消耗补签券 ×1。\n当前没有可用补签券，是否前往 RBC 商店？`,
            confirmText:'前往商店', kind:'ticket'});
          if (goToShop) navigateToShop();
          return false;
        }
        const confirmed = await window.clubDialog.confirm({title:'确认使用补签券',
          text:`补交 ${checkinDate} 的记录需消耗补签券 ×1，是否确认？\n当前剩余 ${remaining} 张，确认后该日期将开放补交。`,
          confirmText:'确认使用', kind:'ticket'});
        if (!confirmed) return false;
      }
      const response = await window.clubApi.request("/api/currency/checkin/makeup", {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          checkin_date: checkinDate,
        }),
      });

      const data = await response.json();

      if (response.ok && data.success) {
        await init();
        return data;
      } else {
        // Check if error is due to insufficient makeup tickets
        if (data.error_code === "INSUFFICIENT_MAKEUP_TICKETS") {
          const confirmPurchase = await window.clubDialog.confirm({title:'补签券不足',
            text:`没有可用补签券。补交 ${checkinDate} 需要消耗补签券 ×1。\n${data.item_id ? `商品：${data.item_name}，价格：${data.item_price} RBC` : '商店暂时没有可购买的补签券，可联系管理员补货。'}\n是否前往 RBC 商店？`,
            confirmText:'前往商店', kind:'ticket'});
          if (confirmPurchase) {
            navigateToShop();
          }
        } else {
          await window.clubDialog.notice({title:'暂时无法补交', text:data.error || '补签失败'});
        }
        return false;
      }
    } catch (error) {
      console.error("Makeup check-in failed:", error);
      await window.clubDialog.notice({title:'补交未完成', text:error.message || '请稍后重试'});
      return false;
    }
  }

  // Check if user has makeup ticket (deprecated - kept for backward compatibility)
  async function checkMakeupTicket() {
    try {
      const response = await window.clubApi.request("/api/currency/inventory", {
        credentials: "include",
      });

      if (response.ok) {
        const data = await response.json();
        const makeupTicket = data.inventory.find(
          (item) => item.item_type === "makeup_ticket"
        );
        return makeupTicket && makeupTicket.quantity > 0;
      }
      return false;
    } catch (error) {
      console.error("Failed to check inventory:", error);
      return false;
    }
  }

  // Refresh streak count
  async function refreshStreak() {
    try {
      const response = await window.clubApi.request("/api/currency/balance", {
        credentials: "include",
      });

      if (response.ok) {
        const data = await response.json();
        return data.streak;
      }
      return 0;
    } catch (error) {
      console.error("Failed to refresh streak:", error);
      return 0;
    }
  }

  // Submit contest screenshot
  async function submitContestScreenshot(contestName, contestUrl, screenshotBase64) {
    try {
      const response = await window.clubApi.request("/api/currency/contest/submit", {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          contest_name: contestName,
          contest_url: contestUrl,
          screenshot: screenshotBase64,
        }),
      });

      const data = await response.json();

      if (response.ok) {
        alert(data.message || "比赛材料已保存，请在比赛日程同步核验奖励");
        return true;
      } else {
        alert(data.error || "提交失败");
        return false;
      }
    } catch (error) {
      console.error("Contest submission failed:", error);
      alert("提交失败，请稍后重试");
      return false;
    }
  }

  const purchasesInFlight = new Set();
  const purchaseRequests = new Map();

  // Purchase shop item
  async function purchaseItem(itemId, quantity = 1, itemDetails = null) {
    itemId=Number(itemId);
    if (purchasesInFlight.has(itemId)) return false;
    purchasesInFlight.add(itemId);
    const requestKey=`${itemId}:${quantity}`;
    try {
      const item = itemDetails || (await loadShopItems()).find(item => Number(item.id) === itemId);
      if (!item) {
        await window.clubDialog.notice({title:'商品暂不可购买', text:'请刷新商店后重试。'});
        return false;
      }
      const confirmed = await window.clubDialog.confirm({title:'确认购买', kind:'cart',
        text:`${item.name} ×${quantity}\n需支付 ${Number(item.price) * quantity} RBC，当前余额 ${currencyData.balance} RBC。`,
        confirmText:'确认购买'});
      if (!confirmed) return false;
      if(!purchaseRequests.has(requestKey)) {
        purchaseRequests.set(requestKey,window.clubApi.requestId());
      }
      const response = await window.clubApi.request("/api/currency/shop/purchase", {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          item_id: itemId,
          quantity: quantity,
          request_id:purchaseRequests.get(requestKey),
        }),
      });

      const data = await response.json();

      if (response.ok) {
        purchaseRequests.delete(requestKey);
        currencyData.balance = data.balance;
        updateCurrencyDisplay();
        await window.clubDialog.notice({title:'购买成功', text:data.duplicate ? '已确认上次购买成功，本次未重复扣款' : `已放入背包，花费 ${data.total_price} RBC。`, kind:'cart'});
        return true;
      } else {
        if(response.status<500)purchaseRequests.delete(requestKey);
        await window.clubDialog.notice({title:'购买未完成', text:data.error || '购买失败'});
        return false;
      }
    } catch (error) {
      console.error("Purchase failed:", error);
      await init();
      await window.clubDialog.notice({title:'购买结果待确认', text:'购买结果暂未确认，请重试；相同请求不会重复扣款。'});
      return false;
    } finally { purchasesInFlight.delete(itemId); }
  }

  // Navigate to shop view
  function navigateToShop() {
    const shopNav = document.querySelector('[data-view="rbcshop"]');
    if (shopNav) {
      shopNav.click();
    }
  }

  // Load shop items
  async function loadShopItems() {
    try {
      const response = await window.clubApi.request("/api/currency/shop/items", {
        credentials: "include",
      });

      if (response.ok) {
        const data = await response.json();
        return data.items;
      }
      return [];
    } catch (error) {
      console.error("Failed to load shop items:", error);
      return [];
    }
  }

  // Render shop view
  let shopRenderVersion = 0;
  async function renderShopView(container) {
    const version = ++shopRenderVersion;
    const [items, inventoryResult] = await Promise.all([loadShopItems(),
      window.clubApi.request('/api/currency/inventory').then(async response => {
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || '背包加载失败');
        return data.inventory || [];
      }).then(items => ({items}), error => ({error:error.message}))]);
    if (version !== shopRenderVersion) return;
    const backpack = container.dataset.shopTab === 'inventory';
    const displayItems = backpack ? (inventoryResult.items || []).map(item => ({
      ...item, id:item.item_id, name:item.item_name,
    })) : items;
    const coinIconSrc = currencyData.currencyIcon || '/static/images/rbc-coin.svg';

    container.innerHTML = `
      <section class="page-heading">
        <div>
          <p class="kicker">RBC SHOP</p>
          <h1>RBC商店</h1>
          <p class="muted">使用RBC Coins兑换您需要的物品</p>
        </div>
        <div class="currency-display">
          ${currencyData.currencyIcon ? `<img src="${escape(currencyData.currencyIcon)}" alt="RBC" class="currency-icon-large" />` : '<span class="currency-icon-large">💎</span>'}
          <div>
            <strong>${currencyData.balance}</strong>
            <small>RBC Coins</small>
          </div>
        </div>
      </section>

      <section class="panel">
        <div class="segmented shop-tabs" role="tablist" aria-label="商店与背包">
          <button class="segment ${!backpack ? 'active' : ''}" type="button" data-shop-tab="shop">商店</button>
          <button class="segment ${backpack ? 'active' : ''}" type="button" data-shop-tab="inventory">背包</button>
        </div>
        <div class="shop-grid">
          ${backpack && inventoryResult.error ? `<div class="empty-state" role="alert">${escape(inventoryResult.error)}<button class="text-button" data-inventory-retry type="button">重试</button></div>` : displayItems.length === 0 ? `<div class="empty-state">${backpack ? '背包里还没有物品' : '暂无商品'}</div>` : displayItems.map(item => `
            <div class="shop-item-card">
              <div class="shop-item-icon">
                ${item.icon ? `<img src="${escape(item.icon)}" alt="${escape(item.name)}" />` : '<span class="placeholder-icon">📦</span>'}
              </div>
              <div class="shop-item-info">
                <h3>${escape(item.name)}</h3>
                <p>${escape(item.description)}</p>
                ${!backpack && item.stock !== -1 ? `<small class="stock-info">库存: ${item.stock}</small>` : ''}
              </div>
              <div class="shop-item-footer">
                ${backpack ? `<span class="shop-owned-label">当前拥有</span><strong class="shop-owned-count">${item.quantity}<small> 个</small></strong>` : `
                <div class="shop-item-price">
                  <img src="${escape(coinIconSrc)}" alt="" class="shop-price-coin" aria-hidden="true" />
                  <strong>${item.price}</strong><span>RBC</span>
                </div>
                <button
                  class="primary-button shop-buy-btn"
                  data-item-id="${item.id}"
                  ${item.stock === 0 || !currencyData.canPurchase ? 'disabled' : ''}
                >
                  <svg class="shop-cart-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                    <path d="M3.5 4.5h2l1.7 9.1a1.7 1.7 0 0 0 1.7 1.4h7.8a1.7 1.7 0 0 0 1.6-1.2l1.3-5.1H7.1" />
                    <circle cx="9.2" cy="19" r="1.2" />
                    <circle cx="17.2" cy="19" r="1.2" />
                  </svg>
                  ${!currencyData.canPurchase ? '管理预览' : item.stock === 0 ? '已售罄' : '购买'}
                </button>
                `}
              </div>
            </div>
          `).join('')}
        </div>
      </section>
    `;

    const tabs = container.querySelector('.shop-tabs');
    if (typeof syncSegmented === 'function') syncSegmented(tabs);
    const buttons = [...tabs.querySelectorAll('[data-shop-tab]')];
    buttons.forEach((button, index) => {
      button.addEventListener('click', async () => {
        if (container.dataset.shopTab === button.dataset.shopTab) return;
        container.dataset.shopTab = button.dataset.shopTab;
        if (typeof syncSegmented === 'function') syncSegmented(tabs, button);
        await renderShopView(container);
        container.querySelector(`[data-shop-tab="${button.dataset.shopTab}"]`)?.focus();
      });
      button.addEventListener('keydown', event => {
        if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
        event.preventDefault();
        buttons[event.key === 'Home' ? 0 : event.key === 'End' ? 1 : 1-index].click();
      });
    });
    container.querySelector('[data-inventory-retry]')?.addEventListener('click', () => renderShopView(container));

    if (currencyData.siteAdmin && !backpack) {
      const edit = document.createElement("button");
      edit.className = "secondary-button"; edit.type = "button"; edit.textContent = "编辑商品";
      container.querySelector(".page-heading").append(edit);
      const management = document.createElement("section"); management.className = "panel"; management.hidden = true;
      container.append(management);
      edit.addEventListener("click", async () => {
        if (management.hidden) {management.hidden=false; edit.textContent="完成编辑"; await window.CurrencyAdminModule.renderShopManagementPanel(management);}
        else {await renderShopView(container);}
      });
    }

    // Attach purchase handlers
    container.querySelectorAll(".shop-buy-btn").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        const button=e.currentTarget;
        if(button.disabled)return;
        const itemId=Number(button.getAttribute("data-item-id"));
        button.disabled=true;button.textContent='确认中…';
        try {await purchaseItem(itemId, 1, items.find(item => Number(item.id) === itemId)); await renderShopView(container);}
        finally {button.disabled=false;}
      });
    });
  }

  // Public API
  return {
    init,
    performCheckin,
    performMakeupCheckin,
    submitContestScreenshot,
    purchaseItem,
    loadShopItems,
    renderShopView,
    updateCurrencyDisplay,
    showTransactionHistory,
    getCurrencyData: () => ({ ...currencyData }),
  };
})();

// Export for use in other modules
if (typeof window !== "undefined") {
  window.CurrencyModule = CurrencyModule;
}
