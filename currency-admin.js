/**
 * RBC Currency System - Admin Panel JavaScript
 */

const CurrencyAdminModule = (() => {
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  // Load currency configuration
  async function loadConfig(teamId) {
    try {
      const response = await window.clubApi.request("/api/currency/admin/config" + (teamId ? `?team_id=${encodeURIComponent(teamId)}` : ""), {
        credentials: "include",
      });

      if (response.ok) {
        return await response.json();
      }
      throw new Error("Failed to load config");
    } catch (error) {
      console.error("Failed to load currency config:", error);
      return null;
    }
  }

  // Save currency configuration
  async function saveConfig(config) {
    try {
      const response = await window.clubApi.request("/api/currency/admin/config", {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(config),
      });

      if (response.ok) {
        showToast("货币配置已保存");
        return true;
      } else {
        const data = await response.json();
        alert(data.error || "保存失败");
        return false;
      }
    } catch (error) {
      console.error("Failed to save currency config:", error);
      alert("保存失败，请稍后重试");
      return false;
    }
  }

  // Adjust member balance
  async function adjustBalance(memberId, amount, description) {
    try {
      const response = await window.clubApi.request("/api/currency/admin/adjust", {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          member_id: memberId,
          amount: amount,
          description: description,
        }),
      });

      const data = await response.json();

      if (response.ok) {
        alert(`余额调整成功，新余额: ${data.new_balance} RBC`);
        return true;
      } else {
        alert(data.error || "调整失败");
        return false;
      }
    } catch (error) {
      console.error("Failed to adjust balance:", error);
      alert("调整失败，请稍后重试");
      return false;
    }
  }

  // Load shop items for admin
  async function loadShopItems() {
    try {
      const response = await window.clubApi.request("/api/currency/admin/shop", {
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

  // Create shop item
  async function createShopItem(itemData) {
    try {
      const response = await window.clubApi.request("/api/currency/admin/shop", {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(itemData),
      });

      if (response.ok) {
        alert("商品创建成功");
        return true;
      } else {
        const data = await response.json();
        alert(data.error || "创建失败");
        return false;
      }
    } catch (error) {
      console.error("Failed to create shop item:", error);
      alert("创建失败，请稍后重试");
      return false;
    }
  }

  // Update shop item
  async function updateShopItem(itemData) {
    try {
      const response = await window.clubApi.request("/api/currency/admin/shop", {
        method: "PUT",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(itemData),
      });

      if (response.ok) {
        alert("商品更新成功");
        return true;
      } else {
        const data = await response.json();
        alert(data.error || "更新失败");
        return false;
      }
    } catch (error) {
      console.error("Failed to update shop item:", error);
      alert("更新失败，请稍后重试");
      return false;
    }
  }

  // Delete shop item
  async function deleteShopItem(itemId) {
    if (!confirm("确定要删除这个商品吗？")) {
      return false;
    }

    try {
      const response = await window.clubApi.request("/api/currency/admin/shop", {
        method: "DELETE",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ item_id: Number(itemId) }),
      });

      if (response.ok) {
        alert("商品删除成功");
        return true;
      } else {
        const data = await response.json();
        alert(data.error || "删除失败");
        return false;
      }
    } catch (error) {
      console.error("Failed to delete shop item:", error);
      alert("删除失败，请稍后重试");
      return false;
    }
  }

  // Render currency configuration panel
  async function renderConfigPanel(container, teamId) {
    const config = await loadConfig(teamId);
    if (!config || !container.isConnected) {
      container.innerHTML = '<p role="alert">无法加载货币配置，请重新打开团队配置。</p>';
      return;
    }
    const streaks = config.streak_rewards.length || config.currency_enabled ? config.streak_rewards : [{days:3,reward:1},{days:7,reward:2}];
    const contests = config.contest_rewards.length || config.currency_enabled ? config.contest_rewards : [{problems_solved:2,reward:1,is_ak:false},{problems_solved:4,reward:2,is_ak:false},{problems_solved:1,reward:5,is_ak:true}];
    container.innerHTML = `
      <form class="currency-config-panel workbench-form">
        <h3>货币系统配置</h3>
        <label class="workbench-check"><input name="currency_enabled" type="checkbox" ${config.currency_enabled ? 'checked' : ''}>启用 RBC 货币系统</label>
        <p class="muted">关闭后，该团队的余额与商店入口会隐藏。</p>
        <fieldset class="currency-config-options" ${config.currency_enabled ? '' : 'hidden disabled'}>
          <label>货币图标（SVG，最多 128 KB）<input name="currency_icon" type="file" accept=".svg,image/svg+xml"></label>
          ${config.currency_icon ? `<div class="currency-icon-preview"><img src="${escape(config.currency_icon)}" width="32" height="32" alt="当前货币图标"><label class="workbench-check"><input name="remove_icon" type="checkbox">恢复默认图标</label></div>` : ''}
          <label>每日签到奖励 (RBC)<input name="daily_checkin_reward" type="number" min="0" max="100" required value="${config.daily_checkin_reward}"></label>
          <p class="muted">每天第一次提交的签到奖励；补签不发放每日奖励。</p>
          <h4>自然周连签奖励</h4><p class="muted">周一至周日截断，每个天数档位每周只发放一次；补签会重算原周。</p><div class="currency-streak-rules"></div>
          <button type="button" class="secondary-button" data-add-streak>＋ 添加连签奖励</button>
          <h4>同步比赛 · 单题奖励</h4><p class="muted">萌新：大一上；老登：大一下及以上。三档按平台题目难度划分；0 表示不奖励。2026-11-01 起的比赛生效；有准确时间时仅正赛时段内 AC 可领奖；已确认 AC 但时间无法核验时，宽松兜底发奖；已知赛外记录不发奖。</p>
          <div class="problem-reward-grid">${['beginner','experienced'].map(group=>`<fieldset><legend>${group==='beginner'?'萌新':'老登'}</legend>${(config.problem_rewards?.[group] || [1,2,3]).map((amount,index)=>`<label>第 ${index+1} 档 RBC<input type="number" data-problem-reward="${group}" data-tier="${index}" min="0" max="100000" required value="${amount}"></label>`).join('')}</fieldset>`).join('')}</div>
          <details><summary>平台难度档位说明</summary><p class="muted">力扣：萌新 600 / 1200，老登 1000 / 1500；CF：1000 / 1600、1400 / 2000；AtCoder：400 / 1000、800 / 1600；牛客 Rating：1100 / 1600、1600 / 2100；洛谷难度等级：2 / 4、4 / 6。均按“低于第一界限／低于第二界限／其余”分档。缺少难度时按第一档发奖；不会编造题目 Rating。</p></details>
          <h4>旧版截图比赛奖励配置</h4><p class="muted">保留旧规则配置，不用于日程同步的单题领奖；旧截图入口仅保存材料，不会自动审核发币。</p>
          <div class="currency-contest-rules"></div>
          <div class="currency-rule-actions"><button type="button" class="secondary-button" data-add-contest>＋ 添加过题奖励</button><button type="button" class="secondary-button" data-add-ak>＋ 添加 AK 奖励</button></div>
        </fieldset>
        <div class="workbench-form-actions"><button type="submit" class="primary-button">保存货币配置</button><span class="currency-config-status" role="status"></span></div>
      </form>`;
    const form = container.querySelector('form');
    const status = container.querySelector('.currency-config-status');
    const options = container.querySelector('fieldset');
    const addRow = (kind, rule) => {
      const row = document.createElement('div'); row.className='currency-rule-row'; row.dataset.kind=kind;
      row.innerHTML = kind === 'streak'
        ? `<label>连签天数<input class="rule-threshold" aria-label="连签天数" type="number" min="1" max="7" required value="${rule.days}"></label>`
        : rule.is_ak ? '<strong>AK（全部通过）</strong>' : `<label>过题数量<input class="rule-threshold" aria-label="过题数量" type="number" min="1" max="100000" required value="${rule.problems_solved}"></label>`;
      row.dataset.ak=String(Boolean(rule.is_ak));
      row.innerHTML += `<label>奖励 RBC<input class="rule-reward" aria-label="奖励 RBC" type="number" min="1" max="100000" required value="${rule.reward}"></label><button class="text-button" type="button" aria-label="删除奖励规则">删除</button>`;
      row.querySelector('button').onclick=()=>row.remove();
      container.querySelector(kind==='streak' ? '.currency-streak-rules' : '.currency-contest-rules').append(row);
    };
    streaks.forEach(r=>addRow('streak',r)); contests.forEach(r=>addRow('contest',r));
    form.elements.currency_enabled.onchange=()=>{options.hidden=!form.elements.currency_enabled.checked;options.disabled=options.hidden;};
    container.querySelector('[data-add-streak]').onclick=()=>addRow('streak',{days:7,reward:2});
    container.querySelector('[data-add-contest]').onclick=()=>addRow('contest',{problems_solved:2,reward:1,is_ak:false});
    container.querySelector('[data-add-ak]').onclick=()=>{
      if (container.querySelector('[data-kind="contest"][data-ak="true"]')) {status.textContent='只能设置一条 AK 奖励';return;}
      addRow('contest',{problems_solved:1,reward:5,is_ak:true});
    };
    form.onsubmit=async event=>{
      event.preventDefault(); event.stopPropagation();
      const button=event.submitter; button.disabled=true; status.textContent='正在保存…';
      const payload={team_id:teamId,currency_enabled:form.elements.currency_enabled.checked};
      try {
        if (payload.currency_enabled) {
          payload.daily_checkin_reward=Number(form.elements.daily_checkin_reward.value);
          payload.problem_rewards=Object.fromEntries(['beginner','experienced'].map(group=>[group,[...container.querySelectorAll('[data-problem-reward='+group+']')].map(input=>Number(input.value))]));
          payload.streak_rewards=[...container.querySelectorAll('[data-kind="streak"]')].map(row=>({days:Number(row.querySelector('.rule-threshold').value),reward:Number(row.querySelector('.rule-reward').value)}));
          payload.contest_rewards=[...container.querySelectorAll('[data-kind="contest"]')].map(row=>({problems_solved:row.dataset.ak==='true'?1:Number(row.querySelector('.rule-threshold').value),reward:Number(row.querySelector('.rule-reward').value),is_ak:row.dataset.ak==='true'}));
          const file=form.elements.currency_icon.files[0];
          if(file){if(file.size>131072)throw new Error('SVG 图标不能超过 128 KB');payload.currency_icon_svg=await file.text();}
          else if(form.elements.remove_icon?.checked)payload.currency_icon_svg=null;
        }
        const response=await window.clubApi.request('/api/currency/admin/config', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
        const result=await response.json();
        if(!response.ok)throw new Error(result.error || '保存失败');
        await window.CurrencyModule.init();
        status.textContent='已保存';showToast('货币配置已保存');
        await renderConfigPanel(container,teamId);
      } catch(error){status.textContent=error.message;}
      finally{button.disabled=false;}
    };
  }

  // Render shop management panel
  async function renderShopManagementPanel(container) {
    const items = await loadShopItems();

    container.innerHTML = `
      <div class="shop-management-panel">
        <div class="panel-header">
          <h3>RBC商店管理</h3>
          <button type="button" id="addShopItem" class="primary-button">+ 添加商品</button>
        </div>

        <div class="shop-items-table">
          <table>
            <thead>
              <tr>
                <th>商品名称</th>
                <th>价格</th>
                <th>库存</th>
                <th>类型</th>
                <th>状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              ${items.length === 0 ? '<tr><td colspan="6" class="empty-state">暂无商品</td></tr>' : items.map(item => `
                <tr>
                  <td>${escape(item.name)}</td>
                  <td>${item.price} RBC</td>
                  <td>${item.stock === -1 ? '无限' : item.stock}</td>
                  <td>${item.item_type}</td>
                  <td>${item.is_active ? '上架' : '下架'}</td>
                  <td>
                    <button type="button" class="edit-item-btn" data-item-id="${item.id}">编辑</button>
                    <button type="button" class="delete-item-btn" data-item-id="${item.id}">删除</button>
                  </td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      </div>
    `;

    // Attach handlers
    container.querySelector("#addShopItem").addEventListener("click", () => showItemEditModal());

    container.querySelectorAll(".edit-item-btn").forEach(btn => {
      btn.addEventListener("click", (e) => {
        const itemId = e.target.getAttribute("data-item-id");
        const item = items.find(i => i.id == itemId);
        showItemEditModal(item);
      });
    });

    container.querySelectorAll(".delete-item-btn").forEach(btn => {
      btn.addEventListener("click", async (e) => {
        const itemId = e.target.getAttribute("data-item-id");
        if (await deleteShopItem(itemId)) {
          renderShopManagementPanel(container);
        }
      });
    });
  }

  // Show item edit modal
  function showItemEditModal(item = null) {
    const isEdit = !!item;

    const modal = document.createElement("div");
    modal.className = "modal-overlay";
    modal.innerHTML = `
      <div class="modal-content">
        <div class="modal-header">
          <h2>${isEdit ? '编辑商品' : '添加商品'}</h2>
          <button class="modal-close" type="button">×</button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label>商品名称</label>
            <input type="text" id="itemName" value="${escape(item?.name)}" placeholder="输入商品名称" />
          </div>
          <div class="form-group">
            <label>商品描述</label>
            <textarea id="itemDescription" placeholder="输入商品描述">${escape(item?.description)}</textarea>
          </div>
          <div class="form-group">
            <label>商品图标</label>
            <input type="file" id="itemIcon" accept="image/*" />
            ${item?.icon ? `<div class="current-icon"><img src="${escape(item.icon)}" alt="当前图标" style="max-width: 100px; max-height: 100px; margin-top: 8px;" /><p class="muted">留空保持当前图标</p></div>` : '<p class="muted">可选：上传商品展示图片</p>'}
          </div>
          <div class="form-group">
            <label>价格 (RBC)</label>
            <input type="number" id="itemPrice" value="${item?.price || 1}" min="1" />
          </div>
          <div class="form-group">
            <label>库存 (-1表示无限)</label>
            <input type="number" id="itemStock" value="${item?.stock !== undefined ? item.stock : -1}" />
          </div>
          <div class="form-group">
            <label>商品类型</label>
            <select id="itemType">
              <option value="general" ${item?.item_type === 'general' ? 'selected' : ''}>普通商品</option>
              <option value="makeup_ticket" ${item?.item_type === 'makeup_ticket' ? 'selected' : ''}>补签券</option>
              <option value="consumable" ${item?.item_type === 'consumable' ? 'selected' : ''}>消耗品</option>
            </select>
          </div>
          <div class="form-group">
            <label>
              <input type="checkbox" id="itemActive" ${item?.is_active !== false ? 'checked' : ''} />
              上架销售
            </label>
          </div>
        </div>
        <div class="modal-footer">
          <button type="button" class="secondary-button modal-cancel">取消</button>
          <button type="button" class="primary-button modal-save">保存</button>
        </div>
      </div>
    `;

    document.body.appendChild(modal);

    // Close handlers
    modal.querySelector(".modal-close").addEventListener("click", () => modal.remove());
    modal.querySelector(".modal-cancel").addEventListener("click", () => modal.remove());

    // Save handler
    modal.querySelector(".modal-save").addEventListener("click", async event => {
      const saveButton=event.currentTarget;
      if(saveButton.disabled)return;
      saveButton.disabled=true;
      try {
      const iconFile = document.getElementById("itemIcon").files[0];
      let iconData = null;

      // Convert image to base64 if provided
      if (iconFile) {
        try {
          iconData = await new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = (e) => resolve(e.target.result);
            reader.onerror = reject;
            reader.readAsDataURL(iconFile);
          });
        } catch (error) {
          alert("图片读取失败");
          return;
        }
      }

      const itemData = {
        name: document.getElementById("itemName").value.trim(),
        description: document.getElementById("itemDescription").value.trim(),
        price: parseInt(document.getElementById("itemPrice").value),
        stock: parseInt(document.getElementById("itemStock").value),
        item_type: document.getElementById("itemType").value,
        is_active: document.getElementById("itemActive").checked,
      };

      if (iconData) {
        itemData.icon = iconData;
      }

      if (!itemData.name) {
        alert("请输入商品名称");
        return;
      }

      if (isEdit) {
        itemData.item_id = item.id;
        if (await updateShopItem(itemData)) {
          modal.remove();
          // Refresh shop management panel
          const container = document.querySelector(".shop-management-panel")?.parentElement;
          if (container) {
            renderShopManagementPanel(container);
          }
        }
      } else {
        if (await createShopItem(itemData)) {
          modal.remove();
          // Refresh shop management panel
          const container = document.querySelector(".shop-management-panel")?.parentElement;
          if (container) {
            renderShopManagementPanel(container);
          }
        }
      }
      } finally {saveButton.disabled=false;}
    });
  }

  function showBalanceAdjustment(member) {
    const modal=document.createElement('div'); modal.className='modal-overlay';
    modal.innerHTML=`<form class="modal-content currency-adjust-modal" role="dialog" aria-modal="true" aria-label="调整 RBC 余额"><div class="modal-header"><h2>调整 ${escape(member.name)} 的余额</h2><button type="button" class="modal-close" aria-label="关闭">×</button></div><div class="modal-body"><p>当前余额：${member.currency_balance} RBC</p><label>调整金额（正数增加，负数扣除）<input name="amount" type="number" min="-100000" max="100000" required></label><label>调整说明<input name="description" maxlength="200" value="管理员调整" required></label><p role="status"></p></div><div class="modal-footer"><button class="primary-button" type="submit">确认调整</button></div></form>`;
    document.body.append(modal);modal.querySelector('.modal-close').onclick=()=>modal.remove();
    modal.querySelector('form').onsubmit=async event=>{
      event.preventDefault();const form=event.target, button=event.submitter;button.disabled=true;
      try {
        const response=await window.clubApi.request('/api/currency/admin/adjust',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({member_id:member.id,amount:Number(form.elements.amount.value),description:form.elements.description.value})});
        const result=await response.json();if(!response.ok)throw new Error(result.error || '调整失败');
        modal.remove();await loadMembersLive();await window.CurrencyModule.init();showToast(`余额已更新为 ${result.new_balance} RBC`);
      } catch(error){modal.querySelector('[role="status"]').textContent=error.message;} finally{button.disabled=false;}
    };
    modal.querySelector('[name="amount"]').focus();
  }

  // Public API
  return {
    loadConfig,
    saveConfig,
    adjustBalance,
    showBalanceAdjustment,
    renderConfigPanel,
    renderShopManagementPanel,
  };
})();

// Export for use in other modules
if (typeof window !== "undefined") {
  window.CurrencyAdminModule = CurrencyAdminModule;
}
