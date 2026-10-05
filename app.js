const rankingData = {
  week: [],
  term: []
};

const pageTitles = {dashboard:'总览', submissions:'我的提交', leaderboard:'排行榜', arena:'每日擂台', showcase:'提交展示', members:'成员列表', admin:'审核工作台'};
const $ = (selector, root=document) => root.querySelector(selector);
const $$ = (selector, root=document) => [...root.querySelectorAll(selector)];
let canManage = false;
const demoMode = new URLSearchParams(window.location.search).get('demo') === '1';
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
let arenaRequestVersion = 0;
let membersRequestVersion = 0;
let historyRequestVersion = 0;
const leaderboardInFlight = new Map();
let pulseCopy = {
  4: {focus: '回看本周最有价值的一次题解', status: '已完成', tone: 'is-done'},
  5: {focus: '整理一次复杂度分析', status: '已完成', tone: 'is-done'},
  6: {focus: '完成第 3 次有效提交', status: '还剩 2 天', tone: 'is-warning'},
  7: {focus: '提前选好下周第一道题', status: '即将开始', tone: 'is-next'},
};
document.addEventListener('click', async (event) => { if (event.target.id !== 'logoutButton') return; await clubApi.request('/api/auth/logout', {method:'POST'}); window.location.href = '/auth.html'; });
const liveStyle = document.createElement('style'); liveStyle.textContent = '.my-submissions-live{margin-top:14px;padding:21px}.live-submission-row{display:flex;align-items:center;gap:12px;padding:13px 0;border-top:1px solid #edf0ee}.live-submission-info{display:flex;flex-direction:column;gap:4px;flex:1;min-width:0}.live-submission-info strong{font-size:12px}.live-submission-info small{font-size:10px;color:var(--muted)}.submission-thumb{width:44px;height:44px;border-radius:7px;background:#eef7f5;display:grid;place-items:center;overflow:hidden;color:var(--teal);flex:none}.submission-thumb img{width:100%;height:100%;object-fit:cover}.live-submission-row .review-view{color:var(--teal-dark);font-size:11px;font-weight:700;white-space:nowrap}.upload-preview{width:80px;height:55px;object-fit:cover;border-radius:6px;margin-bottom:4px}.status-tag.rejected{color:#b35d55;background:#fbeceb}'; document.head.appendChild(liveStyle);
const accessibilityStyle = document.createElement('style'); accessibilityStyle.textContent = '.toast{transition:transform .25s ease,opacity .25s ease}.search-box input:focus-visible{outline:2px solid var(--teal);outline-offset:2px}'; document.head.appendChild(accessibilityStyle);
const escapeHtml = (value='') => String(value).replace(/[&<>'"]/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));

const arenaStyle = document.createElement('style'); arenaStyle.textContent = '.arena-admin-panel{margin-top:14px;padding:24px}.arena-admin-panel h2{font-size:18px;margin:5px 0 6px}.arena-form{display:flex;flex-direction:column;gap:13px;margin-top:20px;max-width:920px}.arena-form input,.arena-form textarea{width:100%;border:1px solid var(--line);border-radius:8px;padding:11px 12px;background:#fbfefd;color:var(--ink)}.arena-form textarea{resize:vertical;line-height:1.55}.arena-form .file-field,.arena-dates label{display:flex;flex-direction:column;gap:7px;font-size:11px;color:var(--muted);font-weight:700}.arena-dates{display:grid;grid-template-columns:1fr 1fr;gap:13px}.arena-form .primary-button{width:max-content}.arena-form #arenaCloseButton{color:#b35d55;border-color:#f0d6d2}.arena-samples{background:#f5faf8;border:1px solid var(--line);border-radius:8px;padding:12px;text-align:left;max-width:680px}.arena-samples pre{white-space:pre-wrap;margin:8px 0 0;font:12px/1.6 monospace}@media(max-width:760px){.arena-dates{grid-template-columns:1fr}.arena-form .primary-button{width:100%}}'; document.head.appendChild(arenaStyle);
function renderLeaderboard(mode='week', target='#leaderboardList') {
  const el = $(target);
  if (!el) return;
  if (!rankingData[mode]?.length) {
    el.innerHTML = '<div class="queue-empty">暂无排行榜数据</div>';
    return;
  }
  el.innerHTML = rankingData[mode].map((row, index) => `
    <div class="leader-row ${row[0] === '林同学' ? 'you' : ''}">
      <span class="leader-rank ${index < 3 ? 'top' : ''}">${index + 1}</span>
      <span class="leader-member"><span class="leader-avatar">${row[1]}</span><span class="leader-name">${row[0]}${row[0] === '林同学' ? '（你）' : ''}</span></span>
      <span class="leader-score">${row[2]}<small> 分</small></span>
      <span class="leader-count">${row[3]} 次</span>
    </div>`).join('');
}

function setupDemoPreview() {
  document.body.classList.add('demo-mode');
  // The preview includes the admin workflow as a read-only, built-in scene.
  // Real sessions still derive this flag exclusively from /api/me.
  applyRoleUi('admin');
  const main = $('.main-content');
  if (main && !$('.demo-banner', main)) {
    const banner = document.createElement('div');
    banner.className = 'demo-banner';
    banner.innerHTML = '<strong>演示场景</strong><span>提交、成员与排名为前端示例，仅用于查看实际内容密度，不会写入数据库。</span>';
    main.prepend(banner);
  }
  rankingData.week = [
    ['王同学', '王', 12, 5],
    ['李同学', '李', 10, 4],
    ['林同学', '林', 7, 3],
    ['陈同学', '陈', 6, 3],
    ['周同学', '周', 4, 2]
  ];
  rankingData.term = [
    ['李同学', '李', 86, 28],
    ['王同学', '王', 79, 25],
    ['林同学', '林', 72, 23],
    ['陈同学', '陈', 67, 21],
    ['周同学', '周', 58, 19]
  ];
  renderLeaderboard('week');
  renderLeaderboard('week', '#leaderboardListFull');
  applyLiveDashboardState({
    current_week: {number: 6, closed: false, remainingSeconds: 2 * 86400 + 8 * 3600 + 42 * 60 + 16},
    semester: {minScore: 10, minSubmissions: 4, totalWeeks: 12},
    score: 7,
    submissions: 3,
    stats: {rank: 5, previousRank: 7, memberCount: 30, streakWeeks: 5, pendingParts: 1},
    pulse: [{number: 4, closed: true, qualified: true}, {number: 5, closed: true, qualified: true}, {number: 6, isCurrent: true, closed: false, qualified: false}, {number: 7, closed: false, qualified: false}],
  }, [{week: 6, parts: [
    {kind: 'proof', status: 'approved'},
    {kind: 'logic', status: 'pending'},
    {kind: 'blog', status: 'approved'},
  ]}]);
  const count = $('#membersView .date-chip');
  if (count) count.textContent = '30 位成员';
  if ($('#lastWeekIncompleteTitle')) $('#lastWeekIncompleteTitle').textContent = '第 05 周未达标成员';
  if ($('#lastWeekIncompleteList')) $('#lastWeekIncompleteList').innerHTML = '<div class="last-week-row"><strong>陈同学</strong><span>8 分 · 3 次有效提交</span><small>要求 10 分 + 4 次</small></div>';
  reviewData['demo-wang'] = {name:'王同学', initial:'王', time:'今天 09:42 · 第 4 次提交', logic:'先将数组按右端点排序，再用贪心策略选择当前能覆盖最多区间的点，时间复杂度为 O(n log n)。', visibility:'team', upload:'demo-proof-greedy.svg', fileName:'区间覆盖 · 通过截图', status:'approved'};
  reviewData['demo-li'] = {name:'李同学', initial:'李', time:'昨天 22:08 · 第 3 次提交', logic:'从双指针的边界处理开始，记录一次完整的思路推导与易错点。', visibility:'team', upload:'demo-proof-twopointer.svg', fileName:'双指针 · 通过截图', status:'approved'};
  reviewData['demo-chen'] = {name:'陈同学', initial:'陈', time:'周五 18:16 · 第 2 次提交', logic:'用状态压缩保存已经访问的节点集合，转移时只扩展一个新节点，空间复杂度 O(2ⁿ)。', visibility:'team', upload:'demo-proof-dp.svg', fileName:'状态压缩 · 通过截图', status:'approved'};
  wireShowcaseProofs();
}

function setView(view) {
  if (view === 'admin' && !canManage) view = 'dashboard';
  if (view === currentView) return;
  const previousView = currentView;
  currentView = view;
  const nextView = $(`#${view}View`);
  $$('.page-view').forEach((el) => el.classList.toggle('active', el === nextView));
  $$('.nav-item[data-view]').forEach((el) => el.classList.toggle('active', el.dataset.view === view));
  $('#pageTitle').textContent = pageTitles[view] || '总览';
  if (nextView) {
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
  if (view === 'leaderboard') renderLeaderboard('week', '#leaderboardListFull');
  if (!demoMode && previousView === 'admin' && view !== 'admin') stopAdminQueuePolling();
  if (!demoMode && view === 'admin') startAdminQueuePolling();
  if (!demoMode && view === 'submissions') loadMySubmissions();
  if (!demoMode && view === 'showcase') loadShowcase();
  if (!demoMode && view === 'arena') loadArenaData();
  if (!demoMode && view === 'members') loadMembersLive();
}

function wirePulseAtlas() {
  const detail = $('#pulseDetail');
  const focus = $('#pulseFocus');
  const status = $('#pulseStatus');
  const jump = $('#pulseJump');
  const track = $('.pulse-track');
  if (!detail || !focus || !status || !jump || !track || track.dataset.wired === 'true') return;
  track.dataset.wired = 'true';
  track.addEventListener('click', (event) => {
    const week = event.target.closest('.pulse-week');
    if (!week) return;
    const weeks = $$('.pulse-week', track);
    weeks.forEach((item) => {
      const selected = item === week;
      item.classList.toggle('is-selected', selected);
      item.setAttribute('aria-selected', String(selected));
    });
    const selected = pulseCopy[week.dataset.pulseWeek] || pulseCopy[6];
    focus.textContent = selected.focus;
    status.textContent = selected.status;
    status.className = `pulse-warning ${selected.tone}`;
    jump.textContent = week.classList.contains('is-current') ? '打开提交入口 ↗' : '查看这一周 ↗';
  });
  jump.addEventListener('click', () => {
    const current = $('.pulse-week.is-selected')?.dataset.pulseWeek || '6';
    if ($(`.pulse-week[data-pulse-week="${current}"]`)?.classList.contains('is-current')) openModal();
    else setView('submissions');
  });
}

function updatePulseCopy(nextCopy, currentWeek) {
  pulseCopy = {...pulseCopy, ...nextCopy};
  const selectedWeek = $(`.pulse-week[data-pulse-week="${currentWeek || 6}"]`) || $('.pulse-week.is-selected');
  selectedWeek?.click();
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
    if (formNote) formNote.textContent = countdownClosed ? '本周已截止' : `距离截止还有 ${formatRemaining(remaining)}`;
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

function renderPulseWeeks(pulse = [], currentNumber) {
  const track = $('.pulse-track');
  if (!track || !pulse.length) return;
  const line = $('.pulse-line', track);
  $$('.pulse-week', track).forEach((item) => item.remove());
  pulse.forEach((item) => {
    const button = document.createElement('button');
    button.className = `pulse-week ${item.isCurrent ? 'is-current is-selected' : item.qualified ? 'is-complete' : item.number > currentNumber ? 'is-next' : ''}`;
    button.dataset.pulseWeek = item.number;
    button.type = 'button';
    button.setAttribute('role', 'tab');
    button.setAttribute('aria-selected', String(item.isCurrent));
    button.innerHTML = `<span>${String(item.number).padStart(2, '0')}</span><small>${item.isCurrent ? '进行中' : item.qualified ? '已完成' : item.number > currentNumber ? '即将开始' : '未达标'}</small>`;
    track.insertBefore(button, line || null);
  });
  wirePulseAtlas();
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
  const isComplete = scoreGap === 0 && submissionGap === 0;
  const focus = isComplete
    ? '保持本周训练节拍，继续记录新题'
    : pendingLabels.length
      ? `等待审核：${pendingLabels.join('、')}`
      : submissionGap > 0
        ? `完成第 ${submissionCount + 1} 次有效提交`
        : `补交${missingLabels[0] || '材料'}，再累积 ${scoreGap} 分`;
  const requirement = isComplete
    ? '本周目标已达成，可继续提交'
    : pendingLabels.length
      ? `审核中 · ${pendingLabels.join(' · ')}`
      : submissionGap > 0
        ? `还需 ${submissionGap} 次有效提交`
      : missingLabels.length ? `可补交：${missingLabels.join(' · ')}` : `还差 ${scoreGap} 分`;
  const status = isComplete ? '本周已达标' : week.closed ? '本周已截止' : scoreGap > 0 && submissionGap > 0 ? `还差 ${scoreGap} 分 · ${submissionGap} 次` : scoreGap > 0 ? `还差 ${scoreGap} 分` : submissionGap > 0 ? `还需 ${submissionGap} 次` : '等待审核';
  const tone = isComplete ? 'is-done' : week.closed ? 'is-warning' : 'is-warning';
  updatePulseCopy({[week.number]: {focus, status, tone}}, week.number);
  renderPulseWeeks(dashboard.pulse || [], week.number);
  startDeadlineCountdown(week.remainingSeconds, week.closed);
  const stageScore = $('#stageScore');
  const stageScoreMax = $('.stage-title span:last-child');
  const stageCaption = $('#stageScoreCaption');
  const stageFocus = $('#stageFocus');
  const stageFocusMeta = $('#stageFocusMeta');
  if (stageScore) stageScore.textContent = String(score).padStart(2, '0');
  if (stageScoreMax) stageScoreMax.textContent = `/${minScore}`;
  if (stageCaption) stageCaption.textContent = isComplete ? '本周已达标' : `还差 ${scoreGap} 分达标`;
  if (stageFocus) stageFocus.textContent = focus;
  if (stageFocusMeta) stageFocusMeta.textContent = requirement;
  const stageWeek = $('#stageWeek');
  if (stageWeek) stageWeek.textContent = `WEEK ${String(week.number).padStart(2, '0')} / ${String(semester.totalWeeks || 0).padStart(2, '0')}`;
  const streak = Number(stats.streakWeeks || 0);
  if ($('#stageStreak')) $('#stageStreak').textContent = `${String(streak).padStart(2, '0')} 周`;
  if ($('#streakValue')) $('#streakValue').innerHTML = `${streak} <small>周</small>`;
  if ($('#quickSubmissions')) $('#quickSubmissions').textContent = `${submissionCount} 次提交`;
  if ($('#quickPending')) $('#quickPending').textContent = `${Number(stats.pendingParts || pending.length)} 项待审核`;
  if ($('#quickRank')) $('#quickRank').textContent = stats.rank ? `排名 #${stats.rank}` : '排名 —';
  if ($('#rankValue')) $('#rankValue').innerHTML = stats.rank ? `#${stats.rank} <small>/ ${stats.memberCount || 0} 人</small>` : '— <small>/ — 人</small>';
  const rankDelta = stats.previousRank && stats.rank ? stats.previousRank - stats.rank : 0;
  if ($('#rankChange')) $('#rankChange').textContent = rankDelta ? `${rankDelta > 0 ? '↑' : '↓'} ${Math.abs(rankDelta)}` : '—';
  if ($('#rankChangeLabel')) $('#rankChangeLabel').textContent = rankDelta ? '较上周' : '暂无变化';
  if ($('#rankGap')) $('#rankGap').textContent = '本周排名';
  if ($('#yourRankValue')) $('#yourRankValue').textContent = stats.rank ? `#${stats.rank}` : '—';
  if ($('#yourRankChange')) $('#yourRankChange').textContent = rankDelta ? `${rankDelta > 0 ? '↑' : '↓'} ${Math.abs(rankDelta)} 名` : '暂无变化';
  const featuredValue = $('.metric-card.featured .metric-value');
  const featuredFoot = $('.metric-card.featured .metric-foot span');
  const submissionValue = $('.metric-card:nth-child(2) .metric-value');
  const submissionFoot = $('.metric-card:nth-child(2) .metric-foot span');
  if (featuredValue) featuredValue.innerHTML = `${score} <small>/ ${minScore} 分</small>`;
  if (featuredFoot) featuredFoot.textContent = isComplete ? '本周已达标' : `还差 ${scoreGap} 分达标`;
  if (submissionValue) submissionValue.innerHTML = `${submissionCount} <small>/ ${minSubmissions} 次</small>`;
  if (submissionFoot) submissionFoot.textContent = submissionGap ? `再完成 ${submissionGap} 次即可` : '本周次数已达标';
  const progress = $('.metric-card.featured .progress-track span');
  if (progress) progress.style.width = `${minScore ? Math.min(100, Math.round(score / minScore * 100)) : 0}%`;
  const dots = $$('.metric-card:nth-child(2) .submission-dots i');
  dots.forEach((dot, index) => dot.classList.toggle('done', index < Math.min(submissionCount, dots.length)));
}

function applyRoleUi(role) {
  canManage = role === 'admin' || role === 'owner';
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

async function loadShowcase() {
  const grid = $('#showcaseGrid');
  if (!grid) return;
  const requestVersion = ++showcaseRequestVersion;
  try {
    const response = await clubApi.request('/api/showcase');
    if (requestVersion !== showcaseRequestVersion) return;
    if (!response.ok) { grid.innerHTML = '<div class="queue-empty">提交展示加载失败，请刷新重试</div>'; return; }
    const items = (await response.json()).submissions || [];
    if (requestVersion !== showcaseRequestVersion) return;
    if (!items.length) { grid.innerHTML = '<div class="queue-empty">当前没有可展示的提交内容</div>'; return; }
    grid.innerHTML = items.map((item) => {
      const visibleParts = item.parts.filter((part) => part.status === 'approved');
      const logic = visibleParts.find((part) => part.kind === 'logic' && part.text);
      const blog = visibleParts.find((part) => part.kind === 'blog' && (part.link || part.text));
      const proof = visibleParts.find((part) => part.kind === 'proof');
      const kinds = [logic && 'logic', blog && 'blog', proof && 'proof'].filter(Boolean).join(' ');
      const key = `showcase-${item.id}`;
      reviewData[key] = {name:item.member_name, initial:item.member_name.slice(0,1), time:`第 ${item.week} 周 · ${new Date(item.submitted_at).toLocaleString('zh-CN')}`, logic:logic?.text || '成员未提交写题逻辑。', visibility:item.visibility || 'team', status:'approved', submissionId:item.id, upload:proof?.upload, fileName:'通过截图'};
      const image = proof?.upload ? `<button class="proof-image-button" type="button" data-review="${key}" aria-label="查看${escapeHtml(item.member_name)}的通过截图"><img src="${escapeHtml(proof.upload)}" alt="${escapeHtml(item.member_name)}的通过截图" /></button>` : '<span class="preview-check" aria-hidden="true">✓</span>';
      return `<article class="showcase-card" data-kind="${kinds}"><div class="showcase-card-top"><div class="member-line"><span class="leader-avatar">${escapeHtml(item.member_name.slice(0,1))}</span><div><strong>${escapeHtml(item.member_name)}</strong><small>第 ${item.week} 周 · ${new Date(item.submitted_at).toLocaleString('zh-CN')}</small></div></div><span class="visibility-tag">${item.visibility === 'private' ? '仅管理员可见' : '团队可见'}</span></div><div class="proof-preview">${image}<div><strong>${proof ? '通过截图已审核' : '截图未展示'}</strong><small>${proof ? `截图材料 · +${proof.points || 0} 分` : '当前提交没有已通过截图'}</small></div></div>${logic ? `<div class="shared-content"><span class="content-type">写题逻辑</span><p>${escapeHtml(logic.text)}</p></div>` : ''}${blog ? `<div class="shared-content"><span class="content-type">Blog 题解</span><a class="blog-link" href="${escapeHtml(blog.link || '#')}" target="_blank" rel="noopener">阅读题解 →</a></div>` : ''}</article>`;
    }).join('');
    wireShowcaseProofs(grid);
  } catch (error) {
    grid.innerHTML = '<div class="queue-empty">提交展示加载失败，请检查网络连接</div>';
  }
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

function markApprovalComplete(row, delay = 0) {
  if (!row) return;
  window.setTimeout(() => {
    row.classList.add('approval-complete');
    row.dataset.approvalState = 'approved';
    const checkbox = row.querySelector('input[type="checkbox"]');
    if (checkbox) { checkbox.checked = false; checkbox.disabled = true; }
    const status = row.querySelector('.status-tag');
    if (status) { status.className = 'status-tag approved'; status.textContent = '已通过'; }
    let marker = row.querySelector('.approval-checkmark');
    if (!marker) {
      marker = document.createElement('span');
      marker.className = 'approval-checkmark';
      marker.setAttribute('aria-hidden', 'true');
      marker.innerHTML = '<span></span>';
      row.insertBefore(marker, row.querySelector('.review-avatar'));
    }
    const content = row.querySelector('.review-content strong');
    if (content && !content.textContent.includes('已通过')) content.textContent = `${content.textContent} · 已通过`;
    const score = row.querySelector('.approval-score');
    if (!score) {
      const badge = document.createElement('span');
      badge.className = 'approval-score';
      badge.textContent = '+1 分';
      row.appendChild(badge);
    }
  }, delay);
}

function finishApprovalRows(rows, message) {
  rows.forEach((row, index) => {
    const checkbox = row.querySelector('input[type="checkbox"]');
    if (checkbox) checkbox.checked = false;
    markApprovalComplete(row, index * 110);
  });
  showToast(message);
  updateSelected();
}

function ensureArenaAdminPanel(role) {
  if (!['admin','owner'].includes(role) || $('#arenaAdminPanel')) return;
  const host = $('#adminView'); if (!host) return;
  const panel = document.createElement('article'); panel.id = 'arenaAdminPanel'; panel.className = 'panel arena-admin-panel';
  panel.innerHTML = `<div><p class="section-label">ARENA CONTROL</p><h2>每日擂台出题</h2><p class="muted">配置题面、样例和测题脚本，发布后成员端开放挑战。</p></div><form id="arenaAdminForm" class="arena-form"><input id="arenaTitle" required maxlength="120" placeholder="题目标题，例如：每日算法挑战 #01" /><textarea id="arenaDescription" rows="5" placeholder="题目描述：输入格式、输出格式、数据范围、判题规则"></textarea><textarea id="arenaSamples" rows="4" placeholder="样例（建议按：输入 / 输出 分隔，可填写多组）"></textarea><label class="file-field">测题脚本（可选）<input id="arenaScript" type="file" accept=".py,.js,.sh,.zip" /></label><div class="arena-dates"><label>开放时间<input id="arenaOpens" type="datetime-local" required /></label><label>截止时间<input id="arenaCloses" type="datetime-local" required /></label></div><div><button class="primary-button" type="submit">发布擂台</button> <button class="secondary-button" id="arenaCloseButton" type="button">关闭当前擂台</button> <span id="arenaAdminStatus" class="muted"></span></div></form>`;
  host.appendChild(panel);
  $('#arenaAdminForm').addEventListener('submit', async (event) => { event.preventDefault(); const form = new FormData(); form.set('title',$('#arenaTitle').value); form.set('description',$('#arenaDescription').value); form.set('samples',$('#arenaSamples').value); form.set('opens_at',new Date($('#arenaOpens').value).toISOString()); form.set('closes_at',new Date($('#arenaCloses').value).toISOString()); form.set('is_published','true'); if ($('#arenaScript').files[0]) form.set('judge_script',$('#arenaScript').files[0]); const response = await clubApi.request('/api/arena', {method:'POST', body:form}); const payload = await response.json().catch(()=>({})); $('#arenaAdminStatus').textContent = response.ok ? '已发布并保存' : (payload.error || '发布失败，请检查填写内容'); showToast(response.ok ? '每日擂台已发布' : '擂台发布失败'); });
  $('#arenaCloseButton').addEventListener('click', async () => { const response = await clubApi.request('/api/admin/arena', {method:'DELETE'}); if (response.ok) { $('#arenaAdminStatus').textContent = '当前擂台已关闭'; showToast('当前擂台已关闭'); } else showToast('关闭擂台失败，请重试'); });
}

function resetSubmissionForm() {
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
}
function openModal() { resetSubmissionForm(); $('#submissionModal').classList.add('open'); $('#submissionModal').setAttribute('aria-hidden','false'); $('#proofImage').focus(); }
function closeModal() { $('#submissionModal').classList.remove('open'); $('#submissionModal').setAttribute('aria-hidden','true'); }

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

const reviewData = {
  zhou: {name:'周同学', initial:'周', time:'今天 11:06 · 第 3 次提交', logic:'使用排序和双指针，先固定左端点，再移动右端点寻找满足条件的最优解。', visibility:'team'},
  chen: {name:'陈同学', initial:'陈', time:'今天 10:48 · 第 4 次提交', logic:'通过状态压缩记录已访问状态，逐步扩展下一步转移。', visibility:'private'},
  zhao: {name:'赵同学', initial:'赵', time:'今天 09:32 · 第 2 次提交', logic:'先处理边界情况，再用贪心策略降低整体复杂度。', visibility:'team'}
};
function stopAdminQueuePolling() {
  window.clearInterval(adminQueueTimer);
  adminQueueTimer = null;
  adminQueueRequestVersion += 1;
  adminQueueAbortController?.abort();
  adminQueueAbortController = null;
}

function startAdminQueuePolling() {
  stopAdminQueuePolling();
  if (demoMode || !canManage || currentView !== 'admin' || document.hidden) return;
  loadAdminQueue({silent: true});
  adminQueueTimer = window.setInterval(() => loadAdminQueue({silent: true}), 15000);
}

async function loadAdminQueue({silent = false} = {}) {
  const list = $('#reviewList');
  if (!list || !canManage || currentView !== 'admin') return;
  if (adminQueueInFlight) return adminQueueInFlight;
  const requestVersion = ++adminQueueRequestVersion;
  const controller = new AbortController();
  adminQueueAbortController = controller;
  const request = (async () => {
    try {
      const response = await clubApi.request('/api/submissions', {signal: controller.signal});
      if (requestVersion !== adminQueueRequestVersion) return;
      if (!response.ok) { list.innerHTML = '<div class="queue-empty">审核队列加载失败，请刷新重试</div>'; return; }
      const payload = await response.json();
      if (requestVersion !== adminQueueRequestVersion) return;
    const pending = (payload.submissions || []).filter((item) => item.parts?.some((part) => part.status === 'pending'));
    const pendingCount = pending.reduce((total, item) => total + item.parts.filter((part) => part.status === 'pending').length, 0);
    const adminStats = $$('.admin-stat strong');
    if (adminStats[0]) adminStats[0].textContent = String(payload.stats?.pendingParts ?? pendingCount);
    if (adminStats[1]) adminStats[1].textContent = String(payload.stats?.reviewedParts ?? 0);
    if (adminStats[2]) adminStats[2].innerHTML = `${payload.stats?.qualificationRate ?? 0}<small>%</small>`;
    $$('.inline-count').forEach((element) => { element.textContent = String(pendingCount); });
    $$('.count-badge').forEach((element) => { element.textContent = String(pendingCount); });
    const lastWeekTitle = $('#lastWeekIncompleteTitle');
    const lastWeekList = $('#lastWeekIncompleteList');
    const lastWeekNumber = payload.stats?.lastWeekNumber;
    const incompleteMembers = payload.stats?.lastWeekIncompleteMembers || [];
    if (lastWeekTitle) lastWeekTitle.textContent = lastWeekNumber ? `第 ${lastWeekNumber} 周未达标成员` : '上周未达标成员';
    if (lastWeekList) {
      lastWeekList.innerHTML = !lastWeekNumber
        ? '<div class="queue-empty">暂无上一周数据</div>'
        : incompleteMembers.length
          ? incompleteMembers.map((member) => `<div class="last-week-row"><strong>${escapeHtml(member.name)}</strong><span>${member.score} 分 · ${member.submissions} 次有效提交</span><small>要求 ${member.requiredScore} 分 ${member.requiredBoth ? '+' : '或'} ${member.requiredSubmissions} 次</small></div>`).join('')
          : '<div class="queue-empty">上一周全员已完成每周任务</div>';
    }
    const firstStat = $('.admin-stat strong');
    if (firstStat) firstStat.textContent = String(pendingCount);
    if (!pending.length) {
      list.innerHTML = '<div class="queue-empty">当前没有待审核提交</div>';
      return;
    }
    list.innerHTML = pending.map((item) => {
      const key = `submission-${item.id}`;
      const pendingParts = item.parts.filter((part) => part.status === 'pending');
      const proofPart = item.parts.find((part) => part.kind === 'proof');
      const visibility = item.visibility || 'team';
      reviewData[key] = {name:item.member_name, initial:item.member_name.slice(0,1), time:new Date(item.submitted_at).toLocaleString('zh-CN'), logic:item.parts.find((part) => part.kind === 'logic')?.text || '成员未提交写题逻辑。', visibility, submissionId:item.id, upload:proofPart?.upload, fileName:'通过截图'};
      return `<div class="review-row" data-submission-id="${item.id}"><input type="checkbox" /><span class="review-avatar">${escapeHtml(item.member_name.slice(0,1))}</span><span class="review-content"><strong>${escapeHtml(item.member_name)} · ${pendingParts.length} 项待审核</strong><small>${new Date(item.submitted_at).toLocaleString('zh-CN')}</small></span><span class="visibility-tag ${visibility === 'private' ? 'private' : ''}">${visibility === 'private' ? '不公开' : '团队可见'}</span><button class="review-view" type="button" data-review="${key}">查看内容</button><span class="status-tag pending">待审核</span></div>`;
    }).join('');
    $$('.review-view', list).forEach((button) => button.addEventListener('click', () => openReview(button.dataset.review)));
    $$('input[type="checkbox"]', list).forEach((box) => box.addEventListener('change', updateSelected));
    } catch (error) {
      if (error.name === 'AbortError' || requestVersion !== adminQueueRequestVersion) return;
      if (!silent) list.innerHTML = '<div class="queue-empty">审核队列加载失败，请检查网络连接</div>';
    }
  })();
  const tracked = request.finally(() => {
    if (adminQueueInFlight === tracked) adminQueueInFlight = null;
    if (adminQueueAbortController === controller) adminQueueAbortController = null;
  });
  adminQueueInFlight = tracked;
  return tracked;
}

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
    list.innerHTML = submissions.slice(0, 5).flatMap((submission) => submission.parts.map((part) => {
      const status = part.status === 'approved' ? 'approved' : part.status === 'rejected' ? 'rejected' : 'pending';
      const label = part.kind === 'proof' ? '通过截图' : part.kind === 'logic' ? '写题逻辑' : 'Blog';
      const statusText = status === 'approved' ? '通过审核' : status === 'rejected' ? '已退回' : '等待管理员审核';
      return `<div class="submission-row"><div class="status-marker ${status}">${status === 'approved' ? '✓' : status === 'rejected' ? '!' : '◷'}</div><div class="submission-info"><strong>${label} · 第 ${submission.week} 周</strong><span>${new Date(submission.submitted_at).toLocaleString('zh-CN')} · ${statusText}</span></div><span class="score">+${part.points || 0} <small>分</small></span><span class="status-tag ${status}">${status === 'approved' ? '已通过' : status === 'rejected' ? '已退回' : '待审核'}</span></div>`;
    })).join('');
  } catch (error) { if (requestVersion === activityRequestVersion) list.innerHTML = '<div class="queue-empty">最近提交加载失败，请检查网络连接</div>'; }
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
    const empty = $('.empty-state', page);
    page.querySelector('.my-submissions-live')?.remove();
    if (!submissions.length) { if (empty) { empty.hidden = false; empty.innerHTML = '<div class="empty-icon">□</div><h2>这里会留下你的训练轨迹</h2><p>当前还没有提交记录。</p><button class="secondary-button" id="emptyAction" type="button">继续提交</button>'; $('#emptyAction')?.addEventListener('click', openModal); } return; }
    const list = document.createElement('div');
    list.className = 'panel my-submissions-live';
    list.innerHTML = `<div class="panel-heading"><div><p class="section-label">PERSISTED RECORDS</p><h2>已保存的提交</h2></div><span class="muted">共 ${submissions.length} 条</span></div>` + submissions.map((item) => {
      const key = `mine-${item.id}`;
      const proof = item.parts.find((part) => part.kind === 'proof');
      const logic = item.parts.find((part) => part.kind === 'logic');
      const reviewStatus = item.parts.some((part) => part.status === 'pending') ? 'pending' : item.parts.some((part) => part.status === 'approved') ? 'approved' : 'rejected';
      reviewData[key] = {name:item.member_name, initial:item.member_name.slice(0,1), time:new Date(item.submitted_at).toLocaleString('zh-CN'), logic:logic?.text || '未提交写题逻辑。', visibility:item.visibility || 'team', status:reviewStatus, submissionId:item.id, upload:proof?.upload, fileName:'通过截图'};
      const approved = item.parts.filter((part) => part.status === 'approved').reduce((sum, part) => sum + (part.points || 0), 0);
      return `<div class="live-submission-row"><div class="submission-thumb">${proof?.upload ? `<img src="${proof.upload}" alt="通过截图" />` : '<span>▧</span>'}</div><div class="live-submission-info"><strong>第 ${String(item.week).padStart(2,'0')} 周提交</strong><small>${new Date(item.submitted_at).toLocaleString('zh-CN')} · 已保存至数据库</small></div><span class="score">+${approved} 分</span><button class="review-view" type="button" data-review="${key}">查看内容</button></div>`;
    }).join('');
    if (empty) empty.hidden = true;
    page.appendChild(list);
    $$('.review-view', list).forEach((button) => button.addEventListener('click', () => openReview(button.dataset.review)));
  } catch (error) { if (requestVersion === submissionsRequestVersion) { const empty = $('.empty-state', page); if (empty) { empty.hidden = false; empty.innerHTML = '<div class="empty-icon">!</div><h2>提交记录加载失败</h2><p>请检查网络连接后重试。</p>'; } } }
}
const reviewModal = $('#reviewModal');
let activeReviewKey = null;
let activeSubmissionId = null;
function openReview(key) {
  const data = reviewData[key];
  if (!data) return;
  activeReviewKey = key;
  activeSubmissionId = data.submissionId || null;
  $('#reviewMember').textContent = data.name;
  $('#reviewAvatar').textContent = data.initial;
  $('#reviewTime').textContent = data.time;
  const reviewStatus = $('.review-author .status-tag');
  if (reviewStatus) {
    const approved = data.status === 'approved';
    reviewStatus.textContent = approved ? '已通过' : data.status === 'rejected' ? '已退回' : '待审核';
    reviewStatus.className = `status-tag ${approved ? 'approved' : data.status === 'rejected' ? 'rejected' : 'pending'}`;
  }
  $('#reviewLogic').textContent = data.logic;
  const image = $('#reviewImage');
  const fallback = $('#reviewImageFallback');
  image.onerror = () => { image.classList.remove('visible'); fallback.classList.remove('hidden'); $('#reviewFileMeta').textContent = '图片加载失败，请检查媒体文件服务'; };
  if (data.upload) { image.src = `${data.upload}${data.upload.includes('?') ? '&' : '?'}v=${Date.now()}`; image.classList.add('visible'); fallback.classList.add('hidden'); } else { image.removeAttribute('src'); image.classList.remove('visible'); fallback.classList.remove('hidden'); }
  $('#reviewFileName').textContent = data.fileName || (data.upload ? '通过截图' : '演示占位图片');
  $('#reviewFileMeta').textContent = data.upload ? '已上传，可点击放大查看' : '当前记录没有可预览图片';
  $('#visibilitySelect').value = data.visibility;
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
$('#closeReview').addEventListener('click', closeReview);
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
$('#visibilitySelect').addEventListener('change', async (event) => {
  const nextVisibility = event.target.value;
  const previousVisibility = reviewData[activeReviewKey]?.visibility || 'team';
  if (!demoMode && activeSubmissionId) {
    const response = await clubApi.request('/api/admin/submissions/bulk-approve', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({submission_ids:[activeSubmissionId], action:'visibility', visibility:nextVisibility})});
    if (!response.ok) { event.target.value = previousVisibility; showToast('展示权限保存失败，请重试'); return; }
  }
  const row = $(`.review-view[data-review="${activeReviewKey}"]`)?.closest('.review-row');
  const tag = row?.querySelector('.visibility-tag');
  if (tag) {
    const isTeamVisible = event.target.value === 'team';
    tag.textContent = isTeamVisible ? '团队可见' : '不公开';
    tag.classList.toggle('private', !isTeamVisible);
  }
  if (reviewData[activeReviewKey]) reviewData[activeReviewKey].visibility = nextVisibility;
  showToast(nextVisibility === 'team' ? '已设置为团队成员可见' : '已设置为不公开');
});
async function persistReview(action) {
  if (!activeSubmissionId) return true;
  const response = await clubApi.request('/api/admin/submissions/bulk-approve', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({submission_ids:[activeSubmissionId], action, note:action === 'approve' ? '' : '管理员退回'})});
  if (!response.ok) return false;
  return true;
}
$('#approveReview').addEventListener('click', async () => {
  const reviewedKey = activeReviewKey;
  const reviewedRow = $(`.review-view[data-review="${reviewedKey}"]`)?.closest('.review-row');
  const ok = await persistReview('approve');
  closeReview();
  if (!ok) { showToast('审核保存失败，请重试'); return; }
  if (reviewData[reviewedKey]) reviewData[reviewedKey].status = 'approved';
  markApprovalComplete(reviewedRow);
  showToast('审核通过，积分已更新');
  if (!demoMode && activeSubmissionId) window.setTimeout(() => refreshAfterMutation({refreshAdmin: true}), 450);
});
$('#rejectReview').addEventListener('click', async () => {
  const ok = await persistReview('reject');
  closeReview();
  showToast(ok ? '已退回该提交，列表正在更新' : '审核保存失败，请重试');
  if (ok && !demoMode) window.setTimeout(() => refreshAfterMutation({refreshAdmin: true}), 250);
});

$$('[data-showcase-filter]').forEach((button) => button.addEventListener('click', () => {
  const group = button.closest('.segmented');
  syncSegmented(group, button);
  const filter = button.dataset.showcaseFilter;
  $$('#showcaseGrid .showcase-card').forEach((card) => { card.style.display = filter === 'all' || card.dataset.kind.split(' ').includes(filter) ? '' : 'none'; });
}));

function wireRankingControls(root=document) {
  $$('[data-ranking]', root).forEach((button) => button.addEventListener('click', async () => {
    const group = button.closest('.panel, .leaderboard-panel, .full-leaderboard');
    syncSegmented(button.closest('.segmented'), button);
    const target = group && group.id === 'leaderboardListFull' ? '#leaderboardListFull' : (group && $('.full-leaderboard', document) === group ? '#leaderboardListFull' : '#leaderboardList');
    const scope = button.dataset.ranking;
    if (!demoMode && !rankingData[scope].length) {
      button.disabled = true;
      await loadLeaderboard(scope);
      button.disabled = false;
    }
    renderLeaderboard(scope, target);
  }));
}

renderLeaderboard('week');
wireRankingControls();
initSegmentedControls();

$('#teamButton').addEventListener('click', () => $('#teamMenu').classList.toggle('open'));
// Team choices are populated from /api/me. Never switch to placeholder teams.
document.addEventListener('click', (event) => { if (!event.target.closest('.team-switcher')) $('#teamMenu').classList.remove('open'); });

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
    showToast('演示提交成功，已进入审核队列');
    if (submitButton) { submitButton.disabled = false; submitButton.removeAttribute('aria-busy'); submitButton.textContent = submitButton.dataset.label || '提交审核'; }
    return;
  }
  const formData = new FormData(form);
  formData.set('proof', $('#proofImage').files[0]);
  formData.set('logic', $('#logicText').value);
  formData.set('blog', $('#blogUrl').value);
  try {
    const response = await clubApi.request('/api/submissions', {method:'POST', body:formData});
    if (response.status === 401 || response.status === 403) throw new Error('请先登录后再提交');
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.error || '提交失败，请稍后重试');
    }
  } catch (error) { showToast(error.message || '提交失败，请稍后重试'); if (submitButton) { submitButton.disabled = false; submitButton.removeAttribute('aria-busy'); submitButton.textContent = submitButton.dataset.label || '提交审核'; } return; }
  closeModal();
  resetSubmissionForm();
  playFeedback('submission-success');
  showToast('提交成功，已进入审核队列');
  refreshAfterMutation({refreshAdmin: canManage});
  if (submitButton) { submitButton.disabled = false; submitButton.removeAttribute('aria-busy'); submitButton.textContent = submitButton.dataset.label || '提交审核'; }
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

const selectAll = $('#selectAll');
const reviewCheckboxes = () => $$('#reviewList input[type="checkbox"]');
function updateSelected() { $('#selectedCount').textContent = reviewCheckboxes().filter((box) => box.checked).length; }
selectAll.addEventListener('change', () => { reviewCheckboxes().forEach((box) => { box.checked = selectAll.checked; }); updateSelected(); });
reviewCheckboxes().forEach((box) => box.addEventListener('change', updateSelected));
function approveSelected(all=false) {
  const boxes = all ? reviewCheckboxes() : reviewCheckboxes().filter((box) => box.checked);
  if (!boxes.length) { showToast('请先选择要审批的提交'); return; }
  const ids = boxes.map((box) => box.closest('.review-row').dataset.submissionId).filter(Boolean).map(Number);
  const rows = boxes.map((box) => box.closest('.review-row')).filter(Boolean);
  const finish = (ok) => {
    if (!ok) { showToast('审批保存失败，请重试'); return; }
    finishApprovalRows(rows, `已通过 ${rows.length} 条提交，积分已更新`);
    selectAll.checked = false;
    if (!demoMode) window.setTimeout(() => refreshAfterMutation({refreshAdmin: true}), 550 + Math.min(rows.length, 6) * 110);
  };
  if (!ids.length) {
    if (demoMode) { finish(true); return; }
    showToast('请先等待真实提交加载');
    return;
  }
  clubApi.request('/api/admin/submissions/bulk-approve', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({submission_ids:ids})}).then((response) => finish(response.ok)).catch(() => finish(false));
}
$('#approveSelected').addEventListener('click', () => approveSelected(false));
$('#approveAllTop').addEventListener('click', () => approveSelected(true));

function clearStaticPreview() {
  const loading = '<div class="queue-empty">正在加载真实数据…</div>';
  rankingData.week = [];
  rankingData.term = [];
  ['#leaderboardList', '#leaderboardListFull'].forEach((selector) => {
    const element = $(selector);
    if (element) { element.innerHTML = loading; element.setAttribute('aria-live', 'polite'); }
  });
  ['#submissionList', '#showcaseGrid', '#membersGrid', '#reviewList', '#historyList', '#submissionsView .empty-state', '#arenaView .arena-empty'].forEach((selector) => {
    const element = $(selector);
    if (element) { element.innerHTML = loading; element.setAttribute('aria-live', 'polite'); }
  });
  const rank = $('.your-rank strong');
  if (rank) rank.textContent = '—';
  const rankChange = $('.your-rank .rank-up');
  if (rankChange) rankChange.textContent = '加载中…';
  const memberCount = $('#membersView .date-chip');
  const leaderboardLabel = $('#leaderboardWeekLabel');
  const showcaseLabel = $('.showcase-toolbar .filter-chip');
  if (memberCount) memberCount.textContent = '— 位成员';
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
  if (dashboard.current_week) {
    const select = $('#historyWeek');
    if (select) select.innerHTML = [dashboard.current_week.number, dashboard.current_week.number - 1, dashboard.current_week.number - 2].filter((number) => number > 0).map((number) => `<option value="${number}">第 ${String(number).padStart(2, '0')} 周</option>`).join('');
    const note = $('.form-note span');
    if (note) note.textContent = `第 ${String(dashboard.current_week.number).padStart(2, '0')} 周`;
    const kicker = $('.welcome-row .kicker');
    if (kicker) kicker.textContent = `${dashboard.semester?.name || '当前学期'} · 第 ${String(dashboard.current_week.number).padStart(2, '0')} 周`;
    const label = `第 ${String(dashboard.current_week.number).padStart(2, '0')} 周 · ${dashboard.semester?.name || '当前学期'}`;
    const leaderboardLabel = $('#leaderboardWeekLabel');
    if (leaderboardLabel) leaderboardLabel.textContent = label;
    const showcaseLabel = $('.showcase-toolbar .filter-chip');
    if (showcaseLabel) showcaseLabel.textContent = `第 ${String(dashboard.current_week.number).padStart(2, '0')} 周⌄`;
  }
  const mineResult = await fetchMineSubmissions({force: forceMine});
  if (mineResult.ok) applyLiveDashboardState(dashboard, mineResult.submissions);
  return dashboard;
}

async function loadLeaderboard(scope = 'week') {
  if (leaderboardInFlight.has(scope)) return leaderboardInFlight.get(scope);
  const request = (async () => {
    try {
      const response = await clubApi.request(`/api/leaderboard?scope=${scope}`);
      if (!response.ok) return false;
      const payload = await response.json();
      rankingData[scope] = (payload.rows || []).slice(0, 5).map((row) => [row.name, row.name.slice(0, 1), row.score, row.submissions]);
      renderLeaderboard(scope, scope === 'week' ? '#leaderboardList' : '#leaderboardListFull');
      if (scope === 'week') {
        const current = (payload.rows || []).find((row) => row.isCurrent);
        const rank = $('.your-rank strong');
        if (rank && current) rank.textContent = `#${current.rank}`;
      }
      return true;
    } catch (error) {
      return false;
    }
  })();
  leaderboardInFlight.set(scope, request);
  request.finally(() => {
    if (leaderboardInFlight.get(scope) === request) leaderboardInFlight.delete(scope);
  });
  return request;
}

async function refreshAfterMutation({refreshAdmin = false} = {}) {
  const tasks = [
    loadRecentActivity({force: true}),
    loadDashboardSummary(),
    loadLeaderboard('week'),
  ];
  if (currentView === 'submissions') tasks.push(loadMySubmissions());
  if (refreshAdmin && currentView === 'admin') tasks.push(loadAdminQueue());
  await Promise.allSettled(tasks);
}

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
    if (!me.team) { window.location.href = '/team-select.html'; return; }
    applyRoleUi(me.role);
    ensureArenaAdminPanel(me.role);
    if (me.role === 'admin' || me.role === 'owner') loadTeamSettings();
    if (me.team?.name) { $('#teamName').textContent = me.team.name; const subtitle = $('.team-button-copy small'); if (subtitle) subtitle.textContent = me.team.code || '当前团队'; }
    if (Array.isArray(me.teams)) { const menu=$('#teamMenu'); if(menu){ menu.innerHTML=me.teams.map(t=>`<button type="button" data-team-id="${t.team_id}" data-team="${escapeHtml(t.team__name)}"><span class="team-avatar small">${escapeHtml((t.team__name||'').slice(0,1))}</span>${escapeHtml(t.team__name)}</button>`).join(''); $$('#teamMenu button').forEach(button=>button.addEventListener('click',async()=>{const response=await clubApi.request('/api/team/select',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({team_id:button.dataset.teamId})}); if(response.ok) location.reload(); else showToast('无权进入该团队');})); } }
    const profile = $('.profile-chip');
    if (profile) { const avatar = profile.querySelector('.profile-avatar'); const name = profile.querySelector('strong'); const role = profile.querySelector('small'); if (avatar) avatar.textContent = (me.name || '').slice(0, 1); if (name) name.textContent = me.name || '当前账号'; if (role) role.textContent = me.role === 'owner' ? '团队创建者' : me.role === 'admin' ? '团队管理员' : '团队成员'; }
    await Promise.allSettled([loadRecentActivity(), loadDashboardSummary(), loadLeaderboard('week')]);
  } catch (error) { showToast(error.message || '页面数据加载失败，请刷新重试'); }
}
async function loadTeamSettings() {
  try { const response = await clubApi.request('/api/admin/team-settings'); if (!response.ok) return; const payload = await response.json(); const mode = payload.visibility || 'team'; $$('[data-global-visibility]').forEach((item) => item.classList.toggle('active', item.dataset.globalVisibility === mode)); const saved = $('#settingsSaved'); if (saved) saved.textContent = `当前设置：${mode === 'team' ? '所有团队成员可查看' : '仅管理员可查看'}`; } catch (error) { showToast('团队设置加载失败'); }
}
async function loadArenaData() {
  const requestVersion = ++arenaRequestVersion;
  try {
    const response = await clubApi.request('/api/arena');
    if (requestVersion !== arenaRequestVersion) return;
    if (!response.ok) return;
    const arena = (await response.json()).arena;
    if (requestVersion !== arenaRequestVersion) return;
    const box = $('#arenaView .arena-empty');
    const banner = $('.arena-banner');
    if (arena) {
      if (box) box.innerHTML = `<div class="empty-icon star">✦</div><h2>${escapeHtml(arena.title)}</h2><p>${escapeHtml(arena.description || '挑战已开放')}</p><div class="arena-samples"><strong>样例</strong><pre>${escapeHtml(arena.samples || '管理员未填写样例')}</pre></div><p class="muted">${arena.has_judge_script ? '已配置测题脚本' : '等待管理员配置测题脚本'}</p><button class="primary-button" type="button" disabled>开始挑战（判题器即将开放）</button>`;
      if (banner) { $('.arena-copy h2', banner).textContent = arena.title; $('.arena-copy p', banner).textContent = arena.description || '当前擂台已开放'; $('.arena-state span:last-child', banner).textContent = '当前擂台已开放'; }
    } else {
      if (box) box.innerHTML = '<div class="empty-icon star">✦</div><h2>今日擂台暂未开放</h2><p>管理员没有指定当期擂台时，挑战入口会保持关闭。</p>';
      if (banner) { $('.arena-copy h2', banner).textContent = '今天的题，等你来破。'; $('.arena-copy p', banner).textContent = '管理员尚未发布今日擂台题目，发布后将在这里开放挑战。'; $('.arena-state span:last-child', banner).textContent = '今日擂台暂未开放'; }
    }
  } catch (error) {
    const box = $('#arenaView .arena-empty');
    if (box) box.innerHTML = '<div class="queue-empty">擂台加载失败，请刷新重试</div>';
  }
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
    const count = $('#membersView .date-chip');
    if (count) count.textContent = `${members.length} 位成员`;
    if (!members.length) {
      grid.innerHTML = '<div class="queue-empty">当前团队暂无成员数据</div>';
      return;
    }
    grid.innerHTML = members.map((member) => `<article class="member-card" data-member="${escapeHtml(member.name)}"><div class="member-card-head"><span class="member-avatar dark">${escapeHtml(member.name.slice(0,1))}</span><div><strong>${escapeHtml(member.name)}</strong><small>${member.role === 'owner' ? '团队创建者' : member.role === 'admin' ? '团队管理员' : '团队成员'}</small></div><span class="member-status">活跃</span></div><div class="member-card-stats"><div><span>本周提交</span><strong>${member.submissions} <small>次</small></strong></div><div><span>学期积分</span><strong>${member.score}</strong></div></div><button class="member-history-button" type="button" data-member-history="${member.id}">查看历史提交 <span>→</span></button></article>`).join('');
    $$('.member-history-button', grid).forEach((button) => button.addEventListener('click', () => openMemberHistory(button.dataset.memberHistory)));
  } catch (error) {
    grid.innerHTML = '<div class="queue-empty">成员列表加载失败，请检查网络连接</div>';
  }
}
if (demoMode) setupDemoPreview();
else { clearStaticPreview(); loadLiveData(); }
const historyModal = $('#memberHistoryModal');
let activeHistoryMemberId = null;
function openMemberHistory(key) {
  if (/^\d+$/.test(String(key))) { activeHistoryMemberId = Number(key); openLiveMemberHistory(Number(key)); return; }
  showToast('请从真实成员列表打开历史提交');
}
async function openLiveMemberHistory(memberId) {
  const requestVersion = ++historyRequestVersion;
  try {
    const week = $('#historyWeek').value;
    const response = await clubApi.request(`/api/members/${memberId}/history?week=${week}`);
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
      const reviewStatus = item.parts.some((part) => part.status === 'pending') ? 'pending' : item.parts.some((part) => part.status === 'approved') ? 'approved' : 'rejected';
      reviewData[key] = {name:item.member_name, initial:item.member_name.slice(0,1), time:new Date(item.submitted_at).toLocaleString('zh-CN'), logic:logic?.text || '未提交写题逻辑。', visibility:item.visibility || 'team', status:reviewStatus, submissionId:item.id, upload:proof?.upload, fileName:'通过截图'};
      const points = item.parts.reduce((sum, part) => sum + (part.points || 0), 0);
      const iconStatus = reviewStatus === 'approved' ? 'approved' : reviewStatus === 'rejected' ? 'pending' : 'pending';
      const icon = reviewStatus === 'approved' ? '✓' : reviewStatus === 'rejected' ? '!' : '◷';
      return `<div class="history-item"><div class="history-item-icon ${iconStatus}">${icon}</div><div><strong>第 ${item.week} 周提交</strong><small>${new Date(item.submitted_at).toLocaleString('zh-CN')}</small></div><span>${points} 分</span><button class="history-view" type="button" data-review="${key}">查看内容</button></div>`;
    }).join('') : '<div class="queue-empty">该周暂无提交记录</div>';
    $$('.history-view', $('#historyList')).forEach((button) => button.addEventListener('click', () => { closeMemberHistory(); openReview(button.dataset.review); }));
    $('#historyScore').textContent = `${submissions.reduce((total, item) => total + item.parts.reduce((sum, part) => sum + (part.points || 0), 0), 0)} 分`;
    $('#historyCount').textContent = `${submissions.length} 次`;
    const historyStatus = $('.history-summary strong.positive');
    if (historyStatus && payload.summary?.qualified !== null && payload.summary?.qualified !== undefined) {
      historyStatus.textContent = payload.summary.qualified ? '已达标' : '未达标';
      historyStatus.className = payload.summary.qualified ? 'positive' : 'pending-text';
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
  openReview(button.dataset.review);
}));

$('#memberSearch').addEventListener('input', (event) => {
  const query = event.target.value.trim().toLowerCase();
  $$('#membersGrid .member-card').forEach((card) => { card.style.display = !query || card.dataset.member.toLowerCase().includes(query) ? '' : 'none'; });
});

$$('[data-global-visibility]').forEach((button) => button.addEventListener('click', () => {
  const mode = button.dataset.globalVisibility;
  $$('[data-global-visibility]').forEach((item) => item.classList.toggle('active', item === button));
  const label = mode === 'team' ? '所有团队成员可查看' : '仅管理员可查看';
  $('#settingsSaved').textContent = `当前设置：${label}`;
  const note = $('#showcaseView .showcase-note');
  if (note) note.innerHTML = `<span class="status-dot"></span>${mode === 'team' ? '仅当前团队成员可见' : '当前仅管理员可见'}`;
  clubApi.request('/api/admin/team-settings', {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify({visibility:mode})}).then((response) => showToast(response.ok ? `已保存：${label}` : '保存失败，请确认管理员权限')).catch(() => showToast('保存失败，请检查网络'));
}));
