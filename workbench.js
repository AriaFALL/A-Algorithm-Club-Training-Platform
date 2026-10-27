const workbench$ = selector => document.querySelector(selector);
let workbenchProfile = null;
let workbenchVersion = 0;
let workbenchConfirmResolver = null;

document.querySelector('#adminView').innerHTML = `
  <div class="page-heading"><div><p class="kicker">团队管理</p><h1>管理工作台</h1><p class="muted" id="workbenchDescription"></p></div><button class="secondary-button" id="refreshReports">刷新工作台</button></div>
  <div class="workbench-scope panel" id="wbManagedScope" hidden><label>当前管理团队 <select id="wbManagedTeam" aria-label="当前管理团队"></select></label></div>
  <section class="panel workbench-panel" id="wbParserSection" hidden><div class="panel-heading"><div><p class="section-label">PROBLEM PARSER</p><h2>题目解析与 API 配置</h2></div></div>
    <form id="wbParserForm" class="workbench-form"><label>解析模式<select name="mode"><option value="auto">自动解析</option><option value="ai">AI解析</option><option value="smart">智能解析：自动失败后使用AI</option></select></label><label class="workbench-check"><input name="enabled" type="checkbox">启用 AI 调用</label><label>API 地址<input name="base_url" type="url" maxlength="500" placeholder="https://api.example.com/v1"></label><label>调用协议<select name="api_protocol"><option value="chat">Chat Completions（兼容模式）</option><option value="responses">Responses（启用联网搜索）</option></select></label><label>Model<input name="model" maxlength="200" placeholder="模型名称"></label><label>API Key<input name="api_key" type="password" autocomplete="new-password" maxlength="4096" placeholder="留空保留已保存的 Key"><small id="wbKeyHint"></small></label><label class="workbench-check"><input name="clear_key" type="checkbox">清除已保存的 Key</label><div class="workbench-form-actions"><button class="primary-button" type="submit">保存解析配置</button><button class="secondary-button" type="button" id="wbTestParser">测试已保存的 AI 配置</button></div></form><p class="muted workbench-hint">自动解析直接读取网页；AI解析只发送题目网址，所配置服务需支持联网；CPA/Codex 可选择 Responses 协议显式启用联网工具。已有题目不会重复解析。测试会发送一次示例题目请求。</p>
  </section>
  <section class="panel workbench-panel" id="wbPendingSection" hidden><div class="panel-heading"><div><p class="section-label">TITLE INBOX</p><h2>待处理题目名称</h2></div></div><div id="wbProblemQueue"></div><button class="secondary-button" id="wbProblemsMore" hidden>加载更多题目</button></section>
  <section class="workbench-panel" id="wbReportsSection"><div class="panel-heading"><div><p class="section-label">REPORTS</p><h2>举报处理</h2></div><span class="muted" id="wbReportScope"></span></div><div id="reviewList" class="solution-waterfall"></div><button id="reportsMore" class="secondary-button" hidden>加载更多举报</button></section>
  <section class="panel workbench-panel" id="wbTeamsSection" hidden><div class="panel-heading"><div><p class="section-label">TEAMS</p><h2>团队配置</h2></div></div>
    <details id="wbCreateSection" class="workbench-details" hidden><summary>创建团队 ＋</summary><form id="wbCreateTeamForm" class="workbench-form"><label>团队名称<input name="team_name" maxlength="80" required></label><label>团队码<input name="team_code" maxlength="32" required></label><label>加入密码<input name="join_password" type="password" minlength="8" maxlength="200" autocomplete="new-password" required></label><label>学期持续天数<input name="term_days" type="number" min="1" max="3660" value="120" required></label><label>每周提交要求<input name="min_submissions" type="number" min="0" max="100000" value="4" required></label><label>每周积分要求<input name="min_score" type="number" min="0" max="100000" value="10" required></label><label>截图积分<input name="screenshot_points" type="number" min="0" max="10000" value="1" required></label><label>题解积分<input name="logic_points" type="number" min="0" max="10000" value="1" required></label><label>Blog积分<input name="blog_points" type="number" min="0" max="10000" value="1" required></label><label class="workbench-check"><input name="require_both" type="checkbox" checked>提交次数和积分均需达标</label><div class="workbench-form-actions"><button class="primary-button" type="submit">创建团队</button></div></form></details>
    <div id="wbTeamGroups"></div>
  </section>`;

document.body.insertAdjacentHTML('beforeend', `<div class="modal-backdrop" id="wbConfirmModal" aria-hidden="true"><section class="modal" role="dialog" aria-modal="true" aria-labelledby="wbConfirmTitle"><div class="modal-header"><h2 id="wbConfirmTitle"></h2><button class="close-button" id="wbCancelConfirm" aria-label="取消操作">×</button></div><p id="wbConfirmText"></p><form id="wbConfirmForm"><label class="field-label" id="wbConfirmCodeField" hidden>输入团队码确认<input id="wbConfirmCode" autocomplete="off"></label><div class="modal-footer"><span class="muted" id="wbConfirmHint"></span><button class="primary-button" type="submit">确认操作</button></div></form></section></div>`);

function initWorkbench(me) {
  workbenchProfile = me;
  workbench$('#workbenchDescription').textContent = me.site_admin ? '管理题目解析、举报与团队配置。' : '处理当前管理团队的举报与题名。';
  ['wbParserSection','wbCreateSection','wbTeamsSection'].forEach(id => { workbench$('#'+id).hidden = !me.site_admin; });
  if (!me.can_manage_current) workbench$('#wbPendingSection').hidden = true;
  workbench$('#wbManagedScope').hidden = me.site_admin || !me.is_team_manager;
  if (me.is_team_manager && !me.site_admin) {
    workbench$('#wbManagedTeam').innerHTML = (!me.can_manage_current ? '<option value="">请选择所管理的团队</option>' : '') + me.managed_teams.map(t => `<option value="${t.team_id}">${escapeHtml(t.team__name)}</option>`).join('');
    workbench$('#wbManagedTeam').value = me.can_manage_current && me.team ? String(me.team.id) : '';
  }
  workbench$('#wbReportScope').textContent = me.site_admin ? '全站全部团队' : me.team?.name || '';
}

async function loadWorkbench() {
  const version = ++workbenchVersion;
  try {
    const me = await communityRequest('/api/me');
    if (version !== workbenchVersion || currentView !== 'admin') return;
    initWorkbench(me);
    if (!me.site_admin && !me.is_team_manager) { applyRoleUi('member'); if (!me.team) location.href='/team-select.html'; else setView('dashboard'); showToast('管理权限已取消'); return; }
    if (!me.can_manage_current) {
      workbench$('#reviewList').innerHTML = '<div class="queue-empty">请先切换到你管理的团队。</div>';
      workbench$('#wbTeamGroups').innerHTML = '';
      workbench$('#reportsMore').hidden = true;
      return;
    }
    const tasks = [loadAdminQueue(), loadPendingProblems(1, version)];
    if (me.site_admin) tasks.push(loadWorkbenchTeams(version), loadParserConfig(version));
    const results = await Promise.allSettled(tasks);
    for (const result of results) if (result.status === 'rejected') showToast(result.reason.message || '工作台加载失败');
  } catch(error) { showToast(error.message); }
}

async function loadWorkbenchTeams(version = workbenchVersion) {
  if (!workbenchProfile?.site_admin) return;
  const data = await communityRequest('/api/management');
  if (version !== workbenchVersion || currentView !== 'admin') return;
  workbench$('#wbTeamGroups').innerHTML = data.teams.map(team => `<article class="workbench-team" data-team="${team.id}"><div class="workbench-team-heading"><div><h3>${escapeHtml(team.name)}</h3><small>${escapeHtml(team.code)}</small></div><div class="workbench-row-actions"><button class="text-button" data-team-config="${team.id}">团队配置</button><button class="text-button danger" data-delete-team="${team.id}" data-code="${escapeHtml(team.code)}" data-name="${escapeHtml(team.name)}">删除团队</button></div></div><div class="workbench-team-settings" id="wbTeamSettings${team.id}" hidden></div></article>`).join('') || '<div class="queue-empty">暂无团队，可先创建团队。</div>';
}

async function loadParserConfig(version = workbenchVersion) {
  const data = await communityRequest('/api/management/parser');
  if (version !== workbenchVersion) return;
  const form = workbench$('#wbParserForm');
  for (const name of ['mode','base_url','model','api_protocol']) form.elements[name].value = data[name];
  form.elements.enabled.checked = data.enabled;
  form.elements.api_key.value = '';
  form.elements.clear_key.checked = false;
  workbench$('#wbKeyHint').textContent = data.has_key ? '已保存 ••••••••；留空保留原值。' : '尚未保存 API Key';
}

async function loadPendingProblems(page = 1, version = workbenchVersion) {
  const data = await communityRequest(`/api/management/problems?page=${page}`);
  if (version !== workbenchVersion || !workbenchProfile?.can_manage_current) return;
  if (page === 1) workbench$('#wbProblemQueue').innerHTML = '';
  workbench$('#wbPendingSection').hidden = page === 1 && !data.problems.length;
  const status = {pending:'待解析',running:'解析中',failed:'待处理'};
  workbench$('#wbProblemQueue').insertAdjacentHTML('beforeend', data.problems.map(p => `<article class="workbench-problem"><a href="${escapeHtml(p.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(p.url)}</a><p class="muted">${status[p.status]}${p.error ? ' · ' + escapeHtml(p.error) : ''}</p><form class="workbench-inline-form" data-problem-title="${p.id}"><label>题目名称<input name="title" required maxlength="200" value="${escapeHtml(p.title)}" placeholder="填写正确题目名称"></label><button class="secondary-button" type="submit">保存题名</button><select aria-label="重新解析模式" data-retry-mode="${p.id}"><option value="auto">自动解析</option><option value="ai">AI解析</option><option value="smart" selected>智能解析</option></select><button class="text-button" type="button" data-retry-problem="${p.id}">重新解析</button><button class="text-button danger" type="button" data-remove-problem="${p.id}">删除任务</button></form></article>`).join(''));
  workbench$('#wbProblemsMore').hidden = !data.next;
  workbench$('#wbProblemsMore').onclick = () => loadPendingProblems(data.next).catch(error => showToast(error.message));
}

function confirmWorkbench(title, text, code = null, hint = null) {
  workbench$('#wbConfirmTitle').textContent = title;
  workbench$('#wbConfirmText').textContent = text;
  workbench$('#wbConfirmCodeField').hidden = !code;
  workbench$('#wbConfirmCode').required = Boolean(code);
  workbench$('#wbConfirmCode').value = '';
  workbench$('#wbConfirmHint').textContent = hint || (code ? `请输入 ${code} 确认，关联训练数据也会删除。` : '历史记录会保留，成员将失去该团队访问权限。');
  workbench$('#wbConfirmModal').classList.add('open'); workbench$('#wbConfirmModal').setAttribute('aria-hidden','false');
  (code ? workbench$('#wbConfirmCode') : workbench$('#wbConfirmForm button')).focus();
  return new Promise(resolve => { workbenchConfirmResolver = resolve; });
}

function finishWorkbenchConfirm(value = null) {
  workbench$('#wbConfirmModal').classList.remove('open'); workbench$('#wbConfirmModal').setAttribute('aria-hidden','true');
  workbenchConfirmResolver?.(value); workbenchConfirmResolver = null;
}

function formNumbers(form, keys) {
  const data = Object.fromEntries(new FormData(form));
  keys.forEach(k => { data[k] = Number(data[k]); });
  data.require_both = form.elements.require_both.checked;
  return data;
}
const workbenchJSON = (method, data) => ({method, headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)});

workbench$('#wbConfirmForm').addEventListener('submit', event => { event.preventDefault(); finishWorkbenchConfirm(workbench$('#wbConfirmCode').required ? workbench$('#wbConfirmCode').value : true); });
workbench$('#wbCancelConfirm').onclick = () => finishWorkbenchConfirm();
document.addEventListener('keydown', event => { if (event.key === 'Escape' && workbenchConfirmResolver) { event.stopImmediatePropagation(); finishWorkbenchConfirm(); } }, true);
workbench$('#wbManagedTeam').addEventListener('change', async event => {
  if (!event.target.value) return;
  try { await communityRequest('/api/team/select', workbenchJSON('POST', {team_id:Number(event.target.value)})); location.href='/?view=admin'; }
  catch(error) { showToast(error.message); }
});
workbench$('#wbParserForm').addEventListener('submit', async event => {
  event.preventDefault(); const button = event.submitter; button.disabled = true;
  const form = event.target; const data = Object.fromEntries(new FormData(form));
  data.enabled = form.elements.enabled.checked; data.clear_key = form.elements.clear_key.checked;
  try { await communityRequest('/api/management/parser', workbenchJSON('PUT', data)); await loadParserConfig(); showToast('解析配置已保存'); }
  catch(error) { showToast(error.message); } finally { button.disabled = false; }
});
const parserTestResult = document.createElement('p');
parserTestResult.id = 'wbParserTestResult'; parserTestResult.className = 'workbench-hint'; parserTestResult.setAttribute('role','status'); parserTestResult.hidden = true;
workbench$('#wbParserForm').after(parserTestResult);
workbench$('#wbTestParser').addEventListener('click', async event => {
  event.target.disabled = true;
  parserTestResult.hidden = false; parserTestResult.textContent = '正在测试连接与样例题名读取…';
  try { const data = await communityRequest('/api/management/parser/test', {method:'POST'}); parserTestResult.textContent = data.warning || ('AI连接成功，样例题名：' + data.title); showToast(parserTestResult.textContent); }
  catch(error) { parserTestResult.textContent = error.message; showToast(error.message); } finally { event.target.disabled = false; }
});
workbench$('#wbCreateTeamForm').addEventListener('submit', async event => {
  event.preventDefault(); const button = event.submitter; button.disabled = true;
  try {
    const data = formNumbers(event.target,['term_days','min_submissions','min_score','screenshot_points','logic_points','blog_points']);
    await communityRequest('/api/auth/create-team',workbenchJSON('POST',data));
    location.href='/?view=admin';
  } catch(error) { showToast(error.message); button.disabled = false; }
});
async function openTeamSettings(id, force = false) {
  const host = workbench$('#wbTeamSettings'+id);
  if (!host.hidden && !force) { host.hidden = true; return; }
  const data = await communityRequest(`/api/management/teams/${id}/settings`);
  const semester = data.semester;
  const numeric = [['min_submissions','每周提交要求'],['min_score','每周积分要求'],['screenshot_points','截图积分'],['logic_points','题解积分'],['blog_points','Blog积分']];
  host.innerHTML = cleanupScheduleMarkup(data.cleanup, id, Boolean(semester)) + `<form class="workbench-form" data-team-settings-form="${id}"><label>团队名称<input name="name" required maxlength="80" value="${escapeHtml(data.name)}"></label><label>团队码<input name="code" required maxlength="32" value="${escapeHtml(data.code)}"></label><label>新加入密码<input name="join_password" type="password" minlength="8" maxlength="200" autocomplete="new-password" placeholder="留空保留原密码"></label>${semester ? numeric.map(([key,label]) => `<label>${label}<input name="${key}" type="number" min="0" max="100000" required value="${semester[key]}"></label>`).join('') + `<label class="workbench-check"><input name="require_both" type="checkbox" ${semester.require_both ? 'checked' : ''}>提交次数和积分均需达标</label>` : '<p class="muted">当前团队没有活动学期。</p>'}<div class="workbench-form-actions"><button class="primary-button" type="submit">保存团队配置</button></div></form>`;
  host.hidden = false;
}

workbench$('#adminView').addEventListener('submit', async event => {
  const form = event.target;
  if (!form.dataset.problemTitle && !form.dataset.teamSettingsForm) return;
  event.preventDefault(); const button = event.submitter; button.disabled = true;
  try {
    if (form.dataset.problemTitle) {
      await communityRequest(`/api/management/problems/${form.dataset.problemTitle}`,workbenchJSON('PATCH',{title:form.elements.title.value}));
      await loadPendingProblems(); showToast('题名已保存');
    } else {
      const data = Object.fromEntries(new FormData(form));
      ['min_submissions','min_score','screenshot_points','logic_points','blog_points'].forEach(k => { if (k in data) data[k]=Number(data[k]); });
      data.require_both = form.elements.require_both?.checked || false;
      await communityRequest(`/api/management/teams/${form.dataset.teamSettingsForm}/settings`,workbenchJSON('PUT',data));
      await loadWorkbenchTeams(); await loadLiveData(); showToast('团队配置已保存');
    }
  } catch(error) { showToast(error.message); } finally { button.disabled=false; }
});

workbench$('#adminView').addEventListener('click', async event => {
  const button = event.target.closest('button'); if (!button) return;
  const data = button.dataset;
  if (!data.deleteTeam && !data.teamConfig && !data.retryProblem && !data.removeProblem && !data.scheduleCleanup && !data.cancelCleanup) return;
  button.disabled = true;
  try {
    if (data.scheduleCleanup || data.cancelCleanup) {
      const id = data.scheduleCleanup || data.cancelCleanup;
      if (data.cancelCleanup) {
        await communityRequest(`/api/management/teams/${id}/cleanup`, {method:'DELETE'});
        showToast('已撤销清理计划，可重新选择时间');
      } else {
        const input = workbench$('#wbCleanupTime'+id);
        if (!input.value || !input.reportValidity()) return;
        await communityRequest(`/api/management/teams/${id}/cleanup`, workbenchJSON('POST', {cleanup_time:input.value}));
        showToast('清理时间已设置，将在该时间7天后执行');
      }
      await openTeamSettings(id, true);
    } else if (data.deleteTeam) {
      const confirmation = await confirmWorkbench('删除团队',`将删除“${data.name}”及其关联训练数据。`,data.code);
      if (!confirmation) return;
      await communityRequest(`/api/management/teams/${data.deleteTeam}`,workbenchJSON('DELETE',{confirmation}));
      location.href='/?view=admin';
    } else if (data.removeProblem) {
      if (!await confirmWorkbench('移除题名任务', '将从待处理队列移除此命名任务。', null, '原题目与提交记录会保留；没有题名时仍显示题目链接。')) return;
      await communityRequest(`/api/management/problems/${data.removeProblem}`, {method:'DELETE'});
      await loadPendingProblems(); showToast('命名任务已移除');
    } else if (data.teamConfig) await openTeamSettings(data.teamConfig);
    else {
      await communityRequest(`/api/management/problems/${data.retryProblem}/retry`,workbenchJSON('POST',{mode:workbench$(`[data-retry-mode="${data.retryProblem}"]`).value}));
      await loadPendingProblems(); showToast('已加入解析队列');
    }
  } catch(error) { showToast(error.message); } finally { button.disabled = false; }
});

workbench$('#membersGrid').addEventListener('click', async event => {
  const button = event.target.closest('button');
  if (!button || (!button.dataset.memberKick && !button.dataset.memberRole)) return;
  const data = button.dataset;
  button.disabled = true;
  try {
    if (data.memberKick) {
      if (!await confirmWorkbench('踢出用户', `将“${data.name}”移出“${data.teamName}”？`)) return;
      await communityRequest(`/api/management/teams/${data.teamId}/members/${data.memberKick}`, workbenchJSON('DELETE', {confirmation:data.name}));
      await loadMembersLive();
      await refreshAfterMutation();
      showToast('已将用户踢出当前团队');
    } else {
      await communityRequest('/api/management/managers', workbenchJSON('POST', {team_id:Number(data.teamId), account:data.account, role:data.memberRole}));
      await loadMembersLive();
      showToast(data.memberRole === 'admin' ? '已设置团队管理' : '已取消团队管理');
    }
  } catch(error) { showToast(error.message); }
  finally { button.disabled = false; }
});

function cleanupScheduleMarkup(schedule, id, hasSemester) {
  if (!hasSemester) return '';
  if (schedule) {
    const selected = new Date(schedule.time).toLocaleString('zh-CN', {timeZone:'Asia/Shanghai'});
    const execute = new Date(schedule.execute_at).toLocaleString('zh-CN', {timeZone:'Asia/Shanghai'});
    return `<section class="workbench-cleanup"><h4 data-cleanup-deadline="${escapeHtml(schedule.execute_at)}">${schedule.days_left}天后清理本学期所有内容。</h4><p class="muted">清理时间：${escapeHtml(selected)}；实际执行：${escapeHtml(execute)}（北京时间）。${schedule.in_grace_period ? '当前处于7天缓冲期。' : ''}</p><button type="button" class="secondary-button" data-cancel-cleanup="${id}">撤销并重设清理时间</button></section>`;
  }
  const minimum = new Date().toLocaleString('sv-SE',{timeZone:'Asia/Shanghai',hour12:false}).replace(' ','T').slice(0,16);
  return `<section class="workbench-cleanup"><h4>清理时间</h4><label class="field-label">清理时间（北京时间）<input id="wbCleanupTime${id}" type="datetime-local" min="${minimum}" required aria-label="清理时间（北京时间）"></label><p class="muted">到达所选时间后保留7天，随后清理本学期提交及材料，保留原有汇总统计。未设置时间时不自动清理。</p><button type="button" class="secondary-button" data-schedule-cleanup="${id}">设置清理时间</button></section>`;
}
setInterval(() => {
  document.querySelectorAll('[data-cleanup-deadline]').forEach(heading => {
    const days = Math.max(0, Math.ceil((new Date(heading.dataset.cleanupDeadline).getTime() - Date.now()) / 86400000));
    heading.textContent = `${days}天后清理本学期所有内容。`;
  });
}, 60000);
