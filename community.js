let galleryWeek = '';
let galleryWeekControl = null;

function updateGalleryWeeks(data) {
  const select = $('#galleryWeek');
  const weeks = data.weeks.map(week => ({value: String(week.id), text: week.label, current: String(week.id) === String(data.current_week)}));
  if (!data.week) weeks.unshift({value: '', text: '暂无已开始的周次'});
  if (!galleryWeekControl) {
    select.innerHTML = weeks.map(week => `<option value="${escapeHtml(week.value)}">${escapeHtml(week.text)}</option>`).join('');
    select.value = galleryWeek;
    if (window.TomSelect) {
      galleryWeekControl = new TomSelect(select, {
        options: weeks,
        create: false, maxItems: 1, maxOptions: null, allowEmptyOption: true,
        searchField: ['text'], sortField: [{field: '$order'}],
        plugins: ['dropdown_input'], placeholder: '选择展示周次',
        render: {
          option(item, escape) {
            const match = item.text.match(/^(.*?)\s*·\s*(第\s*\d+\s*周)$/);
            return `<div class="week-option${item.current ? ' is-current-week' : ''}"><span>${escape(match ? match[1] : item.text)}</span><span class="week-option-label">${item.current ? '<small class="current-week-tag">本周</small>' : ''}${match ? `<strong>${escape(match[2])}</strong>` : ''}</span></div>`;
          },
          no_results() { return '<div class="no-results">未找到匹配的周次</div>'; }
        },
        onInitialize() { this.control.setAttribute('aria-label', '选择展示周次'); },
        onDropdownOpen() {
          const input = this.dropdown.querySelector('input');
          if (input) { input.placeholder = '搜索学期或周次…'; input.setAttribute('aria-label', '搜索学期或周次'); }
        }
      });
    }
  } else {
    galleryWeekControl.clear(true);
    galleryWeekControl.clearOptions();
    galleryWeekControl.addOptions(weeks);
    galleryWeekControl.setValue(galleryWeek, true);
    galleryWeekControl.refreshOptions(false);
  }
  return weeks.find(week => week.value === galleryWeek)?.text;
}
let galleryProblem = null;
let galleryRequest = 0;
let reportRequest = 0;
let resubmitting = null;
let editingSubmission = null;
const ownRecords = new Map();
let rejectionResolver = null;

function rejectionNote() {
  $('#rejectionReason').value = '';
  $('#reportDecisionModal').classList.add('open');
  $('#reportDecisionModal').setAttribute('aria-hidden', 'false');
  $('#rejectionReason').focus();
  return new Promise(resolve => { rejectionResolver = resolve; });
}

function finishRejection(value = null) {
  $('#reportDecisionModal').classList.remove('open');
  $('#reportDecisionModal').setAttribute('aria-hidden', 'true');
  rejectionResolver?.(value);
  rejectionResolver = null;
}

async function communityRequest(url, options) {
  const response = await clubApi.request(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.error || '加载失败，请重试');
    error.status = response.status;
    throw error;
  }
  return data;
}

function submissionCard(item, moderation = false) {
  const proof = item.parts.find(p => p.kind === 'proof');
  const logic = item.parts.find(p => p.kind === 'logic');
  const blog = item.parts.find(p => p.kind === 'blog');
  return `<article class="solution-card panel" data-submission="${item.id}">
    <div class="member-line">${memberAvatar(item.member_id,item.member_name)}<div><strong>${escapeHtml(item.member_name)}</strong><small>${escapeHtml(item.semester_name)} · 第${item.week}周<br>归属日期：${escapeHtml(item.record_date || '')}<br>上传：${new Date(item.submitted_at).toLocaleString('zh-CN')}</small></div></div>
    ${moderation ? `<h3>${escapeHtml(item.problem_title)}</h3><small>${escapeHtml(item.team_name || '')}</small><p class="muted">${item.reports} 人举报 · 版本 ${item.version}</p>` : ''}
    ${blog?.text ? `<div class="shared-content blog-content"><strong>Blog</strong><div class="blog-rendered" data-markdown="${escapeHtml(blog.text)}"></div></div>` : ''}
    <div class="solution-attachments">
    ${proof?.upload ? `<button class="solution-proof" data-zoom="${escapeHtml(proof.upload)}" aria-label="放大通过截图"><img loading="lazy" src="${escapeHtml(proof.upload)}" alt="${escapeHtml(item.member_name)}的通过截图"><span>通过截图 · 点击放大</span></button>` : ''}
    ${logic?.text ? `<div class="shared-content"><strong>写题逻辑</strong><p class="solution-text">${escapeHtml(logic.text)}</p></div>` : ''}
    </div>
    <div class="solution-actions">${moderation ? item.can_resolve ? `<button class="secondary-button" data-resolve="dismiss" data-id="${item.id}" data-version="${item.version}">驳回举报</button><button class="secondary-button" data-resolve="reject" data-id="${item.id}" data-version="${item.version}">整条退回</button>` : '<span class="muted">请其他管理员处理自己的记录</span>' : `<button class="secondary-button ${item.liked ? 'is-liked' : ''}" data-like="${item.id}" data-liked="${item.liked}" aria-pressed="${item.liked}" ${item.own ? 'disabled' : ''}>赞 ${item.likes}</button>${item.can_tip ? `<button class="secondary-button" data-tip="${item.id}">打赏</button>` : ""}<button class="text-button" data-report="${item.id}" ${item.own || item.reported ? 'disabled' : ''}>${item.reported ? '已举报' : '举报'}</button>${item.can_reject ? `<button class="text-button" data-direct-reject="${item.id}" data-version="${item.version}">驳回</button>` : ''}`}</div>
  </article>`;
}

async function loadShowcase(page = 1) {
  galleryProblem = null;
  const version = ++galleryRequest;
  const host = $('#showcaseGrid');
  const more = $('#galleryMore');
  $('#problemBack').hidden = true;
  $('#galleryWeekPicker').hidden = false;
  $('#problemHeading').textContent = '本周题目';
  $('#problemOriginal').hidden = true;
  if (page === 1) host.innerHTML = '<div class="queue-empty">正在加载题目…</div>';
  more.hidden = true;
  host.className = 'problem-list';
  try {
    const data = await communityRequest(`/api/showcase?page=${page}${galleryWeek ? `&week=${galleryWeek}` : ''}`);
    if (version !== galleryRequest) return;
    galleryWeek = data.week ? String(data.week) : '';
    const weekLabel = updateGalleryWeeks(data);
    $('#problemHeading').textContent = data.week ? weekLabel || '题目列表' : '题目列表';
    const html = data.problems.map(p => `<button class="problem-row panel" data-problem="${p.id}"><span><strong>${escapeHtml(p.title)}</strong><small>${p.count} 个题解：${p.members.map(escapeHtml).join('　')}</small></span><span class="problem-arrow">点击查看 →</span></button>`).join('');
    if (page === 1) host.innerHTML = html || '<div class="queue-empty">该周暂无提交，完成第一份题解吧。</div>';
    else host.insertAdjacentHTML('beforeend', html);
    more.hidden = !data.next;
    more.onclick = () => loadShowcase(data.next);
  } catch (error) { if (version === galleryRequest) host.innerHTML = `<div class="queue-empty">${escapeHtml(error.message)}</div>`; }
}

function appendSubmissionDays(host, submissions) {
  const groups = new Map([...host.querySelectorAll('.submission-day')].map(group => [group.dataset.date, group]));
  const today = new Intl.DateTimeFormat('en-CA', {timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit'}).format(new Date());
  const dateFormat = new Intl.DateTimeFormat('zh-CN', {timeZone: 'Asia/Shanghai', year: 'numeric', month: 'long', day: 'numeric', weekday: 'short'});
  for (const item of submissions) {
    const day = item.record_date;
    let group = groups.get(day);
    if (!group) {
      group = document.createElement('section');
      group.className = 'submission-day';
      group.dataset.date = day;
      const heading = document.createElement('h2');
      heading.className = 'submission-day-heading';
      heading.textContent = `${day === today ? '今天 · ' : ''}${dateFormat.format(new Date(`${day}T12:00:00+08:00`))}`;
      const cards = document.createElement('div');
      cards.className = 'solution-waterfall';
      group.append(heading, cards);
      host.append(group);
      groups.set(day, group);
    }
    group.querySelector('.solution-waterfall').insertAdjacentHTML('beforeend', submissionCard(item));
  }
}

async function openProblem(id, page = 1) {
  galleryProblem = id;
  const version = ++galleryRequest;
  const host = $('#showcaseGrid');
  const more = $('#galleryMore');
  $('#problemBack').hidden = false;
  $('#galleryWeekPicker').hidden = true;
  $('#problemOriginal').hidden = true;
  $('#problemOriginal').removeAttribute('href');
  host.className = 'submission-days';
  if (page === 1) host.innerHTML = '<div class="queue-empty">正在加载全部历史题解…</div>';
  more.hidden = true;
  try {
    const data = await communityRequest(`/api/problems/${id}/submissions?page=${page}`);
    if (version !== galleryRequest) return;
    $('#problemHeading').textContent = data.problem.title;
    const link = $('#problemOriginal');
    link.hidden = false; link.href = data.problem.url;
    if (page === 1) host.replaceChildren();
    appendSubmissionDays(host, data.submissions);

    renderSubmissionBlogs(host);

    more.hidden = !data.next;
    more.onclick = () => openProblem(id, data.next);
  } catch (error) {
    if (version !== galleryRequest) return;
    if (error.status === 404) { await loadShowcase(); return; }
    host.innerHTML = `<div class="queue-empty">${escapeHtml(error.message)}</div>`;
  }
}

async function loadAdminQueue({append = false, page = 1} = {}) {
  if (!canManage || currentView !== 'admin') return;
  const version = ++reportRequest;
  const host = $('#reviewList');
  try {
    const data = await communityRequest(`/api/admin/reports?page=${page}`);
    if (version !== reportRequest || currentView !== 'admin') return;
    const html = data.submissions.map(item => submissionCard(item, true)).join('');
    if (!append) host.innerHTML = html || '<div class="queue-empty">当前没有待处理举报</div>';
    else host.insertAdjacentHTML('beforeend', html);
    renderSubmissionBlogs(host);
    const more = $('#reportsMore'); more.hidden = !data.next;
    more.onclick = () => loadAdminQueue({append: true, page: data.next});
  } catch (error) { if (version === reportRequest) host.innerHTML = `<div class="queue-empty">${escapeHtml(error.message)}</div>`; }
}

function stopAdminQueuePolling() { reportRequest++; }
function startAdminQueuePolling() { loadWorkbench(); }

function beginResubmit(id) {
  const record = ownRecords.get(Number(id));
  if (!record) return;
  openModal(true);
  resubmitting = record.id;
  $('#submissionForm').dataset.weekId = record.week_id;
  $('#submissionForm').dataset.recordDate = record.record_date;
  $('.form-note span').textContent = `记录日期：${record.record_date}`;
  $('#problemUrl').value = record.problem_url;
  $('#logicText').value = record.parts.find(p => p.kind === 'logic')?.text || '';
  const blogPart = record.parts.find(p => p.kind === 'blog');
  if (typeof setBlogEditorContent === 'function' && blogPart?.text) {
    setBlogEditorContent(blogPart.text);
  }
  $('#modalTitle').textContent = '修改并重新提交';
}

document.addEventListener('DOMContentLoaded', () => {
  $('#galleryWeek').addEventListener('change', event => { galleryWeek = event.target.value; loadShowcase(); });
  $('#problemBack').addEventListener('click', () => loadShowcase());
  $('#refreshReports').addEventListener('click', () => loadWorkbench());
  $('#closeReportDecision').addEventListener('click', () => finishRejection());
  $('#reportDecisionForm').addEventListener('submit', event => {
    event.preventDefault();
    const note = $('#rejectionReason').value.trim();
    if (note) finishRejection(note);
  });
});

document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && rejectionResolver) { event.stopImmediatePropagation(); finishRejection(); }
}, true);

document.addEventListener('click', async event => {
  const button = event.target.closest('button');
  if (!button) return;
  if (button.dataset.problem) { openProblem(button.dataset.problem); return; }
  if (button.dataset.resubmit) { beginResubmit(button.dataset.resubmit); return; }
  if (button.dataset.zoom) {
    $('#lightboxImage').src = button.dataset.zoom;
    $('#imageLightbox').classList.add('open');
    $('#imageLightbox').setAttribute('aria-hidden', 'false'); return;
  }
  if(button.dataset.tip){openTipDialog(button.dataset.tip);return;}
  if (!button.dataset.like && !button.dataset.report && !button.dataset.resolve && !button.dataset.directReject) return;
  let note = '';
  if (button.dataset.resolve === 'reject' || button.dataset.directReject) {
    note = await rejectionNote();
    if (!note) return;
  }
  button.disabled = true;
  try {
    if (button.dataset.like) {
      const data = await communityRequest(`/api/submissions/${button.dataset.like}/like`, {method: button.dataset.liked === 'true' ? 'DELETE' : 'PUT'});
      button.dataset.liked = String(data.liked); button.textContent = `赞 ${data.likes}`;
      button.classList.toggle('is-liked', data.liked); button.setAttribute('aria-pressed', String(data.liked));
    } else if (button.dataset.report) {
      await communityRequest(`/api/submissions/${button.dataset.report}/report`, {method: 'POST'});
      button.textContent = '已举报'; button.dataset.done = 'true'; showToast('举报已交由管理员处理');
    } else if (button.dataset.directReject) {
      await communityRequest(`/api/submissions/${button.dataset.directReject}/reject`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({note,version:Number(button.dataset.version)})});
      showToast('已驳回，积分已撤销');
      if (galleryProblem) await openProblem(galleryProblem);
      await refreshAfterMutation();
    } else {
      await communityRequest(`/api/admin/reports/${button.dataset.id}/resolve`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({action:button.dataset.resolve, note, version:Number(button.dataset.version)})});
      showToast(button.dataset.resolve === 'reject' ? '已退回，积分已撤销' : '已驳回举报');
      await loadWorkbench(); await refreshAfterMutation();
    }
  } catch (error) { showToast(error.message); }
  finally { if (button.dataset.done !== 'true') button.disabled = false; }
});

// Viewing uses the editor's stored Markdown; only the rendered output is filtered.
function renderSubmissionBlog(element, markdown) {
  const source = String(markdown || '');
  if (typeof marked === 'undefined') { element.textContent = source; return; }
  try {
    const template = document.createElement('template');
    template.innerHTML = marked.parse(source);
    const tags = new Set(['P','BR','HR','H1','H2','H3','H4','H5','H6','STRONG','EM','DEL','S','B','I','U','BLOCKQUOTE','PRE','CODE','UL','OL','LI','TABLE','THEAD','TBODY','TR','TH','TD','A','IMG','DETAILS','SUMMARY','DIV','SPAN','SUP','SUB']);
    const blocked = new Set(['SCRIPT','STYLE','IFRAME','OBJECT','EMBED','SVG','MATH','TEMPLATE','FORM','INPUT','BUTTON','LINK','META','BASE']);
    template.content.querySelectorAll('*').forEach(node => {
      if (blocked.has(node.tagName)) { node.remove(); return; }
      if (!tags.has(node.tagName)) { node.replaceWith(...node.childNodes); return; }
      const href = node.getAttribute('href');
      const src = node.getAttribute('src');
      const alt = node.getAttribute('alt');
      const title = node.getAttribute('title');
      for (const attr of [...node.attributes]) node.removeAttribute(attr.name);
      if (title) node.setAttribute('title', title);
      const safeUrl = (value, image = false) => {
        if (!value || /[\u0000-\u001f\u007f]/.test(value)) return null;
        try {
          const url = new URL(value, location.href);
          return (image ? ['http:', 'https:'] : ['http:', 'https:', 'mailto:']).includes(url.protocol) ? url.href : null;
        } catch { return null; }
      };
      if (node.tagName === 'A' && safeUrl(href)) {
        node.href = safeUrl(href); node.target = '_blank'; node.rel = 'noopener noreferrer';
      }
      if (node.tagName === 'IMG') {
        if (!safeUrl(src, true)) { node.remove(); return; }
        node.src = safeUrl(src, true); node.alt = alt || ''; node.loading = 'lazy';
      }
    });
    element.replaceChildren(template.content);
    if (typeof renderMathInElement !== 'undefined') {
      renderMathInElement(element, {delimiters:[{left:'$$',right:'$$',display:true},{left:'$',right:'$',display:false},{left:'\\[',right:'\\]',display:true},{left:'\\(',right:'\\)',display:false}],throwOnError:false,trust:false});
    }
  } catch { element.textContent = source; }
}

function renderSubmissionBlogs(root) {
  root.querySelectorAll('.blog-rendered[data-markdown]').forEach(element => renderSubmissionBlog(element, element.dataset.markdown));
}

function editOwnSubmission(id) {
  const record = ownRecords.get(Number(id));
  if (!record?.can_edit) { showToast('该记录已截止或学期已归档'); return; }
  closeReview();
  beginResubmit(id);
  editingSubmission = Number(id);
  resubmitting = null;
  $('#proofImage').required = false;
  $('.upload-box strong').textContent = '保留原截图，点击可更换';
  $('#proofHint').textContent = '未选择新图片时保留原截图';
  $('#modalTitle').textContent = '编辑提交记录';
}

function openTipDialog(id){
 const dialog=document.createElement('dialog');dialog.className='contest-reward-summary';
 dialog.innerHTML='<h2>打赏这条提交</h2><form><label>RBC Coins 数量<input name="amount" type="number" min="1" max="2147483647" step="1" required autofocus style="display:block;width:100%;padding:12px;margin:12px 0"></label><p>打赏将从你的余额扣除，并全额转给提交者。</p><p role="status"></p><button type="button" class="secondary-button">取消</button> <button type="submit" class="primary-button">确认打赏</button></form>';
 const token=clubApi.requestId();let pending=false;
 dialog.querySelector('button[type=button]').onclick=()=>dialog.close();
 dialog.addEventListener('cancel',event=>{if(pending)event.preventDefault();});dialog.addEventListener('close',()=>dialog.remove());
 dialog.querySelector('form').onsubmit=async event=>{
  event.preventDefault();if(pending)return;const form=event.target,amount=Number(form.elements.amount.value);
  if(!Number.isSafeInteger(amount)||amount<=0)return;pending=true;form.querySelectorAll('button').forEach(b=>b.disabled=true);
  try{const result=await communityRequest(`/api/submissions/${id}/tip`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({amount,request_id:token})});dialog.close();await window.CurrencyModule?.init();showToast(`打赏成功：${result.amount} RBC Coins`);}catch(error){form.querySelector('[role=status]').textContent=error.message;}finally{pending=false;form.querySelectorAll('button').forEach(b=>b.disabled=false);}
 };
 document.body.append(dialog);dialog.showModal();
}
