/* Personal page: enters from and returns to the right; keeps the main view intact. */
(() => {
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const number = value => typeof value === 'number' ? value.toLocaleString('zh-CN') : '—';
  let page, data, opened = false, closing = false, poll, objectURL, allowed = false, generation = 0;
  const entry = document.getElementById('openProfile');
  const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches;

  async function request(url, options = {}) {
    const response = await window.clubApi.request(url, options);
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || '请求失败，请稍后重试');
    return payload;
  }
  function updateHeader(info) {
    if (!entry) return;
    entry.querySelector('strong').textContent = info.name;
    const avatar = entry.querySelector('.profile-avatar');
    avatar.replaceChildren();
    if (info.avatar) {
      const image = document.createElement('img'); image.src = info.avatar + '?v=' + Date.now(); image.alt = '';
      avatar.append(image);
    } else avatar.textContent = (info.name || '').slice(0, 1);
  }
  function message(text, bad = false) {
    const target = page.querySelector('#profileMessage');
    target.textContent = text; target.classList.toggle('is-error', bad);
  }
  function avatarPreview(url, name) {
    const target = page.querySelector('#personalAvatar'); target.replaceChildren();
    if (url) { const image = document.createElement('img'); image.src = url; image.alt = '头像预览'; target.append(image); }
    else target.textContent = (name || '').slice(0, 1);
  }
  function renderGrade() {
    page.querySelector('#personalGrade').textContent = data.grade_label;
    page.querySelector('#gradeHelp').textContent = '年级仅在注册时选择，之后按 2 月 15 日、8 月 1 日自动晋级。';
  }
  function buildPage() {
    page = document.createElement('section'); page.id = 'personalPage'; page.className = 'personal-page';
    page.hidden = true; page.setAttribute('role', 'dialog'); page.setAttribute('aria-modal', 'true');
    page.setAttribute('aria-labelledby', 'personalTitle');
    page.innerHTML = `
      <div class="personal-top"><button id="profileBack" class="personal-back" aria-label="返回主页面" type="button">&lt;</button><span>个人空间</span><small>PROFILE & ACCOUNTS</small></div>
      <main class="personal-content">
        <header class="personal-heading"><p class="kicker">YOUR ALGORITHM JOURNEY</p><h1 id="personalTitle">个人信息</h1><p>整理你的个人资料，连接各个平台的训练足迹。</p></header>
        <p id="profileMessage" class="profile-message" role="status" aria-live="polite"></p>
        <div id="profileLoading" class="personal-loading">正在读取个人资料…</div>
        <div id="profileBody" hidden>
          <section class="personal-basics" aria-labelledby="basicsTitle">
            <div class="personal-section-copy"><span class="personal-step">01 / ABOUT YOU</span><h2 id="basicsTitle">基本资料</h2><p id="personalAccount"></p></div>
            <form id="personalForm" class="personal-form">
              <div class="personal-avatar-field"><span id="personalAvatar" class="personal-avatar"></span><label class="avatar-picker">更换头像<input id="personalAvatarFile" name="avatar" type="file" accept="image/png,image/jpeg,image/webp"></label><small>PNG / JPEG / WebP · 最大 3 MB</small></div>
              <div class="personal-name-field"><label for="personalName">昵称</label><input id="personalName" name="name" required maxlength="40" autocomplete="nickname"><small id="nicknameScope"></small><label for="personalGrade">年级</label><span id="personalGrade"></span><small id="gradeHelp"></small><button type="submit" class="primary-button">保存个人资料</button></div>
            </form>
          </section>
          <section class="personal-basics personal-password" aria-labelledby="passwordTitle"><div><h2 id="passwordTitle">修改密码</h2><p class="muted">验证当前密码后设置新密码。</p></div><form id="personalPasswordForm" class="personal-name-field"><label>当前密码<input type="password" name="old_password" autocomplete="current-password" required></label><label>新密码<input type="password" name="new_password" autocomplete="new-password" minlength="8" maxlength="128" required></label><label>确认新密码<input type="password" name="confirm_password" autocomplete="new-password" minlength="8" maxlength="128" required></label><button type="submit" class="primary-button">修改密码</button><p id="passwordMessage" role="status"></p></form></section>
          <section class="personal-platform-section" aria-labelledby="platformTitle"><div class="personal-platform-heading"><div><span class="personal-step">02 / CONNECT YOUR PLATFORMS</span><h2 id="platformTitle">算法平台</h2><p>绑定公开账号，查看 Rating、比赛表现与做题信息。</p></div><span id="bindingCount" class="binding-count"></span></div>
            <p class="profile-binding-note">绑定表示关联公开资料，不代表平台官方身份认证。无需提供第三方密码；同步失败时保留上次成功数据。</p>
            <div id="platformGrid" class="platform-grid"></div>
          </section>
        </div>
      </main>`;
    document.body.append(page);
    page.querySelector('#platformGrid').addEventListener('focusout', () => {
      setTimeout(() => { if (opened && data) renderBindings(); }, 0);
    });
    page.querySelector('#profileBack').onclick = back;
    page.querySelector('#personalAvatarFile').onchange = event => {
      const file = event.target.files[0];
      if (objectURL) URL.revokeObjectURL(objectURL);
      objectURL = null;
      if (!file) { avatarPreview(data.avatar, data.name); return; }
      if (file.size > 3 * 1024 * 1024 || !['image/png','image/jpeg','image/webp'].includes(file.type)) {
        event.target.value = ''; avatarPreview(data.avatar, data.name); message('请选择不超过 3 MB 的 PNG、JPEG 或 WebP 图片', true); return;
      }
      objectURL = URL.createObjectURL(file); avatarPreview(objectURL, data.name); message('头像已预览，点击“保存个人资料”后生效');
    };
    page.querySelector('#personalPasswordForm').onsubmit=async event=>{
      event.preventDefault();const form=event.target,button=form.querySelector('button'),status=page.querySelector('#passwordMessage');button.disabled=true;
      try{await request('/api/profile/password',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(Object.fromEntries(new FormData(form)))});form.reset();status.textContent='密码已修改，当前登录已保留。';}catch(error){status.textContent=error.message;}finally{button.disabled=false;}
    };
    page.querySelector('#personalForm').onsubmit = async event => {
      event.preventDefault();
      const button = event.target.querySelector('button[type="submit"]'); button.disabled = true;
      try {
        const result = await request('/api/profile', {method:'POST', body:new FormData(event.target)});
        data = result; renderGrade(); updateHeader(result); message('个人资料已保存');
        window.dispatchEvent(new CustomEvent('personal-profile-saved'));
        page.querySelector('#personalName').value = result.name;
        page.querySelector('#personalAvatarFile').value = '';
        if (objectURL) URL.revokeObjectURL(objectURL); objectURL = null;
        avatarPreview(result.avatar ? result.avatar + '?v=' + Date.now() : null, result.name);
      } catch (error) { message(error.message, true); }
      finally { button.disabled = false; }
    };
    page.addEventListener('keydown', event => {
      if (event.key === 'Escape') { event.preventDefault(); back(); }
      if (event.key === 'Tab') {
        const items = [...page.querySelectorAll('button:not([disabled]),input:not([disabled]),select:not([disabled]),a[href],summary')].filter(el => el.getClientRects().length);
        const first = items[0], last = items[items.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }
    });
  }
  function metrics(binding) {
    const stats = binding.snapshot || {};
    if (!Object.keys(stats).length) return '<div class="platform-empty">绑定后将在这里展示公开训练数据</div>';
    const history = stats.rating_history || [];
    const difficulty = stats.difficulty || [];
    return `<div class="platform-metrics"><div><span>当前 Rating</span><strong>${number(stats.rating)}</strong></div><div><span>最高 Rating</span><strong>${number(stats.max_rating)}</strong></div><div><span>${escape(stats.solved_label || '通过题数')}</span><strong>${number(stats.solved)}</strong></div></div>
      <div class="platform-extra">${stats.rank ? `<span>${escape(stats.rank)}</span>` : ''}${typeof stats.contests === 'number' ? `<span>${number(stats.contests)} 场 Rated 比赛</span>` : ''}${difficulty.map(d => `<span>${escape(d.label)} ${number(d.count)}</span>`).join('')}</div>
      ${history.length ? `<details class="rating-details"><summary>最近比赛 Rating <span>${history.length} 场</span></summary><ol>${history.slice().reverse().map(r => `<li><span>${escape(r.name)}</span><strong>${number(r.rating)}</strong></li>`).join('')}</ol></details>` : ''}
      ${(stats.notes || []).map(note => `<p class="platform-note">${escape(note)}</p>`).join('')}`;
  }
  function renderCard(card, platform, binding) {
    const meta = data.platforms[platform];
    const busy = binding?.status === 'pending';
    const status = !binding ? '未绑定' : busy ? '同步中' : binding.status === 'failed' ? '待重试' : '已绑定';
    card.innerHTML = `<div class="platform-card-head"><span class="platform-monogram" data-platform="${platform}">${escape(meta.short)}</span><div><h3>${escape(meta.name)}</h3><small>${escape(binding?.account || meta.hint)}</small></div><span class="platform-status ${busy ? 'pending' : binding?.status || ''}">${status}</span></div>
      ${binding ? metrics(binding) : '<div class="platform-empty">连接账号，汇总你的比赛与做题表现</div>'}
      ${binding?.error ? `<p class="platform-error" role="status">${escape(binding.error)}${binding.synced_at ? '；以下为上次成功数据。' : ''}</p>` : ''}
      ${binding?.synced_at ? `<p class="platform-updated">上次成功同步 · ${escape(new Date(binding.synced_at).toLocaleString('zh-CN'))}</p>` : ''}
      <form class="platform-bind-form"><label for="account-${platform}">${escape(meta.hint)}</label><div><input id="account-${platform}" name="account" required maxlength="100" value="${escape(binding?.account || '')}" autocomplete="off"><button class="secondary-button" type="submit" ${busy ? 'disabled' : ''}>${binding ? '更新绑定' : '绑定账号'}</button></div></form>
      ${binding ? `<div class="platform-actions"><button type="button" data-refresh ${busy ? 'disabled' : ''}>${busy ? '正在获取资料…' : '↻ 同步资料'}</button>${binding.snapshot?.profile_url ? `<a href="${escape(binding.snapshot.profile_url)}" target="_blank" rel="noopener noreferrer">平台主页 ↗</a>` : ''}<button type="button" data-unbind>解绑</button></div>` : ''}
      <p class="platform-action-message" role="status"></p>`;
    card.querySelector('form').onsubmit = event => {
      event.preventDefault(); act(card, platform, 'PUT', {account:new FormData(event.target).get('account')});
    };
    card.querySelector('[data-refresh]')?.addEventListener('click', () => act(card, platform, 'POST'));
    card.querySelector('[data-unbind]')?.addEventListener('click', () => {
      if (confirm(`解除 ${meta.name} 的账号关联？平台上的账号和记录不会被删除。`)) act(card, platform, 'DELETE');
    });
    card.dataset.signature = JSON.stringify(binding || null);
  }
  function renderBindings() {
    const grid = page.querySelector('#platformGrid');
    for (const platform of Object.keys(data.platforms)) {
      let card = grid.querySelector(`[data-platform-card="${platform}"]`);
      if (!card) { card = document.createElement('article'); card.className = 'platform-card'; card.dataset.platformCard = platform; grid.append(card); }
      const binding = data.bindings.find(b => b.platform === platform);
      // Polling must not overwrite an account currently being edited.
      if (!card.contains(document.activeElement) && card.dataset.signature !== JSON.stringify(binding || null)) renderCard(card, platform, binding);
    }
    page.querySelector('#bindingCount').textContent = `${data.bindings.length} / ${Object.keys(data.platforms).length} 已关联`;
  }
  async function act(card, platform, method, payload) {
    card.querySelectorAll('button').forEach(button => button.disabled = true);
    const output = card.querySelector('.platform-action-message'); output.textContent = '正在保存…';
    try {
      await request('/api/profile/platforms/' + platform, {method, headers:{'Content-Type':'application/json'}, ...(payload ? {body:JSON.stringify(payload)} : {})});
      data = await request('/api/profile');
      renderCard(card, platform, data.bindings.find(b => b.platform === platform)); renderBindings(); schedulePoll();
    } catch (error) {
      output.textContent = error.message; card.querySelectorAll('button').forEach(button => button.disabled = false);
    }
  }
  function schedulePoll() {
    clearTimeout(poll);
    if (!opened || !data?.bindings.some(b => b.status === 'pending')) return;
    const version = generation;
    poll = setTimeout(async () => {
      try {
        const result = await request('/api/profile');
        if (!opened || version !== generation) return;
        data.bindings = result.bindings; renderBindings(); schedulePoll();
      } catch (error) { if (opened) message('同步状态读取失败，请重新打开个人页查看', true); }
    }, 3000);
  }
  async function open(push = true) {
    if (!allowed || opened || closing) return;
    if (!page) buildPage();
    opened = true; generation++;
    if (push && location.hash !== '#profile') history.pushState({...history.state, personalPage:true}, '', '#profile');
    page.hidden = false; document.querySelector('.app-shell').inert = true; document.body.classList.add('personal-open');
    page.animate([{transform:'translateX(100%)'}, {transform:'translateX(0)'}], {duration:reduced() ? 0 : 320, easing:'cubic-bezier(.2,.75,.25,1)'});
    page.querySelector('#profileBack').focus();
    const version = generation;
    try {
      const result = await request('/api/profile');
      if (!opened || version !== generation) return;
      data = result;
      renderGrade();
      page.querySelector('#profileLoading').hidden = true; page.querySelector('#profileBody').hidden = false;
      // Keep unsaved edits when returning to the page.
      if (!page.dataset.loaded) {
        page.querySelector('#personalName').value = data.name; avatarPreview(data.avatar, data.name); page.dataset.loaded = 'true';
      }
      page.querySelector('#personalAccount').textContent = `登录账号：${data.account}`;
      page.querySelector('#nicknameScope').textContent = `昵称用于当前团队「${data.team_name}」；头像与平台绑定在你的团队间共享。`;
      renderBindings(); schedulePoll();
    } catch (error) { if (opened) { page.querySelector('#profileLoading').hidden = true; message(error.message, true); } }
  }
  async function close() {
    if (!opened || closing) return;
    opened = false; closing = true; generation++; clearTimeout(poll);
    await page.animate([{transform:'translateX(0)'}, {transform:'translateX(100%)'}], {duration:reduced() ? 0 : 260, easing:'cubic-bezier(.4,0,.8,.3)'}).finished;
    page.hidden = true; closing = false; document.querySelector('.app-shell').inert = false; document.body.classList.remove('personal-open'); entry.focus();
    if (location.hash === '#profile') open(false);
  }
  function back() {
    if (closing) return;
    if (history.state?.personalPage) history.back();
    else { history.replaceState(history.state, '', location.pathname + location.search); close(); }
  }
  addEventListener('popstate', () => { if (location.hash === '#profile') open(false); else close(); });
  entry?.addEventListener('click', () => open());
  window.PersonalProfile = {
    init(me) { allowed = !me.site_admin && !!me.can_submit; entry.disabled = !allowed; updateHeader(me); if (location.hash === '#profile') open(false); },
    updateHeader,
  };
})();
