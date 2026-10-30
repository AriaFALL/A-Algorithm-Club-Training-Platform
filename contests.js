/* Date-grouped calendar, rendered independently of team training data. */
(() => {
  const el = id => document.getElementById(id);
  const names = {codeforces:'Codeforces', atcoder:'AtCoder', nowcoder:'牛客', luogu:'洛谷', leetcode:'LeetCode'};
  const escape = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const date = (seconds, options) => new Intl.DateTimeFormat('zh-CN', {timeZone:'Asia/Shanghai', ...options}).format(new Date(seconds * 1000));
  const day = seconds => date(seconds, {year:'numeric',month:'2-digit',day:'2-digit'});
  const hm = seconds => date(seconds, {hour:'2-digit',minute:'2-digit',hourCycle:'h23'});
  let data = null, tab = 'upcoming', page = 1, inFlight = null, loadedAt = 0, timer = null, active = false;
  let progress = {contests:[],status:'idle'}, progressTimer = null, claiming = false;
  const expanded = new Set();
  const overview = document.querySelector('.contest-overview');
  const nextTime = el('contestNextTime');
  let overviewFrame = 0, overviewWidth = -1;
  const fitOverview = () => {
    overviewFrame = 0;
    overview.classList.remove('next-on-second-row');
    if (innerWidth <= 760 || !nextTime.getClientRects().length) return;
    // Measure the real single-row layout, including the current localized time text.
    const range = document.createRange(); range.selectNodeContents(nextTime);
    const lines = new Set([...range.getClientRects()].filter(rect => rect.width > 0).map(rect => Math.round(rect.top)));
    overview.classList.toggle('next-on-second-row', lines.size > 1);
  };
  const scheduleOverview = () => { if (!overviewFrame) overviewFrame = requestAnimationFrame(fitOverview); };
  new ResizeObserver(entries => {
    const width = entries[0].contentRect.width;
    if (width !== overviewWidth) { overviewWidth = width; scheduleOverview(); }
  }).observe(overview);
  new MutationObserver(scheduleOverview).observe(nextTime, {childList:true, characterData:true, subtree:true});
  addEventListener('resize', scheduleOverview);
  document.fonts?.ready.then(scheduleOverview);
  function syncContestTabs() {
    const group = document.querySelector('.contest-tabs');
    const selected = group?.querySelector('.segment.active');
    if (!group || !selected) return;
    let indicator = group.querySelector('.segment-indicator');
    if (!indicator) {
      indicator = document.createElement('i');
      indicator.className = 'segment-indicator';
      indicator.setAttribute('aria-hidden', 'true');
      group.prepend(indicator);
    }
    group.style.setProperty('--segment-x', `${selected.offsetLeft}px`);
    group.style.setProperty('--segment-width', `${selected.offsetWidth}px`);
  }
  const now = () => data ? data.server_time + (Date.now() - loadedAt) / 1000 : Date.now() / 1000;
  const phase = c => now() < c.start ? 'upcoming' : now() < c.end ? 'running' : 'finished';
  const span = seconds => { const mins = Math.max(1, Math.ceil(seconds / 60)); return mins >= 1440 ? `${Math.floor(mins/1440)} 天 ${Math.floor(mins%1440/60)} 小时` : mins >= 60 ? `${Math.floor(mins/60)} 小时${mins%60 ? ` ${mins%60} 分` : ''}` : `${mins} 分钟`; };

  function render() {
    if (!data && tab !== 'attended') return;
    const calendar = data || {contests:[],sources:[]};
    const current = now();
    const all = calendar.contests.filter(c => c.end >= current - 7*86400 && c.start <= current + 90*86400);
    const future = all.filter(c => phase(c) === 'upcoming').sort((a,b) => a.start-b.start);
    el('contestWeekCount').textContent = future.filter(c => c.start <= current+7*86400).length;
    el('contestRunningCount').textContent = all.filter(c => phase(c) === 'running').length;
    el('contestNextName').textContent = future[0]?.name || '暂无已获取的排期';
    el('contestNextTime').textContent = future[0] ? `${date(future[0].start,{month:'long',day:'numeric',weekday:'short'})} ${hm(future[0].start)} · ${span(future[0].start-current)}后开始` : '统一使用北京时间 · UTC+8';
    el('contestWindowLabel').textContent = tab === 'attended' ? '全部已同步参赛历史 · 北京时间' : '未来 90 天 / 最近结束 7 天 · 北京时间';
    const terms = el('contestSearch').value.normalize('NFKC').trim().toLowerCase().split(/\s+/).filter(Boolean);
    const platform = el('contestPlatform').value;
    const matches = (tab === 'attended' ? progress.contests : all).filter(c => (tab === 'attended' || phase(c) === tab) && (!platform || c.platform === platform) && terms.every(q => `${c.name} ${names[c.platform]}`.normalize('NFKC').toLowerCase().includes(q)))
      .sort((a,b) => tab === 'upcoming' ? a.start-b.start : tab === 'running' ? a.end-b.end : b.end-a.end);
    const pages = Math.max(1,Math.ceil(matches.length/12));
    page = Math.min(page,pages);
    el('contestResultCount').textContent = `共 ${matches.length} 场比赛`;
    el('contestPageNumber').textContent = `${page} / ${pages}`;
    el('contestPrev').disabled = page === 1;
    el('contestNext').disabled = page === pages;
    document.querySelectorAll('[data-contest-tab]').forEach(b => {
      const selected = b.dataset.contestTab === tab;
      b.setAttribute('aria-pressed',String(selected));
      b.classList.toggle('active', selected);
    });
    syncContestTabs();
    const groups = new Map();
    matches.slice((page-1)*12,page*12).forEach(c => { const key = day(c.start); if (!groups.has(key)) groups.set(key,[]); groups.get(key).push(c); });
    const failed = calendar.sources.every(s => s.error && !s.stale);
    el('contestResults').innerHTML = matches.length ? [...groups].map(([key,items]) => {
      const relative = key === day(current) ? '今天 · ' : key === day(current+86400) ? '明天 · ' : '';
      return `<section class="contest-day"><h2>${relative}${date(items[0].start,{month:'long',day:'numeric',weekday:'short'})}<small>${items.length} 场</small></h2><div class="contest-grid">${items.map(c => {
        if (tab === 'attended') return attendedCard(c);
        const timing = tab === 'upcoming' ? `${span(c.start-current)}后开始` : tab === 'running' ? `剩余 ${span(c.end-current)}` : '已结束';
        return `<article class="contest-card ${escape(c.platform)}"><div class="contest-card-top"><span class="contest-platform">${escape(names[c.platform])}</span><span class="contest-phase ${tab}">${timing}</span></div><h3>${escape(c.name)}</h3><div class="contest-card-time"><strong>${hm(c.start)}</strong><span>开始 · 时长 ${span(c.end-c.start)}</span></div><div class="contest-card-bottom"><small>结束于 ${date(c.end,{month:'numeric',day:'numeric'})} ${hm(c.end)}</small><a href="${escape(c.url)}" target="_blank" rel="noopener noreferrer">${tab === 'finished' ? '查看比赛' : '前往比赛'} <span aria-hidden="true">↗</span><span class="contest-sr">（新窗口打开）</span></a></div></article>`;
      }).join('')}</div></section>`;
    }).join('') : `<div class="contest-empty"><span aria-hidden="true">▦</span><h2>${failed ? '赛程暂时无法获取' : '暂无符合条件的比赛'}</h2><p>${failed ? '请稍后点击刷新日程重试，或直接访问各平台官网。' : '试试切换比赛状态、平台，或清空搜索条件。'}</p></div>`;
    el('contestSourceStatus').innerHTML = calendar.sources.map(s => `<span class="${s.error ? 'source-warning' : ''}" title="${escape(s.updated_at ? '上次成功更新：'+date(Date.parse(s.updated_at)/1000,{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'}) : '尚无成功更新')}">${escape(s.name)} · ${escape(s.error || '已更新')}</span>`).join('');
  }

  async function load(refresh = false) {
    if (inFlight) return inFlight;
    el('contestRefresh').disabled = true;
    el('contestRefresh').textContent = refresh ? '正在更新…' : '正在加载…';
    el('contestResults').setAttribute('aria-busy','true');
    inFlight = (async () => {
      try {
        const response = await window.clubApi.request('/api/contests' + (refresh ? '?refresh=1' : ''));
        if (!response.ok) throw new Error(response.status === 401 ? '登录已过期，请重新登录后查看赛程。' : '赛程加载失败，请稍后重试。');
        data = await response.json(); loadedAt = Date.now(); render();
      } catch (error) {
        el('contestSourceStatus').textContent = error.message;
        if (!data) {
          el('contestResults').innerHTML = '<div class="contest-empty"><h2>赛程加载失败</h2><p>点击右上方「刷新日程」重试。</p></div>';
          el('contestNextName').textContent = '暂时无法获取';
        }
      } finally {
        el('contestRefresh').disabled = false;
        el('contestRefresh').textContent = '↻ 刷新日程';
        el('contestResults').setAttribute('aria-busy','false');
        inFlight = null;
      }
    })();
    return inFlight;
  }

  function attendedCard(c) {
    const open = expanded.has(c.id);
    return `<article class="contest-entry ${open ? 'is-expanded' : ''}" data-participation="${escape(c.id)}">
      <div class="contest-card attended ${escape(c.platform)} ${c.claimable_count && !open ? 'reward-shake' : ''}">
        <button type="button" class="contest-expand" data-expand="${escape(c.id)}" aria-expanded="${open}" aria-controls="drawer-${escape(c.id)}">
          <span class="contest-card-top"><span class="contest-platform">${escape(names[c.platform])}${c.is_demo ? ' · 演示' : ''}</span><span class="contest-phase">${c.claimable_count ? c.claimable_count+' 项奖励待领取' : '已参加'}</span></span>
          <strong class="attended-title">${escape(c.name)}</strong>
          <span class="contest-card-time"><strong>${hm(c.start)}</strong><span>开始 · 时长 ${span(c.end-c.start)}</span></span>
          <span class="contest-card-bottom"><small>${day(c.start)} · ${escape(c.account)}</small><span class="drawer-indicator">${open ? '收起题目 ∧' : '展开题目 ∨'}</span></span>
        </button>
      </div>
      <div id="drawer-${escape(c.id)}" class="contest-problem-drawer ${open ? 'is-open' : ''}" ${open ? '' : 'inert'}><div><div class="contest-problem-tray">
        <div class="contest-progress-problems" aria-label="比赛题目">${c.problems.map(p => `<button type="button" data-claim="${p.id}" class="contest-problem ${p.accepted ? 'is-ac' : ''} ${p.claimable ? 'reward-shake claimable' : ''}" ${p.claimable ? '' : 'disabled'} title="${escape(p.title+' · '+(p.claimed ? '已领取' : p.claimable ? '领取 '+p.reward+' RBC Coins'+(p.timing_relaxed ? '（已确认 AC，时间无法核验，宽松奖励）' : '') : p.reason))}"><strong>${escape(p.label)}</strong><small>${p.claimed ? '已领取' : p.claimable ? '+'+p.reward+' RBC' : p.accepted ? 'AC' : '—'}</small></button>`).join('') || '<span class="contest-evidence-note">正在获取题目进度</span>'}</div>
        ${c.sync_error ? `<p class="contest-evidence-note">${escape(c.sync_error)}</p>` : ''}
        <a class="contest-original-link" href="${escape(c.url)}" target="_blank" rel="noopener noreferrer" title="查看原比赛">↗</a>
      </div></div></div>
    </article>`;
  }
  async function api(url, options) {
    const r = await window.clubApi.request(url, options);
    const j = await r.json();
    if (!r.ok) {const error=new Error(j.error || '操作失败，请稍后重试');error.status=r.status;throw error;}
    return j;
  }
  function progressControls() {
    const count = progress.contests.reduce((n,c) => n+c.claimable_count,0);
    el('contestClaimAll').hidden = count < 2;
    el('contestClaimAll').textContent = `一键领取奖励（${count}）`;
    document.querySelector('[data-contest-tab="attended"]').hidden = !progress.contests.length;
    el('contestSync').disabled = progress.status === 'pending';
    el('contestSync').textContent = progress.status === 'pending' ? '正在同步…' : '↻ 同步比赛进度';
    el('contestProgressStatus').textContent = progress.status === 'pending' ? `正在核验比赛进度${progress.total ? ' '+(progress.total-progress.remaining)+' / '+progress.total : ''}…` : Object.entries(progress.messages || {}).map(([p,m]) => `${names[p] || "系统"}：${m}`).join('；');
    if (progress.status === 'failed') el('contestProgressStatus').textContent = Object.values(progress.messages || {}).join('；') || '本次同步超时或失败，已保留已有记录，请重试。';
  }
  async function loadProgress() {
    clearTimeout(progressTimer);
    try {
      progress = await api('/api/contests/progress');
      el('contestSync').hidden = false;
      progressControls(); if(tab === 'attended' && !claiming) render();
      if (active && progress.status === 'pending') progressTimer = setTimeout(loadProgress,4000);
    } catch(error) {if(error.status===403){el('contestSync').hidden=true;el('contestClaimAll').hidden=true;el('contestProgressStatus').textContent='';}else el('contestProgressStatus').textContent=error.message;}
  }
  el('contestSync').addEventListener('click',async () => {
    el('contestSync').disabled = true;
    try {await api('/api/contests/progress',{method:'POST'});await loadProgress();}
    catch(error) {el('contestProgressStatus').textContent=error.message;el('contestSync').disabled=false;}
  });
  el('contestResults').addEventListener('click',event => {
    const toggle = event.target.closest('[data-expand]');
    if (toggle) {
      const id=toggle.dataset.expand, open=!expanded.has(id);
      if(open) expanded.add(id);else expanded.delete(id);
      toggle.setAttribute('aria-expanded',String(open));
      toggle.querySelector('.drawer-indicator').textContent=open?'收起题目 ∧':'展开题目 ∨';
      const drawer=el('drawer-'+id);drawer.classList.toggle('is-open',open);drawer.inert=!open;
      const c=progress.contests.find(c=>c.id===id);const entry=toggle.closest('.contest-entry');entry.classList.toggle('is-expanded',open);entry.querySelector('.contest-card').classList.toggle('reward-shake',!!c.claimable_count&&!open);
    }
    const button=event.target.closest('[data-claim]');
    if(button&&!button.disabled) claim([Number(button.dataset.claim)],button);
  });
  async function claim(ids, button) {
    if(claiming)return;claiming=true;el('contestClaimAll').disabled=true;
    if(button)button.disabled=true;
    try {
      const result=await api('/api/contests/claim',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(ids ? {ids} : {})});
      if(button && result.total) {
        const float=document.createElement('span');float.className='coin-float';
        const icon=window.CurrencyModule?.getCurrencyData().currencyIcon || '/static/helloworld_coin.svg';
        float.innerHTML=`<img src="${escape(icon)}" alt="RBC Coins"> × ${result.total}`;
        await float.querySelector('img').decode().catch(()=>{});
        button.appendChild(float);button.classList.remove('reward-shake');
        await new Promise(resolve=>setTimeout(resolve,1100));
      } else {
        const dialog=document.createElement('dialog');dialog.className='contest-reward-summary';
        dialog.innerHTML=`<h2>奖励已领取</h2><p>共 ${result.claims.length} 题 · <strong>${result.total} RBC Coins</strong></p><ul>${result.claims.map(c=>`<li><span>${escape(c.contest)} · ${escape(c.label)}</span><strong>+${c.amount}</strong></li>`).join('')}</ul><form method="dialog"><button class="primary-button">完成</button></form>`;
        document.body.appendChild(dialog);dialog.addEventListener('close',()=>dialog.remove());dialog.showModal();
      }
      if(!result.total)el('contestProgressStatus').textContent='暂无可领取奖励，可能已经领取或核验条件已变化。';
      await window.CurrencyModule?.init();
    }catch(error){el('contestProgressStatus').textContent=error.message;}
    finally{claiming=false;el('contestClaimAll').disabled=false;await loadProgress();render();}
  }
  el('contestClaimAll').addEventListener('click',()=>claim());

  el('contestRefresh').addEventListener('click',() => load(true));
  el('contestSearch').addEventListener('input',() => {page=1;render();});
  el('contestPlatform').addEventListener('change',() => {page=1;render();});
  document.querySelectorAll('[data-contest-tab]').forEach(b => b.addEventListener('click',() => {tab=b.dataset.contestTab;page=1;render();}));
  el('contestPrev').addEventListener('click',() => {page--;render();});
  el('contestNext').addEventListener('click',() => {page++;render();});
  function tick() {if (!active || document.hidden) return; if (Date.now()-loadedAt >= 900000) load(); else render();}
  window.contestSchedule = {activate(value) {active=value;clearInterval(timer);clearTimeout(progressTimer);if(value){loadProgress();if(!data || Date.now()-loadedAt>60000) load();else render();timer=setInterval(tick,30000);}}};
  document.addEventListener('visibilitychange',tick);
})();
