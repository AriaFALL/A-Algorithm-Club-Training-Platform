const rankingData = {};
const rankingKey = (scope, platform='codeforces') => scope === 'rating' ? `${scope}:${platform}` : scope;
function rankingSelection(target) {
  const panel = document.querySelector(target)?.closest('.panel');
  return {scope: panel?.querySelector('[data-ranking].active')?.dataset.ranking || 'checkin',
    platform: panel?.querySelector('[data-rating-platform]')?.value || 'codeforces', panel};
}

const pageTitles = {extensions:'拓展', dashboard:'总览', submissions:'我的提交', leaderboard:'排行榜', showcase:'提交展示', members:'成员列表', contests:'比赛日程', admin:'管理工作台', rbcshop:'RBC商店'};
const $ = (selector, root=document) => root.querySelector(selector);
const $$ = (selector, root=document) => [...root.querySelectorAll(selector)];
let canManage = false;
const demoMode = false;
let countdownTimer = null;
let countdownDeadline = 0;
let countdownClosed = false;
let currentView = 'dashboard';
let adminQueueTimer = null;
let adminQueueInFlight = null;
let adminQueueAbortController = null;
let adminQueueRequestVersion = 0;
let mineSubmissionsInFlight = null;
let activityRequestVersion = 0;
let submissionsRequestVersion = 0;
let showcaseRequestVersion = 0;
let membersRequestVersion = 0;
let historyRequestVersion = 0;
const leaderboardInFlight = new Map();
let pulseDays = [];
let selectedPulseDate = '';
let pulseToday = '';
document.addEventListener('click', async (event) => { if (event.target.id !== 'logoutButton') return; await clubApi.request('/api/auth/logout', {method:'POST'}); window.location.href = '/auth.html'; });
const liveStyle = document.createElement('style'); liveStyle.textContent = '.my-submissions-live{margin-top:14px;padding:21px}.live-submission-row{display:flex;align-items:center;gap:12px;padding:13px 0;border-top:1px solid #edf0ee}.live-submission-info{display:flex;flex-direction:column;gap:4px;flex:1;min-width:0}.live-submission-info strong{font-size:12px}.live-submission-info small{font-size:10px;color:var(--muted)}.submission-thumb{width:44px;height:44px;border-radius:7px;background:#eef7f5;display:grid;place-items:center;overflow:hidden;color:var(--teal);flex:none}.submission-thumb img{width:100%;height:100%;object-fit:cover}.live-submission-row .review-view{color:var(--teal-dark);font-size:11px;font-weight:700;white-space:nowrap}.upload-preview{width:80px;height:55px;object-fit:cover;border-radius:6px;margin-bottom:4px}.status-tag.rejected{color:#b35d55;background:#fbeceb}'; document.head.appendChild(liveStyle);
const accessibilityStyle = document.createElement('style'); accessibilityStyle.textContent = '.toast{transition:transform .25s ease,opacity .25s ease}.search-box input:focus-visible{outline:2px solid var(--teal);outline-offset:2px}'; document.head.appendChild(accessibilityStyle);
const escapeHtml = (value='') => String(value).replace(/[&<>'"]/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
function memberAvatar(memberId, name, className='leader-avatar') {
  return `<span class="${className} synced-member-avatar" data-avatar-member="${Number(memberId)}">${escapeHtml((name || '').slice(0,1))}<img src="/api/members/${Number(memberId)}/avatar" alt="" loading="lazy" onerror="this.remove()" /></span>`;
}

function renderLeaderboard(mode='checkin', target='#leaderboardList') {
  const el = $(target);
  if (!el) return;
  const selection = rankingSelection(target);
  const allRows = rankingData[rankingKey(selection.scope,selection.platform)];
  const rows = target === '#leaderboardList' ? allRows?.filter(row => row.isCurrent) : allRows;
  const filter = selection.panel?.querySelector('.rating-platform-filter');
  if (filter) filter.hidden = selection.scope !== 'rating';
  el.innerHTML = !rows ? '<div class="queue-empty" role="status">正在加载榜单…</div>' : !rows.length
    ? `<div class="queue-empty">${target === '#leaderboardList' ? '你在当前榜单暂无排名' : selection.scope === 'rating' ? '当前团队暂无绑定此平台的成员' : '暂无排行榜数据'}</div>`
    : rows.map(row => `
      <button type="button" class="leader-row ${row.isCurrent ? 'you' : ''}" data-ranking-member="${row.memberId}" aria-label="查看${escapeHtml(row.name)}的历史提交">
        <span class="leader-rank ${row.rank && row.rank <= 3 ? 'top' : ''}">${row.rank || '—'}</span>
        <span class="leader-member">${memberAvatar(row.memberId,row.name)}<span class="leader-name">${escapeHtml(row.name)}${row.isCurrent ? '（你）' : ''}</span></span>
        <span class="leader-score">${row.value ?? '—'}<small> ${escapeHtml(row.unit)}</small></span>
        <span class="leader-count">${escapeHtml(row.detail)}${row.value === null ? ' · 暂无评级' : ''}</span>
      </button>`).join('');
  if (target === '#leaderboardList') {
    const current = rows?.find(row => row.isCurrent);
    if ($('#yourRankValue')) $('#yourRankValue').textContent = current?.rank ? `#${current.rank}` : '—';
    if ($('#yourRankChange')) $('#yourRankChange').textContent = {checkin:'当前连续签到',rating:'平台已同步 Rating',solved:'累计过题',wealth:'当前 Coins 余额'}[selection.scope];
  }
}

function setView(view) {
  if (view === 'rbcshop' && !window.CurrencyModule?.getCurrencyData().enabled) view = 'dashboard';
  if (view === 'admin' && !canManage) view = 'dashboard';
  if (view === currentView) return;
  const previousView = currentView;
  currentView = view;
  const nextView = $(`#${view}View`);
  $$('.page-view').forEach((el) => el.classList.toggle('active', el === nextView));
  $$('.nav-item[data-view]').forEach((el) => el.classList.toggle('active', el.dataset.view === view));
  $('#pageTitle').textContent = pageTitles[view] || '总览';
  // Hidden pages have zero-size tabs at startup; measure after making them visible.
  nextView?.querySelectorAll('.segmented').forEach(group => syncSegmented(group));
  // The overview owns its entrance animation; do not stack the route animation.
  if (nextView && view !== 'dashboard') {
    nextView.classList.remove('view-enter');
    void nextView.offsetWidth;
    nextView.classList.add('view-enter');
    const transitionId = String(Date.now());
    nextView.dataset.transitionId = transitionId;
    window.setTimeout(() => {
      if (nextView.dataset.transitionId === transitionId) nextView.classList.remove('view-enter');
    }, 1120);
  }
  window.scrollTo({top:0, behavior:'smooth'});
  if (view === 'dashboard') {const selected=rankingSelection('#leaderboardList');loadLeaderboard(selected.scope,selected.platform);}
  if (view === 'leaderboard') { const selected = rankingSelection('#leaderboardListFull'); renderLeaderboard(selected.scope, '#leaderboardListFull'); loadLeaderboard(selected.scope,selected.platform); }
  if (!demoMode && previousView === 'admin' && view !== 'admin') stopAdminQueuePolling();
  if (!demoMode && view === 'admin') startAdminQueuePolling();
  if (!demoMode && view === 'submissions') loadMySubmissions();
  if (!demoMode && view === 'showcase') loadShowcase();
  if (!demoMode && view === 'members') loadMembersLive();
  if (!demoMode && view === 'rbcshop' && window.CurrencyModule) {
    const shopView = document.getElementById('rbcshopView');
    if (shopView) window.CurrencyModule.renderShopView(shopView);
  }
  window.contestSchedule?.activate(view === 'contests');
  if (view === 'extensions') window.ExtensionResources.load();
}

function selectPulseDay(date) {
  const day = pulseDays.find(item => item.date === date);
  if (!day) return;
  selectedPulseDate = date;
  $$('.pulse-week').forEach(button => {
    const selected = button.dataset.pulseDate === date;
    button.classList.toggle('is-selected', selected);
    button.setAttribute('aria-selected', String(selected));
  });
  $('#pulseFocus').textContent = `${date} · ${day.isMakeup ? '已补签' : day.makeupOpen ? '已开放补交，待提交' : day.checkedIn && !day.hasSubmission ? '已签到' : day.submitted ? '已有有效提交' : '尚未提交'}`;
  const button = $('#openSubmission');
  const secondaryButton = $('#openSubmissionSecondary');
  const isFuture = date > pulseToday;
  const historical = date < pulseToday;
  const label = isFuture ? '暂未开放' : historical && day.isMakeup ? '当日已补签'
    : historical && day.submitted ? '当日已签到' : historical ? '补交当日记录' : '提交今日记录';
  const disabled = isFuture || !day.canSubmit || historical && (day.submitted || day.isMakeup);
  for (const entry of [button, secondaryButton].filter(Boolean)) {
    entry.innerHTML = `<span>＋</span>${label}`;
    entry.disabled = Boolean(disabled);
    entry.classList.toggle('disabled', Boolean(disabled));
    entry.classList.toggle('is-makeup-complete', historical && day.isMakeup);
  }

}

function wirePulseAtlas() {
  const track = $('.pulse-track');
  if (!track || track.dataset.wired) return;
  track.dataset.wired = 'true';
  let drag = null;
  let dragged = false;
  track.addEventListener('pointerdown', event => {
    if (event.pointerType === 'touch' || event.button !== 0) return;
    drag = {x:event.clientX, scroll:track.scrollLeft, id:event.pointerId};
    dragged = false;
  });
  track.addEventListener('pointermove', event => {
    if (!drag) return;
    const distance = event.clientX - drag.x;
    if (Math.abs(distance) > 5) { dragged = true; track.setPointerCapture(drag.id); }
    if (dragged) { track.scrollLeft = drag.scroll - distance; event.preventDefault(); }
  });
  track.addEventListener('pointerup', () => { drag = null; });
  track.addEventListener('pointercancel', () => { drag = null; });
  track.addEventListener('click', event => {
    if (dragged) { dragged = false; return; }
    const day = event.target.closest('[data-pulse-date]');
    if (day) selectPulseDay(day.dataset.pulseDate);
  });
}

function formatRemaining(seconds) {
  const total = Math.max(0, Number(seconds) || 0);
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  return `${days} 天 ${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
}

function startDeadlineCountdown(seconds, closed) {
  window.clearInterval(countdownTimer);
  countdownTimer = null;
  countdownClosed = Boolean(closed);
  countdownDeadline = Date.now() + Math.max(0, Number(seconds) || 0) * 1000;
  const render = () => {
    const remaining = Math.max(0, Math.ceil((countdownDeadline - Date.now()) / 1000));
    const welcome = $('.welcome-row .muted');
    if (welcome) welcome.textContent = countdownClosed ? '本周已截止' : `距离截止还有 ${formatRemaining(remaining)}`;
    const formNote = $('.form-note span:last-child');
    if (formNote && $('#submissionForm')?.dataset.makeup === '1') formNote.textContent = '已开放补交 · 学期结束前有效';
    else if (formNote) formNote.textContent = countdownClosed ? '本周已截止' : `距离截止还有 ${formatRemaining(remaining)}`;
    if (remaining <= 0 && !countdownClosed) {
      countdownClosed = true;
      window.clearInterval(countdownTimer);
      countdownTimer = null;
      render();
    }
  };
  render();
  if (closed || countdownDeadline <= Date.now()) return;
  countdownTimer = window.setInterval(render, 1000);
}

document.addEventListener('visibilitychange', () => {
  if (document.hidden) {
    window.clearInterval(countdownTimer);
    countdownTimer = null;
    stopAdminQueuePolling();
    return;
  }
  if (countdownDeadline && !countdownClosed) {
    startDeadlineCountdown(Math.ceil(Math.max(0, countdownDeadline - Date.now()) / 1000), false);
  }
  if (!demoMode && currentView === 'admin') startAdminQueuePolling();
});

function renderPulseDays(dashboard) {
  const track = $('.pulse-track');
  pulseDays = dashboard.pulse || [];
  pulseToday = dashboard.today;
  if (!track || !pulseDays.length) return;
  track.style.setProperty('--pulse-days', String(pulseDays.length));
  track.innerHTML = pulseDays.map((day, i) => `<button class="pulse-week ${day.submitted ? 'is-complete' : ''} ${day.makeupOpen ? 'is-unlocked' : ''} ${day.isToday ? 'is-current' : ''}" data-pulse-date="${day.date}" type="button" role="tab" aria-selected="false" aria-label="${day.date} ${day.isMakeup ? '已补签' : day.makeupOpen ? '已开放补交，待提交' : day.checkedIn && !day.hasSubmission ? '已签到' : day.submitted ? '已提交' : '未提交'}"><span>${day.date.slice(-2)}</span></button>`).join('') + '<i class="pulse-line" aria-hidden="true"></i>';
  const streakDays = Math.max(0, Math.trunc(Number(dashboard.streakDays) || 0));
  if ($('#streakValue')) $('#streakValue').innerHTML = `${streakDays} <small>天</small>`;
  const streakFoot = $('.metric-card:nth-child(4) .metric-foot span');
  if (streakFoot) streakFoot.textContent = '保持每天的训练节拍';
  const todayIndex = pulseDays.findIndex(day => day.date === pulseToday);
  const defaultDate = pulseDays.some(day => day.date === selectedPulseDate) ? selectedPulseDate : pulseDays.find(day => day.isToday)?.date || pulseDays[todayIndex >= 0 ? todayIndex : Math.floor(pulseDays.length / 2)].date;
  selectPulseDay(defaultDate);
  // Keep the selected date reachable when a historical submission refreshes the page.
  const selectedIndex = pulseDays.findIndex(day => day.date === defaultDate);
  if (selectedIndex >= 0) {
    const todayButton = track.children[selectedIndex];
    if (todayButton) {
      setTimeout(() => {
        const trackWidth = track.offsetWidth;
        const buttonLeft = todayButton.offsetLeft;
        const buttonWidth = todayButton.offsetWidth;
        track.scrollLeft = buttonLeft - (trackWidth / 2) + (buttonWidth / 2);
      }, 0);
    }
  }
}

function applyLiveDashboardState(dashboard, submissions = []) {
  const week = dashboard.current_week;
  const semester = dashboard.semester;
  if (!week || !semester) return;
  const score = Number(dashboard.score || 0);
  const submissionCount = Number(dashboard.submissions || 0);
  const minScore = Number(semester.minScore || 0);
  const minSubmissions = Number(semester.minSubmissions || 0);
  const stats = dashboard.stats || {};
  const scoreGap = Math.max(0, minScore - score);
  const submissionGap = Math.max(0, minSubmissions - submissionCount);
  const currentSubmissions = submissions.filter((item) => Number(item.week) === Number(week.number));
  const parts = currentSubmissions.flatMap((item) => item.parts || []);
  const pending = parts.filter((part) => part.status === 'pending');
  const pendingLabels = [...new Set(pending.map((part) => part.kind === 'proof' ? '截图' : part.kind === 'logic' ? '写题逻辑' : 'Blog'))];
  const presentKinds = new Set(parts.map((part) => part.kind));
  const missingLabels = [['proof', '通过截图'], ['logic', '写题逻辑'], ['blog', 'Blog']].filter(([kind]) => !presentKinds.has(kind)).map(([, label]) => label);
  const requireBoth = semester.requireBoth !== false;
  const isComplete = requireBoth ? scoreGap === 0 && submissionGap === 0 : scoreGap === 0 || submissionGap === 0;
  const focus = isComplete
    ? '保持本周训练节拍，继续记录新题'
    : pendingLabels.length
      ? `等待审核：${pendingLabels.join('、')}`
      : submissionGap > 0 && (requireBoth || scoreGap > 0)
        ? `完成第 ${submissionCount + 1} 次有效提交`
        : `补交${missingLabels[0] || '材料'}，再累积 ${scoreGap} 分`;
  const requirement = isComplete
    ? '本周目标已达成，可继续提交'
    : pendingLabels.length
      ? `审核中 · ${pendingLabels.join(' · ')}`
      : !requireBoth && scoreGap > 0 && submissionGap > 0
        ? `还需 ${submissionGap} 次或 ${scoreGap} 分`
        : submissionGap > 0
          ? `还需 ${submissionGap} 次有效提交`
        : missingLabels.length ? `可补交：${missingLabels.join(' · ')}` : `还差 ${scoreGap} 分`;
  const status = isComplete ? '本周已达标' : week.closed ? '本周已截止' : requireBoth ? scoreGap > 0 && submissionGap > 0 ? `还差 ${scoreGap} 分 · ${submissionGap} 次` : scoreGap > 0 ? `还差 ${scoreGap} 分` : submissionGap > 0 ? `还需 ${submissionGap} 次` : '等待审核' : `还需 ${submissionGap} 次或 ${scoreGap} 分`;
  const tone = isComplete ? 'is-done' : week.closed ? 'is-warning' : 'is-warning';
  renderPulseDays(dashboard);
  startDeadlineCountdown(week.remainingSeconds, week.closed);
  const stageScore = $('#stageScore');
  const stageScoreMax = $('.stage-title span:last-child');
  const stageCaption = $('#stageScoreCaption');
  const stageFocus = $('#stageFocus');
  const stageFocusMeta = $('#stageFocusMeta');
  if (stageScore) stageScore.textContent = String(score).padStart(2, '0');
  if (stageScoreMax) stageScoreMax.textContent = `/${minScore}`;
  if (stageCaption) stageCaption.textContent = isComplete ? '本周已达标' : !requireBoth && submissionGap === 0 ? '提交次数已达标' : `还差 ${scoreGap} 分达标`;
  if (stageFocus) stageFocus.textContent = focus;
  if (stageFocusMeta) stageFocusMeta.textContent = requirement;
  const stageWeek = $('#stageWeek');
  if (stageWeek) stageWeek.textContent = `WEEK ${String(week.number).padStart(2, '0')} / ${String(semester.totalWeeks || 0).padStart(2, '0')}`;
  const streak = Number(stats.streakWeeks || 0);
  if ($('#stageStreak')) $('#stageStreak').textContent = `${String(streak).padStart(2, '0')} 周`;

  if ($('#quickSubmissions')) $('#quickSubmissions').textContent = `${submissionCount} 次提交`;
  if ($('#quickPending')) $('#quickPending').textContent = '提交即计分';
  if ($('#quickRank')) $('#quickRank').textContent = stats.rank ? `训练排名 #${stats.rank}` : '排名 —';
  if ($('#rankValue')) $('#rankValue').innerHTML = stats.rank ? `#${stats.rank} <small>/ ${stats.memberCount || 0} 人</small>` : '— <small>/ — 人</small>';
  const rankDelta = stats.previousRank && stats.rank ? stats.previousRank - stats.rank : 0;
  if ($('#rankChange')) $('#rankChange').textContent = rankDelta ? `${rankDelta > 0 ? '↑' : '↓'} ${Math.abs(rankDelta)}` : '—';
  if ($('#rankChangeLabel')) $('#rankChangeLabel').textContent = rankDelta ? '较上周' : '暂无变化';
  if ($('#rankGap')) $('#rankGap').textContent = '本周排名';
  const featuredValue = $('.metric-card.featured .metric-value');
  const featuredFoot = $('.metric-card.featured .metric-foot span');
  const submissionValue = $('.metric-card:nth-child(2) .metric-value');
  const submissionFoot = $('.metric-card:nth-child(2) .metric-foot span');
  if (featuredValue) featuredValue.innerHTML = `${score} <small>/ ${minScore} 分</small>`;
  if (featuredFoot) featuredFoot.textContent = isComplete ? '本周已达标' : !requireBoth && submissionGap === 0 ? '提交次数已达标' : `还差 ${scoreGap} 分达标`;
  if (submissionValue) submissionValue.innerHTML = `${submissionCount} <small>/ ${minSubmissions} 次</small>`;
  if (submissionFoot) submissionFoot.textContent = submissionGap ? `再完成 ${submissionGap} 次即可` : '本周次数已达标';
  const progress = $('.metric-card.featured .progress-track span');
  if (progress) progress.style.width = `${minScore ? Math.min(100, Math.round(score / minScore * 100)) : 0}%`;
  const dots = $$('.metric-card:nth-child(2) .submission-dots i');
  dots.forEach((dot, index) => dot.classList.toggle('done', index < Math.min(submissionCount, dots.length)));
}

function applyRoleUi(role) {
  canManage = role === 'admin' || role === 'site_admin';
  document.body.classList.toggle('member-mode', !canManage);
  const adminNav = $('#adminNavItem');
  const adminView = $('#adminView');
  if (adminNav) adminNav.hidden = !canManage;
  if (adminView) adminView.hidden = !canManage;
  // The same content modal is used for history and review. Members may read
  // materials, but never see approval or visibility controls.
  const visibility = $('.visibility-setting');
  const reject = $('#rejectReview');
  const approve = $('#approveReview');
  if (visibility) visibility.hidden = !canManage;
  if (reject) reject.hidden = !canManage;
  if (approve) approve.hidden = !canManage;
}

function showToast(text) {
  $('#toastText').textContent = text;
  $('#toast').classList.add('show');
  window.setTimeout(() => $('#toast').classList.remove('show'), 2800);
}

function syncSegmented(group, selected = $('.segment.active', group)) {
  if (!group || !selected) return;
  let indicator = $('.segment-indicator', group);
  if (!indicator) {
    indicator = document.createElement('i');
    indicator.className = 'segment-indicator';
    indicator.setAttribute('aria-hidden', 'true');
    group.prepend(indicator);
  }
  const buttons = $$('.segment', group);
  buttons.forEach((button) => {
    const isSelected = button === selected;
    button.classList.toggle('active', isSelected);
    button.setAttribute('role', 'tab');
    button.setAttribute('aria-selected', String(isSelected));
    button.tabIndex = isSelected ? 0 : -1;
  });
  group.style.setProperty('--segment-x', `${selected.offsetLeft}px`);
  group.style.setProperty('--segment-width', `${selected.offsetWidth}px`);
}

function initSegmentedControls() {
  $$('.segmented').forEach((group) => {
    const selected = $('.segment.active', group) || $('.segment', group);
    syncSegmented(group, selected);
    $$('.segment', group).forEach((button, index) => {
      button.addEventListener('keydown', (event) => {
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        const items = $$('.segment', group);
        const current = items.indexOf(button);
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : (current + (event.key === 'ArrowRight' ? 1 : -1) + items.length) % items.length;
        items[next]?.focus();
        items[next]?.click();
      });
    });
  });
  window.addEventListener('resize', () => $$('.segmented').forEach((group) => syncSegmented(group)));
}

let feedbackTimer = null;
function playFeedback(type) {
  if (type !== 'submission-success') return;
  const layer = $('#feedbackLayer');
  const card = $('#submissionFeedback');
  if (!layer || !card) return;
  window.clearTimeout(feedbackTimer);
  layer.classList.remove('is-visible');
  card.classList.remove('is-playing');
  void card.offsetWidth;
  layer.classList.add('is-visible');
  card.classList.add('is-playing');
  layer.setAttribute('aria-hidden', 'false');
  feedbackTimer = window.setTimeout(() => {
    card.classList.remove('is-playing');
    layer.classList.remove('is-visible');
    layer.setAttribute('aria-hidden', 'true');
  }, 1700);
}

function resetSubmissionForm() {
  $('#proofImage').required = true;
  const form = $('#submissionForm');
  if (!form) return;
  const preview = $('.upload-preview', form);
  if (preview?.dataset.objectUrl) URL.revokeObjectURL(preview.dataset.objectUrl);
  preview?.remove();
  form.reset();
  const title = $('.upload-box strong');
  const hint = $('#proofHint');
  if (title) title.textContent = '点击上传截图';
  if (hint) hint.textContent = '支持 PNG、JPG、WebP，单张不超过 5MB';
  if (typeof clearBlogEditor === 'function') clearBlogEditor();
}
let currentSubmissionWeekId = null;
let makeupInFlight = false;
async function completeMakeup(date) {
  if (makeupInFlight) return null;
  makeupInFlight = true;
  const buttons = ['openSubmission', 'openSubmissionSecondary'].map(id => $('#'+id)).filter(Boolean);
  buttons.forEach(button => button.disabled = true);
  try {
    const alreadyOpen = pulseDays.find(day => day.date === date)?.makeupOpen === true;
    const result = await window.CurrencyModule.performMakeupCheckin(date, {alreadyOpen});
    if (result) await refreshAfterMutation();
    return result;
  } finally {
    makeupInFlight = false;
    if (selectedPulseDate) selectPulseDay(selectedPulseDate);
  }
}
async function openModal(forceToday = false) {
  const selected = forceToday === true ? pulseDays.find(day => day.date === pulseToday)
    : pulseDays.find(day => day.date === selectedPulseDate);
  const date = selected?.date || pulseToday;
  const historical = date < pulseToday;
  if (selected && (!selected.canSubmit || historical && (selected.submitted || selected.isMakeup))) return;
  let weekId = selected?.weekId || currentSubmissionWeekId;
  if (historical) {
    const permission = await completeMakeup(date);
    if (!permission) return;
    weekId = permission.week_id;
  }
  loadDailyChallenges(); editingSubmission = null; resubmitting = null;
  $('#modalTitle').textContent = historical ? '补交当日记录' : '提交今日记录'; resetSubmissionForm();
  $('#submissionForm').dataset.recordDate = date || '';
  $('#submissionForm').dataset.makeup = historical ? '1' : '';
  if (date) $('.form-note span').textContent = `记录日期：${date}`;
  $('#submissionForm').dataset.weekId = weekId || '';
  if (historical) $('.form-note span:last-child').textContent = '已开放补交 · 学期结束前有效';
  lockSubmissionScroll();
  $('#submissionModal').classList.add('open'); $('#submissionModal').setAttribute('aria-hidden','false'); $('#proofImage').focus({preventScroll:true});
}

let submissionScrollState = null;
function lockSubmissionScroll() {
  if (submissionScrollState) return;
  const properties = ['position', 'top', 'left', 'width', 'overflow'];
  submissionScrollState = {
    x: window.scrollX, y: window.scrollY,
    styles: properties.map(name => [name, document.body.style.getPropertyValue(name), document.body.style.getPropertyPriority(name)]),
  };
  // A fixed body also prevents background touch scrolling in mobile Safari.
  Object.assign(document.body.style, {
    position: 'fixed', top: `-${submissionScrollState.y}px`,
    left: `-${submissionScrollState.x}px`, width: '100%', overflow: 'hidden',
  });
}
function closeModal() {
  $('#submissionModal').classList.remove('open'); $('#submissionModal').setAttribute('aria-hidden','true');
  if (!submissionScrollState) return;
  const {x, y, styles} = submissionScrollState;
  submissionScrollState = null;
  styles.forEach(([name, value, priority]) => {
    if (value) document.body.style.setProperty(name, value, priority);
    else document.body.style.removeProperty(name);
  });
  const root = document.documentElement;
  const behavior = root.style.getPropertyValue('scroll-behavior');
  const priority = root.style.getPropertyPriority('scroll-behavior');
  root.style.setProperty('scroll-behavior', 'auto', 'important');
  window.scrollTo(x, y);
  if (behavior) root.style.setProperty('scroll-behavior', behavior, priority);
  else root.style.removeProperty('scroll-behavior');
}

$$('.nav-item[data-view]').forEach((button) => button.addEventListener('click', () => setView(button.dataset.view)));
wirePulseAtlas();
$$('[data-view-target]').forEach((button) => button.addEventListener('click', () => setView(button.dataset.viewTarget)));
['openSubmission','openSubmissionSecondary','emptyAction'].forEach((id) => { const button = $(`#${id}`); if (button) button.addEventListener('click', openModal); });
$('#closeSubmission').addEventListener('click', closeModal);
$('#submissionModal').addEventListener('click', (event) => { if (event.target.id === 'submissionModal') closeModal(); });
document.addEventListener('keydown', (event) => {
  if (event.key !== 'Escape') return;
  if (imageLightbox?.classList.contains('open')) closeImageLightbox();
  else closeModal();
});

const reviewData = {};
function fetchMineSubmissions({force = false} = {}) {
  if (mineSubmissionsInFlight && !force) return mineSubmissionsInFlight;
  const request = clubApi.request('/api/submissions?mine=1').then(async (response) => ({
    ok: response.ok,
    response,
    submissions: response.ok ? ((await response.json()).submissions || []) : [],
  }));
  const tracked = request.finally(() => {
    if (mineSubmissionsInFlight === tracked) mineSubmissionsInFlight = null;
  });
  mineSubmissionsInFlight = tracked;
  return tracked;
}

async function loadRecentActivity({force = false} = {}) {
  const list = $('#submissionList');
  if (!list) return;
  const requestVersion = ++activityRequestVersion;
  try {
    const result = await fetchMineSubmissions({force});
    if (requestVersion !== activityRequestVersion) return;
    if (!result.ok) { list.innerHTML = '<div class="queue-empty">最近提交加载失败，请刷新重试</div>'; return; }
    const submissions = result.submissions;
    if (!submissions.length) { list.innerHTML = '<div class="queue-empty">当前还没有提交记录</div>'; return; }
    list.innerHTML = submissions.flatMap(submission => submission.parts.map(part => ({submission, part}))).slice(0, 2).map(({submission, part}) => {
      const status = part.status === 'approved' ? 'approved' : part.status === 'rejected' ? 'rejected' : 'pending';
      const label = part.kind === 'proof' ? '通过截图' : part.kind === 'logic' ? '写题逻辑' : 'Blog';
      const statusText = status === 'approved' ? '已计分' : status === 'rejected' ? '已退回' : '等待处理';
      return `<div class="submission-row"><div class="status-marker ${status}">${status === 'approved' ? '✓' : status === 'rejected' ? '!' : '◷'}</div><div class="submission-info"><strong>${label} · 第 ${submission.week} 周</strong><span>${new Date(submission.submitted_at).toLocaleString('zh-CN')} · ${statusText}</span></div><span class="score">+${part.points || 0} <small>分</small></span><span class="status-tag ${status}">${status === 'approved' ? '已通过' : status === 'rejected' ? '已退回' : '待审核'}</span></div>`;
    }).join('');
  } catch (error) { if (requestVersion === activityRequestVersion) list.innerHTML = '<div class="queue-empty">最近提交加载失败，请检查网络连接</div>'; }
}
function groupMySubmissions(submissions) {
  const sorted = [...submissions].sort((a, b) => b.record_date.localeCompare(a.record_date)
    || Date.parse(b.submitted_at) - Date.parse(a.submitted_at) || b.id - a.id);
  const groups = new Map();
  for (const item of sorted) {
    if (!groups.has(item.record_date)) groups.set(item.record_date, []);
    groups.get(item.record_date).push(item);
  }
  return [...groups];
}

async function loadMySubmissions({force = false} = {}) {
  const page = $('#submissionsView');
  if (!page) return;
  const requestVersion = ++submissionsRequestVersion;
  try {
    const result = await fetchMineSubmissions({force});
    if (requestVersion !== submissionsRequestVersion) return;
    if (!result.ok) { const empty = $('.empty-state', page); if (empty) { empty.hidden = false; empty.innerHTML = '<div class="empty-icon">!</div><h2>提交记录加载失败</h2><p>请刷新页面后重试。</p>'; } return; }
    const submissions = result.submissions;
    ownRecords.clear(); submissions.forEach(item => ownRecords.set(item.id, item));
    const empty = $('.empty-state', page);
    page.querySelector('.my-submissions-live')?.remove();
    if (!submissions.length) { if (empty) { empty.hidden = false; empty.innerHTML = '<div class="empty-icon">□</div><h2>这里会留下你的训练轨迹</h2><p>当前还没有提交记录。</p><button class="secondary-button" id="emptyAction" type="button">继续提交</button>'; $('#emptyAction')?.addEventListener('click', openModal); } return; }
    const list = document.createElement('div');
    list.className = 'panel my-submissions-live';
    const today = new Intl.DateTimeFormat('en-CA', {timeZone:'Asia/Shanghai', year:'numeric', month:'2-digit', day:'2-digit'}).format(new Date());
    const dateFormat = new Intl.DateTimeFormat('zh-CN', {timeZone:'Asia/Shanghai', year:'numeric', month:'long', day:'numeric', weekday:'short'});
    list.innerHTML = `<div class="panel-heading"><div><h2>历史提交记录</h2></div><span class="muted">共 ${submissions.length} 条</span></div>` + groupMySubmissions(submissions).map(([day, items]) => {
      const label = `${day === today ? '今天 · ' : ''}${dateFormat.format(new Date(`${day}T12:00:00+08:00`))}`;
      return `<section class="my-submission-day"><h3 class="my-submission-date">${escapeHtml(label)}<small>${items.length} 条</small></h3>` + items.map((item) => {
      const key = `mine-${item.id}`;
      const proof = item.parts.find((part) => part.kind === 'proof');
      const logic = item.parts.find((part) => part.kind === 'logic');
      const blog = item.parts.find((part) => part.kind === 'blog');
      const reviewStatus = item.parts.some((part) => part.status === 'pending') ? 'pending' : item.parts.some((part) => part.status === 'approved') ? 'approved' : 'rejected';
      reviewData[key] = {name:item.member_name, initial:item.member_name.slice(0,1), time:new Date(item.submitted_at).toLocaleString('zh-CN'), logic:logic?.text || '未提交写题逻辑。', visibility:item.visibility || 'team', status:reviewStatus, submissionId:item.id, problemUrl:item.problem_url || '', upload:proof?.upload, fileName:'通过截图', blog:blog?.text || ''};
      const approved = item.parts.filter((part) => part.status === 'approved').reduce((sum, part) => sum + (part.points || 0), 0);
      return `<div class="live-submission-row"><div class="submission-thumb">${proof?.upload ? `<img src="${proof.upload}" alt="通过截图" />` : '<span>▧</span>'}</div><div class="live-submission-info"><strong>${escapeHtml(item.problem_title || '提交记录')}</strong><small>第${item.week}周 · 归属 ${escapeHtml(item.record_date || '')} · ${new Date(item.submitted_at).toLocaleString('zh-CN')}${item.rejection_note ? ' · 退回原因：' + escapeHtml(item.rejection_note) : ''}</small></div><span class="score">+${approved} 分</span><button class="review-view" type="button" data-review="${key}">查看内容</button>${item.can_resubmit ? `<button class="secondary-button" data-resubmit="${item.id}">修改重交</button>` : ""}</div>`;
      }).join('') + '</section>';
    }).join('');
    if (empty) empty.hidden = true;
    page.appendChild(list);
    $$('.review-view', list).forEach((button) => button.addEventListener('click', () => openReview(button.dataset.review)));
  } catch (error) { if (requestVersion === submissionsRequestVersion) { const empty = $('.empty-state', page); if (empty) { empty.hidden = false; empty.innerHTML = '<div class="empty-icon">!</div><h2>提交记录加载失败</h2><p>请检查网络连接后重试。</p>'; } } }
}
const reviewModal = $('#reviewModal');
let activeReviewKey = null;
let activeSubmissionId = null;
let reviewReturnsToHistory = false;
function openReview(key, returnToHistory = false) {
  const data = reviewData[key];
  if (!data) return;
  reviewReturnsToHistory = returnToHistory;
  const closeControl = $('#closeReview');
  closeControl.innerHTML = returnToHistory ? '<svg class="ui-chevron" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="m15 5-7 7 7 7"/></svg>' : '×';
  closeControl.setAttribute('aria-label', returnToHistory ? '返回历史提交' : '关闭');
  closeControl.title = returnToHistory ? '返回历史提交' : '关闭';
  activeReviewKey = key;
  activeSubmissionId = data.submissionId || null;
  const ownRecord = key.startsWith('mine-') ? ownRecords.get(Number(data.submissionId)) : null;
  $('#ownReviewActions').hidden = !ownRecord;
  $('#editOwnSubmission').disabled = !ownRecord?.can_edit;
  $('#deleteOwnSubmission').disabled = !ownRecord?.can_delete;
  $('#ownReviewHint').textContent = ownRecord && !ownRecord.can_edit ? '该周已截止或学期已归档，无法编辑' : '';

  $('#reviewMember').textContent = data.name;
  $('#reviewAvatar').textContent = data.initial;
  $('#reviewTime').textContent = data.time;
  const originalProblem = $('#reviewOriginalProblem');
  originalProblem.hidden = true;
  originalProblem.removeAttribute('href');
  try {
    const url = new URL(data.problemUrl);
    if (['https:', 'http:'].includes(url.protocol)) {
      originalProblem.href = url.href;
      originalProblem.hidden = false;
    }
  } catch { /* Legacy records without a problem URL have no outbound action. */ }
  const reviewStatus = $('.review-author .status-tag');
  if (reviewStatus) {
    const approved = data.status === 'approved';
    reviewStatus.textContent = approved ? '已通过' : data.status === 'rejected' ? '已退回' : '待审核';
    reviewStatus.className = `status-tag ${approved ? 'approved' : data.status === 'rejected' ? 'rejected' : 'pending'}`;
  }
  $('#reviewLogic').textContent = data.logic;
  const blog = typeof data.blog === 'string' ? data.blog.trim() : '';
  const hasBlog = Boolean(blog);
  $('.review-modal').classList.toggle('has-blog', hasBlog);
  $('#reviewBlogStatus').textContent = hasBlog ? '已提交' : '未提交';
  $('#reviewBlogStatus').className = hasBlog ? 'score-chip' : 'empty-chip';
  const blogContainer = $('#reviewBlog');
  blogContainer.classList.toggle('blog-rendered', hasBlog);
  if (hasBlog) renderSubmissionBlog(blogContainer, blog);
  else blogContainer.textContent = '未提交 Blog';
  const image = $('#reviewImage');
  const fallback = $('#reviewImageFallback');
  image.onerror = () => { image.classList.remove('visible'); fallback.classList.remove('hidden'); $('#reviewFileMeta').textContent = '图片加载失败，请检查媒体文件服务'; };
  if (data.upload) { image.src = `${data.upload}${data.upload.includes('?') ? '&' : '?'}v=${Date.now()}`; image.classList.add('visible'); fallback.classList.add('hidden'); } else { image.removeAttribute('src'); image.classList.remove('visible'); fallback.classList.remove('hidden'); }
  $('#reviewFileName').textContent = data.fileName || (data.upload ? '通过截图' : '演示占位图片');
  $('#reviewFileMeta').textContent = data.upload ? '已上传，可点击放大查看' : '当前记录没有可预览图片';
  reviewModal.classList.add('open');
  reviewModal.setAttribute('aria-hidden','false');
}
function closeReview() { reviewModal.classList.remove('open'); reviewModal.setAttribute('aria-hidden','true'); }
$$('.review-view').forEach((button) => button.addEventListener('click', () => openReview(button.dataset.review)));
function wireShowcaseProofs(root=document) {
  $$('.proof-image-button', root).forEach((button) => {
    if (button.dataset.proofWired) return;
    button.dataset.proofWired = 'true';
    button.addEventListener('click', () => openReview(button.dataset.review));
  });
}
$('#closeReview').addEventListener('click', () => {
  const restoreHistory = reviewReturnsToHistory;
  closeReview();
  reviewReturnsToHistory = false;
  if (restoreHistory) {
    historyModal.classList.add('open'); historyModal.setAttribute('aria-hidden', 'false');
    const origin = [...historyModal.querySelectorAll('.history-view')].find(button => button.dataset.review === activeReviewKey);
    (origin || $('#closeHistory')).focus();
  }
});
reviewModal.addEventListener('click', (event) => { if (event.target.id === 'reviewModal') closeReview(); });
const imageLightbox = $('#imageLightbox');
function closeImageLightbox() { imageLightbox.classList.remove('open'); imageLightbox.setAttribute('aria-hidden','true'); $('#lightboxImage').removeAttribute('src'); }
$('#zoomReviewImage').addEventListener('click', () => {
  const source = $('#reviewImage');
  if (!source.classList.contains('visible') || !source.src) { showToast('当前记录没有可预览图片'); return; }
  $('#lightboxImage').src = source.src;
  $('#lightboxImage').alt = source.alt || '放大后的通过截图';
  imageLightbox.classList.add('open');
  imageLightbox.setAttribute('aria-hidden','false');
});
$('#closeImageLightbox').addEventListener('click', closeImageLightbox);
imageLightbox.addEventListener('click', (event) => { if (event.target === imageLightbox) closeImageLightbox(); });
function wireRankingControls(root=document) {
  $$('[data-ranking]', root).forEach(button => button.addEventListener('click', async () => {
    const panel = button.closest('.panel');
    syncSegmented(button.closest('.segmented'), button);
    const target = panel?.classList.contains('full-leaderboard') ? '#leaderboardListFull' : '#leaderboardList';
    const selected = rankingSelection(target);
    renderLeaderboard(selected.scope,target);
    await loadLeaderboard(selected.scope,selected.platform);
  }));
  $$('[data-rating-platform]', root).forEach(select => select.addEventListener('change',async () => {
    const target = select.closest('.full-leaderboard') ? '#leaderboardListFull' : '#leaderboardList';
    renderLeaderboard('rating',target);
    await loadLeaderboard('rating',select.value);
  }));
}

wireRankingControls();
initSegmentedControls();

function toggleTeamMenu(open) {
  const menu = $('#teamMenu');
  menu.classList.toggle('open', open);
  menu.inert = !open;
  $('#teamButton').setAttribute('aria-expanded', String(open));
}
$('#teamButton').addEventListener('click', () => toggleTeamMenu(!$('#teamMenu').classList.contains('open')));
$('#teamButton').addEventListener('keydown', event => {
  if (event.key !== 'ArrowDown') return;
  event.preventDefault(); toggleTeamMenu(true); $('#teamMenu button')?.focus();
});
$('#teamMenu').addEventListener('keydown', event => {
  if (event.key === 'Escape') {event.preventDefault();toggleTeamMenu(false);$('#teamButton').focus();return;}
  if (event.key === 'Tab') {toggleTeamMenu(false);return;}
  if (!['ArrowDown','ArrowUp','Home','End'].includes(event.key)) return;
  event.preventDefault();
  const buttons = $$('#teamMenu button');
  const index = buttons.indexOf(document.activeElement);
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length-1 : (index + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length;
  buttons[next]?.focus();
});
// Team choices are populated from /api/me. Never switch to placeholder teams.
document.addEventListener('click', (event) => { if (!event.target.closest('.team-switcher')) toggleTeamMenu(false); });

$('#submissionForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.target;
  const submitButton = form.querySelector('button[type="submit"]');
  if (submitButton?.disabled) return;
  if (submitButton) { submitButton.disabled = true; submitButton.setAttribute('aria-busy', 'true'); submitButton.dataset.label = submitButton.textContent; submitButton.textContent = '正在提交…'; }
  if (demoMode) {
    closeModal();
    resetSubmissionForm();
    playFeedback('submission-success');
    showToast('演示提交成功，已计分并展示');
    if (submitButton) { submitButton.disabled = false; submitButton.removeAttribute('aria-busy'); submitButton.textContent = submitButton.dataset.label || '提交记录'; }
    return;
  }
  const formData = new FormData(form);
  formData.set('week_id', form.dataset.weekId || '');
  formData.set('record_date', form.dataset.recordDate || '');
  if ($('#proofImage').files[0]) formData.set('proof', $('#proofImage').files[0]);
  else formData.delete('proof');
  if (editingSubmission) formData.set('version', ownRecords.get(editingSubmission)?.version || '');
  formData.set('logic', $('#logicText').value);
  const blogContent = typeof getBlogEditorContent === 'function' ? getBlogEditorContent() : '';
  formData.set('blog', blogContent);
  try {
    const response = await clubApi.request(editingSubmission ? `/api/submissions/${editingSubmission}/edit` : resubmitting ? `/api/submissions/${resubmitting}/resubmit` : '/api/submissions', {method:'POST', body:formData});
    if (response.status === 401 || response.status === 403) throw new Error('请先登录后再提交');
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.error || '提交失败，请稍后重试');
    }
  } catch (error) { showToast(error.message || '提交失败，请稍后重试'); if (submitButton) { submitButton.disabled = false; submitButton.removeAttribute('aria-busy'); submitButton.textContent = submitButton.dataset.label || '提交记录'; } return; }
  closeModal();
  resetSubmissionForm();
  playFeedback('submission-success');
  showToast('提交成功，已计分并展示');
  refreshAfterMutation({refreshAdmin: canManage});
  if (submitButton) { submitButton.disabled = false; submitButton.removeAttribute('aria-busy'); submitButton.textContent = submitButton.dataset.label || '提交记录'; }
});
$('#proofImage').addEventListener('change', (event) => {
  const file = event.target.files?.[0];
  const box = $('.upload-box');
  if (!file || !box) return;
  let preview = box.querySelector('.upload-preview');
  if (!preview) { preview = document.createElement('img'); preview.className = 'upload-preview'; box.prepend(preview); }
  const objectUrl = URL.createObjectURL(file);
  preview.src = objectUrl;
  preview.dataset.objectUrl = objectUrl;
  const title = box.querySelector('strong'); if (title) title.textContent = file.name;
  const hint = box.querySelector('small'); if (hint) hint.textContent = `${(file.size / 1024 / 1024).toFixed(2)} MB · 已选择，可提交`;
});

function clearStaticPreview() {
  const loading = '<div class="queue-empty">正在加载真实数据…</div>';
  Object.keys(rankingData).forEach(key => delete rankingData[key]);
  ['#leaderboardList', '#leaderboardListFull'].forEach((selector) => {
    const element = $(selector);
    if (element) { element.innerHTML = loading; element.setAttribute('aria-live', 'polite'); }
  });
  ['#submissionList', '#showcaseGrid', '#membersGrid', '#reviewList', '#historyList', '#submissionsView .empty-state', '#reportsPlaceholder'].forEach((selector) => {
    const element = $(selector);
    if (element) { element.innerHTML = loading; element.setAttribute('aria-live', 'polite'); }
  });
  const rank = $('.your-rank strong');
  if (rank) rank.textContent = '—';
  const rankChange = $('.your-rank .rank-up');
  if (rankChange) rankChange.textContent = '加载中…';
  const leaderboardLabel = $('#leaderboardWeekLabel');
  const showcaseLabel = $('.showcase-toolbar .filter-chip');
  if (leaderboardLabel) leaderboardLabel.textContent = '加载中…';
  if (showcaseLabel) showcaseLabel.textContent = '加载中…';
  const featuredDelta = $('.metric-card.featured .metric-foot span:nth-child(2)');
  if (featuredDelta) featuredDelta.textContent = '—';
  const demoCallout = $('.mini-callout');
  if (demoCallout) demoCallout.hidden = true;
  const stageScore = $('#stageScore');
  const stageScoreMax = $('.stage-title span:last-child');
  const stageCaption = $('#stageScoreCaption');
  const stageFocus = $('#stageFocus');
  const stageFocusMeta = $('#stageFocusMeta');
  if (stageScore) stageScore.textContent = '—';
  if (stageScoreMax) stageScoreMax.textContent = '/—';
  if (stageCaption) stageCaption.textContent = '等待真实数据';
  if (stageFocus) stageFocus.textContent = '等待真实数据';
  if (stageFocusMeta) stageFocusMeta.textContent = '当前周数据加载中';
  if ($('#pulseFocus')) $('#pulseFocus').textContent = '等待真实数据';
  if ($('#pulseStatus')) $('#pulseStatus').textContent = '加载中…';
  $$('.metric-card .metric-value').forEach((element) => { element.innerHTML = '—'; });
  $$('.metric-card .metric-foot span:first-child').forEach((element) => { element.textContent = '等待真实数据'; });
  const welcomeKicker = $('.welcome-row .kicker');
  const welcomeNote = $('.welcome-row .muted');
  if (welcomeKicker) welcomeKicker.textContent = '当前学期 · 当前周次';
  if (welcomeNote) welcomeNote.textContent = '正在加载本周截止时间…';
  const search = $('#memberSearch');
  if (search) { search.name = 'member_search'; search.autocomplete = 'off'; search.placeholder = '搜索成员姓名…'; search.setAttribute('aria-label', '搜索成员姓名'); }
  $$('.inline-count').forEach((element) => { element.textContent = '—'; });
  $$('.count-badge').forEach((element) => { element.textContent = '—'; });
  $$('.admin-stat strong').forEach((element) => { element.textContent = '—'; });
  if ($('#lastWeekIncompleteTitle')) $('#lastWeekIncompleteTitle').textContent = '上周未达标成员';
  if ($('#lastWeekIncompleteList')) $('#lastWeekIncompleteList').innerHTML = '<div class="queue-empty">等待真实数据…</div>';
  const formNote = $('.form-note');
  if (formNote) {
    const weekLabel = formNote.querySelector('span:first-child');
    const deadlineLabel = formNote.querySelector('span:last-child');
    if (weekLabel) weekLabel.textContent = '当前周次加载中…';
    if (deadlineLabel) deadlineLabel.textContent = '截止时间加载中…';
  }
  ['#quickSubmissions', '#quickPending', '#quickRank', '#stageWeek', '#stageStreak', '#rankValue', '#rankChange', '#rankGap', '#streakValue', '#yourRankValue', '#yourRankChange'].forEach((selector) => { const element = $(selector); if (element) element.textContent = '—'; });
  if ($('#teamName')) $('#teamName').textContent = '正在加载…';
  const profile = $('.profile-chip');
  if (profile) { profile.querySelector('strong').textContent = '正在加载…'; profile.querySelector('small').textContent = '正在验证登录状态'; }
}

async function loadDashboardSummary({forceMine = false} = {}) {
  const dashboardResponse = await clubApi.request('/api/dashboard');
  if (!dashboardResponse.ok) return null;
  const dashboard = await dashboardResponse.json();
  const scoreValue = $('.metric-card.featured .metric-value');
  const scoreFoot = $('.metric-card.featured .metric-foot span');
  const submissionValue = $('.metric-card:nth-child(2) .metric-value');
  if (scoreValue && dashboard.semester) scoreValue.innerHTML = `${dashboard.score} <small>/ ${dashboard.semester.minScore} 分</small>`;
  if (scoreFoot && dashboard.semester) scoreFoot.textContent = dashboard.score >= dashboard.semester.minScore ? '本周已达标' : `还差 ${Math.max(0, dashboard.semester.minScore - dashboard.score)} 分达标`;
  if (submissionValue && dashboard.semester) submissionValue.innerHTML = `${dashboard.submissions} <small>/ ${dashboard.semester.minSubmissions} 次</small>`;
  currentSubmissionWeekId = dashboard.current_week?.id || null;
  if (dashboard.current_week) {
    const select = $('#historyWeek');
    if (select) select.innerHTML = [dashboard.current_week.number, dashboard.current_week.number - 1, dashboard.current_week.number - 2].filter((number) => number > 0).map((number) => `<option value="${number}">第 ${String(number).padStart(2, '0')} 周</option>`).join('');
    const note = $('.form-note span');
    if (note) note.textContent = `第 ${String(dashboard.current_week.number).padStart(2, '0')} 周`;
    const kicker = $('.welcome-row .kicker');
    if (kicker) kicker.textContent = `${dashboard.semester?.name || '当前学期'} · 第 ${String(dashboard.current_week.number).padStart(2, '0')} 周`;
    const label = `第 ${String(dashboard.current_week.number).padStart(2, '0')} 周 · ${dashboard.semester?.name || '当前学期'}`;
    const leaderboardLabel = $('#leaderboardWeekLabel');
    if (leaderboardLabel) leaderboardLabel.textContent = '当前团队 · 最新数据';
    const showcaseLabel = $('.showcase-toolbar .filter-chip');
    if (showcaseLabel) showcaseLabel.textContent = `第 ${String(dashboard.current_week.number).padStart(2, '0')} 周⌄`;
  }
  const mineResult = await fetchMineSubmissions({force: forceMine});
  if (mineResult.ok) applyLiveDashboardState(dashboard, mineResult.submissions);
  return dashboard;
}

async function loadLeaderboard(scope = 'checkin', platform='codeforces') {
  const key = rankingKey(scope,platform);
  if (leaderboardInFlight.has(key)) return leaderboardInFlight.get(key);
  const request = (async () => {
    try {
      const response = await clubApi.request(`/api/leaderboard?scope=${encodeURIComponent(scope)}&platform=${encodeURIComponent(platform)}`);
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || '榜单加载失败');
      rankingData[key] = payload.rows || [];
      for (const target of ['#leaderboardList','#leaderboardListFull']) {
        const selected = rankingSelection(target);
        if (rankingKey(selected.scope,selected.platform) === key) renderLeaderboard(scope,target);
      }
      return true;
    } catch (error) {
      for (const target of ['#leaderboardList','#leaderboardListFull']) {
        const selected = rankingSelection(target);
        if (rankingKey(selected.scope,selected.platform) === key && !rankingData[key]) $(target).innerHTML = `<div class="queue-empty" role="alert">${escapeHtml(error.message)}</div>`;
      }
      return false;
    }
  })();
  leaderboardInFlight.set(key,request);
  request.finally(() => {if (leaderboardInFlight.get(key) === request) leaderboardInFlight.delete(key);});
  return request;
}

async function refreshAfterMutation({refreshAdmin = false} = {}) {
  const tasks = [
    window.CurrencyModule?.init(),
    loadRecentActivity({force: true}),
    loadDashboardSummary(),
    ...['#leaderboardList','#leaderboardListFull'].map(target => {const selected=rankingSelection(target);return loadLeaderboard(selected.scope,selected.platform);}),
  ];
  if (currentView === 'submissions') tasks.push(loadMySubmissions());
  if (refreshAdmin && currentView === 'admin') tasks.push(loadAdminQueue());
  await Promise.allSettled(tasks);
  renderLeaderboard();
  renderLeaderboard('checkin','#leaderboardListFull');
}

window.addEventListener('personal-profile-saved', () => {
  document.querySelectorAll('.synced-member-avatar').forEach(holder => {
    holder.querySelector('img')?.remove();
    const image = document.createElement('img');
    image.alt = ''; image.onerror = () => image.remove();
    image.src = `/api/members/${holder.dataset.avatarMember}/avatar?v=${Date.now()}`;
    holder.append(image);
  });
  refreshAfterMutation();
  if (currentView === 'members') loadMembersLive();
});

async function loadLiveData() {
  try {
    const meResponse = await clubApi.request('/api/me');
    if (meResponse.status === 401) { window.location.href = '/auth.html'; return; }
    if (!meResponse.ok) { showToast('账户信息加载失败，请刷新重试'); return; }
    if (!(meResponse.headers.get('content-type') || '').includes('application/json')) {
      if (meResponse.url.includes('/auth.html')) window.location.href = '/auth.html';
      return;
    }
    const me = await meResponse.json();
    window.PersonalProfile?.init(me);
    await window.CurrencyModule?.init();
    initWorkbench(me);
    applyRoleUi(me.site_admin ? 'site_admin' : me.is_team_manager ? 'admin' : me.role);
    if (!me.team && !me.site_admin) { window.location.href = '/team-select.html'; return; }
    document.body.classList.toggle('site-admin-mode', me.site_admin && !me.can_submit);
    if (!me.can_submit) ['openSubmission','openSubmissionSecondary','emptyAction','pulseJump'].forEach(id => { if ($('#'+id)) $('#'+id).hidden=true; });

    if (me.team?.name) { $('#teamName').textContent = me.team.name; const subtitle = $('.team-button-copy small'); if (subtitle) subtitle.textContent = me.team.code || '当前团队'; }
    if (Array.isArray(me.teams)) {
      const menu = $('#teamMenu');
      menu.innerHTML = '<div class="team-menu-options" role="group"></div>';
      const options = $('.team-menu-options', menu);
      me.teams.forEach(team => {
        const button = document.createElement('button');
        button.type = 'button'; button.dataset.teamId = team.team_id;
        button.setAttribute('role', 'menuitemradio');
        button.setAttribute('aria-checked', String(String(team.team_id) === String(me.team?.id)));
        button.innerHTML = `<span class="team-avatar small">${escapeHtml((team.team__name || '').slice(0,1))}</span><span class="team-menu-name">${escapeHtml(team.team__name)}</span>`;
        button.addEventListener('click', async () => {
          if (button.disabled) return;
          button.disabled = true;
          try {
            const response = await clubApi.request('/api/team/select', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({team_id:team.team_id})});
            if (response.ok) location.reload(); else showToast('无权进入该团队');
          } catch(error) {showToast('团队切换失败，请重试');}
          finally {button.disabled=false;}
        });
        options.append(button);
      });
      const join = document.createElement('button');
      join.type = 'button'; join.className = 'team-menu-join'; join.setAttribute('role','menuitem');
      join.innerHTML = '<svg class="ui-chevron" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg><span>加入团队</span>';
      join.addEventListener('click', () => {toggleTeamMenu(false);window.openJoinTeamDialog();});
      menu.append(join);
    }
    const profile = $('.profile-chip');
    if (profile) { const avatar = profile.querySelector('.profile-avatar'); const name = profile.querySelector('strong'); const role = profile.querySelector('small'); if (avatar) avatar.textContent = (me.name || '').slice(0, 1); if (name) name.textContent = me.name || '当前账号'; if (role) role.textContent = me.site_admin ? '系统管理员' : me.is_team_manager ? '团队管理员' : '普通用户'; }
    window.PersonalProfile?.updateHeader(me);
    if (!me.team) {
      $('#teamName').textContent = '尚未创建团队';
      $('#dashboardView').innerHTML = '<div class="page-heading"><h1>欢迎回来，系统管理员</h1></div><div class="panel empty-state"><h2>从创建第一个团队开始</h2><p>点击左下角管理工作台，配置团队、成员和题目解析。</p><button class="primary-button" id="openEmptyWorkbench">打开管理工作台</button></div>';
      $('#openEmptyWorkbench').onclick = () => setView('admin');
      const requestedView = new URLSearchParams(location.search).get('view');
      if (pageTitles[requestedView]) setView(requestedView);
      return;
    }
    await Promise.allSettled([loadRecentActivity(), loadDashboardSummary(), loadLeaderboard('checkin')]);
    renderLeaderboard();
    const requestedView = new URLSearchParams(location.search).get('view');
    if (pageTitles[requestedView]) setView(requestedView);
  } catch (error) { showToast(error.message || '页面数据加载失败，请刷新重试'); }
}
async function loadMembersLive() {
  const grid = $('#membersGrid');
  if (!grid) return;
  const requestVersion = ++membersRequestVersion;
  // Never leave the built-in preview members visible while the real team
  // roster is loading. Otherwise the demo cards can appear to overwrite data.
  grid.innerHTML = '<div class="queue-empty">正在加载团队成员…</div>';
  try {
    const response = await clubApi.request('/api/members');
    if (requestVersion !== membersRequestVersion) return;
    if (!response.ok) {
      grid.innerHTML = '<div class="queue-empty">成员列表加载失败，请刷新重试</div>';
      return;
    }
    const payload = await response.json();
    if (requestVersion !== membersRequestVersion) return;
    const members = payload.members || [];
    if (!members.length) {
      grid.innerHTML = '<div class="queue-empty">当前团队暂无成员数据</div>';
      return;
    }
grid.innerHTML = members.map((member) => `<article class="member-card" data-member="${escapeHtml(member.name)}"><div class="member-card-head">${memberAvatar(member.id,member.name,'member-avatar dark')}<div><strong>${escapeHtml(member.name)}</strong><small>${member.is_system_admin ? '系统管理员' : member.role === 'admin' ? '团队管理员' : '普通用户'}</small></div><span class="member-status">活跃</span></div><div class="member-card-stats"><div><span>本周提交</span><strong>${member.submissions} <small>次</small></strong></div><div><span>本周积分</span><strong>${member.score}</strong></div><div><span>本周 AC 题数</span><strong>${member.ac_problems ?? 0} <small>题</small></strong></div></div><div class="member-card-actions">${member.can_kick ? `<button class="member-action-button danger" type="button" data-member-kick="${member.id}" data-team-id="${member.team_id}" data-name="${escapeHtml(member.name)}" data-team-name="${escapeHtml(payload.team_name)}">踢出用户</button>` : ''}${member.can_manage_role ? `<button class="member-action-button" type="button" data-member-role="${member.role === 'admin' ? 'member' : 'admin'}" data-team-id="${member.team_id}" data-account="${escapeHtml(member.account)}">${member.role === 'admin' ? '取消团队管理' : '设置团队管理'}</button>` : ''}<button class="member-history-button" type="button" data-member-history="${member.id}">查看历史提交 <span>→</span></button></div></article>`).join('');
    members.forEach((member,index) => {
      if (!Object.hasOwn(member,'currency_balance')) return;
      const button=document.createElement('button'); button.type='button'; button.className='member-currency-button';
      button.textContent=`${member.currency_balance} RBC · 调整`;
      button.setAttribute('aria-label',`调整${member.name}的 RBC 余额`);
      grid.children[index].querySelector('.member-card-head').append(button);
      button.onclick=()=>window.CurrencyAdminModule.showBalanceAdjustment(member);
    });
    $$('.member-history-button', grid).forEach((button) => button.addEventListener('click', () => openMemberHistory(button.dataset.memberHistory)));
  } catch (error) {
    grid.innerHTML = '<div class="queue-empty">成员列表加载失败，请检查网络连接</div>';
  }
}
clearStaticPreview(); loadLiveData();
const historyModal = $('#memberHistoryModal');
let activeHistoryMemberId = null;
let historyFromMemberList = false;
function updateHistorySelect(select, options, value) {
  const selected = options.some(option => option.value === String(value)) ? String(value) : options[0]?.value || '';
  if (select.tomselect) {
    select.tomselect.clear(true);
    select.tomselect.clearOptions();
    select.tomselect.addOptions(options);
    select.tomselect.setValue(selected, true);
    select.tomselect.refreshOptions(false);
  } else {
    select.innerHTML = options.map(option => `<option value="${escapeHtml(option.value)}">${escapeHtml(option.text)}</option>`).join('');
    select.value = selected;
    if (window.TomSelect) new TomSelect(select, {
      create:false, maxItems:1, controlInput:null, searchField:[],
      onInitialize() {
        this.wrapper.classList.add('history-select', select.id === 'historySemester' ? 'history-semester-select' : 'history-week-select');
        this.control.setAttribute('aria-label', select.id === 'historySemester' ? '选择学期' : '选择周次');
      }
    });
  }
}
function openMemberHistory(key) {
  historyFromMemberList = currentView === 'members';
  if (/^\d+$/.test(String(key))) { activeHistoryMemberId = Number(key); openLiveMemberHistory(Number(key)); return; }
  showToast('请从真实成员列表打开历史提交');
}
async function openLiveMemberHistory(memberId) {
  const requestVersion = ++historyRequestVersion;
  try {
    let semesterSelect = $('#historySemester');
    if (!semesterSelect) {
      semesterSelect = document.createElement('select'); semesterSelect.id = 'historySemester'; semesterSelect.setAttribute('aria-label', '选择学期');
      $('#historyWeek').before(semesterSelect);
      semesterSelect.addEventListener('change', () => { semesterSelect.dataset.weeksFor = ''; if (activeHistoryMemberId) openLiveMemberHistory(activeHistoryMemberId); });
    }
    const semesterResponse = await clubApi.request('/api/semesters');
    if (requestVersion !== historyRequestVersion) return;
    if (!semesterResponse.ok) throw new Error('学期加载失败');
    const semesterList = (await semesterResponse.json()).semesters || [];
    if (requestVersion !== historyRequestVersion) return;
    const selected = semesterSelect.value;
    updateHistorySelect(semesterSelect, semesterList.map(item => ({value:String(item.id),text:`${item.name}${item.archived ? '（已归档）' : ''}`})), selected);
    const semester = semesterList.find(item => String(item.id) === semesterSelect.value);
    if (semester && semesterSelect.dataset.weeksFor !== String(semester.id)) {
      const previousWeek = $('#historyWeek').value;
      updateHistorySelect($('#historyWeek'), semester.weeks.map(number => ({value:String(number),text:`第 ${number} 周`})), previousWeek);
      semesterSelect.dataset.weeksFor = String(semester.id);
    }
    const week = $('#historyWeek').value;
    const response = await clubApi.request(`/api/members/${memberId}/history?week=${week}${semester ? `&semester=${semester.id}` : ''}`);
    if (requestVersion !== historyRequestVersion) return;
    if (!response.ok) { showToast('当前权限无法查看该成员材料'); return; }
    const payload = await response.json();
    if (requestVersion !== historyRequestVersion) return;
    $('#historyMember').textContent = payload.member.name;
    $('#historyAvatar').textContent = payload.member.name.slice(0,1);
    const submissions = payload.submissions || [];
    $('#historyList').innerHTML = submissions.length ? submissions.map((item) => {
      const key = `history-${item.id}`;
      const proof = item.parts.find((part) => part.kind === 'proof');
      const logic = item.parts.find((part) => part.kind === 'logic');
      const blog = item.parts.find((part) => part.kind === 'blog');
      const reviewStatus = item.parts.some((part) => part.status === 'pending') ? 'pending' : item.parts.some((part) => part.status === 'approved') ? 'approved' : 'rejected';
      reviewData[key] = {name:item.member_name, initial:item.member_name.slice(0,1), time:new Date(item.submitted_at).toLocaleString('zh-CN'), logic:logic?.text || '未提交写题逻辑。', visibility:item.visibility || 'team', status:reviewStatus, submissionId:item.id, problemUrl:item.problem_url || '', upload:proof?.upload, fileName:'通过截图', blog:blog?.text || ''};
      const points = item.parts.reduce((sum, part) => sum + (part.points || 0), 0);
      const iconStatus = reviewStatus === 'approved' ? 'approved' : reviewStatus === 'rejected' ? 'pending' : 'pending';
      const icon = reviewStatus === 'approved' ? '✓' : reviewStatus === 'rejected' ? '!' : '◷';
      return `<div class="history-item"><div class="history-item-icon ${iconStatus}">${icon}</div><div><strong>第 ${item.week} 周提交</strong><small>归属 ${escapeHtml(item.record_date || '')} · ${new Date(item.submitted_at).toLocaleString('zh-CN')}</small></div><span>${points} 分</span><button class="history-view" type="button" data-review="${key}">查看内容</button></div>`;
    }).join('') : '<div class="queue-empty">该周暂无提交记录</div>';
    $$('.history-view', $('#historyList')).forEach((button) => button.addEventListener('click', () => { closeMemberHistory(); openReview(button.dataset.review, historyFromMemberList); }));
    $('#historyScore').textContent = `${payload.summary?.score || 0} 分`;
    $('#historyCount').textContent = `${payload.summary?.submissions || 0} 次`;
    const historyStatus = $('.history-summary > div:last-child strong');
    if (historyStatus && payload.summary?.qualified !== null && payload.summary?.qualified !== undefined) {
      historyStatus.textContent = payload.summary.qualified ? '已达标' : '未达标';
      historyStatus.className = payload.summary.qualified ? 'positive' : 'pending-text';
    }
    $('#historyWeek').disabled = Boolean(payload.archived);
    if ($('#historyWeek').tomselect) $('#historyWeek').tomselect[payload.archived ? 'disable' : 'enable']();
    $('.history-summary > div:first-child span').textContent = payload.archived ? '学期累计积分' : '本周积分';
    const subtitle = $('.history-author small');
    if (subtitle) subtitle.textContent = payload.archived ? `${payload.semester.name} · 已归档` : '本团队 · 按周查看训练记录';
    if (payload.archived) {
      $('#historyList').innerHTML = '<div class="queue-empty">该学期已归档，仅保留累计统计，提交明细已清理。</div>';
      if (historyStatus) { historyStatus.textContent = `${payload.summary?.qualifiedWeeks || 0} 周达标`; historyStatus.className = 'positive'; }
    } else if (historyStatus && payload.summary?.qualified == null) {
      historyStatus.textContent = '—';
    }
    historyModal.classList.add('open');
    historyModal.setAttribute('aria-hidden','false');
  } catch (error) { showToast('历史提交加载失败'); }
}
function closeMemberHistory() { historyModal.classList.remove('open'); historyModal.setAttribute('aria-hidden','true'); }
$$('.member-history-button').forEach((button) => button.addEventListener('click', () => openMemberHistory(button.dataset.memberHistory)));
$('#closeHistory').addEventListener('click', closeMemberHistory);
historyModal.addEventListener('click', (event) => { if (event.target.id === 'memberHistoryModal') closeMemberHistory(); });
$('#historyWeek').addEventListener('change', (event) => { if (activeHistoryMemberId) openLiveMemberHistory(activeHistoryMemberId); else showToast(`已切换到第 ${event.target.value.padStart(2,'0')} 周历史提交`); });
$$('.history-view').forEach((button) => button.addEventListener('click', () => {
  closeMemberHistory();
  openReview(button.dataset.review, historyFromMemberList);
}));

$('#memberSearch').addEventListener('input', (event) => {
  $('#memberSearchClear').hidden = !event.target.value;
  const query = event.target.value.trim().toLowerCase();
  $$('#membersGrid .member-card').forEach((card) => { card.style.display = !query || card.dataset.member.toLowerCase().includes(query) ? '' : 'none'; });
});

$('#memberSearchClear').addEventListener('click', () => {
  const input = $('#memberSearch');
  input.value = '';
  input.dispatchEvent(new Event('input', {bubbles:true}));
  input.focus();
});

// Resolve the current platform challenge without delaying the submission form.
let dailyChallengesRequest = null;
let dailyChallengesLoadedAt = 0;
async function loadDailyChallenges() {
  if (dailyChallengesRequest || Date.now() - dailyChallengesLoadedAt < 60000) return dailyChallengesRequest;
  const link = $('#dailyLeetcode');
  const status = $('#dailyChallengeStatus');
  if (!link || !status) return;
  link.removeAttribute('href');
  link.setAttribute('aria-disabled', 'true');
  status.textContent = '正在获取力扣今日题目…';
  dailyChallengesRequest = (async () => {
    try {
      const data = await communityRequest('/api/daily-challenges');
      if (!data.leetcode?.url || !/^https:\/\/leetcode\.cn\/problems\/[a-z0-9-]+\/$/.test(data.leetcode.url)) throw new Error(data.leetcode?.error || '力扣每日一题暂时无法获取，请稍后重试');
      link.href = data.leetcode.url;
      link.removeAttribute('aria-disabled');
      link.title = `${data.date} · 力扣每日一题`;
      status.textContent = '';
    } catch (error) {
      status.textContent = error.message || '力扣每日一题暂时无法获取，请稍后重试';
    } finally {
      dailyChallengesLoadedAt = Date.now();
      dailyChallengesRequest = null;
    }
  })();
  return dailyChallengesRequest;
}
$('#dailyLeetcode')?.addEventListener('click', event => {
  if (!event.currentTarget.hasAttribute('href')) {
    event.preventDefault();
    showToast($('#dailyChallengeStatus').textContent || '正在获取今日题目，请稍候');
    loadDailyChallenges();
  }
});

$('#editOwnSubmission').addEventListener('click', () => {
  if (activeReviewKey?.startsWith('mine-')) editOwnSubmission(activeSubmissionId);
});
$('#deleteOwnSubmission').addEventListener('click', async () => {
  if (!activeReviewKey?.startsWith('mine-')) return;
  const key = activeReviewKey;
  const record = ownRecords.get(Number(activeSubmissionId));
  if (!record?.can_delete) return;
  closeReview();
  if (!await confirmWorkbench('删除提交记录', '将删除整条提交及其材料，并撤销积分和有效提交次数。此操作无法恢复。', null, '确认后会移除整条记录，相关积分、次数和签到将重新计算。')) { openReview(key); return; }
  try {
    await communityRequest(`/api/submissions/${record.id}`, {method:'DELETE', body:JSON.stringify({version:record.version}), headers:{'Content-Type':'application/json'}});
    delete reviewData[key]; ownRecords.delete(record.id);
    await refreshAfterMutation({refreshAdmin:canManage});
    showToast('记录已删除，积分与提交次数已更新');
  } catch (error) { showToast(error.message); }
});

document.addEventListener('click', event => {
  const member = event.target.closest('[data-ranking-member]');
  if (member?.dataset.rankingMember && member.dataset.rankingMember !== 'undefined') openMemberHistory(member.dataset.rankingMember);
});
