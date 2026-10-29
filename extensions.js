(() => {
  const root = document.getElementById('extensionsView');
  const escape = value => String(value || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let items = [];
  async function api(url, options) {
    const response = await clubApi.request(url, options);
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || '操作失败，请重试');
    return payload;
  }
  async function load() {
    root.innerHTML = '<p role="status">正在加载资源…</p>';
    try {
      const result = await api('/api/extensions'); items = result.items;
      root.innerHTML = `<section class="page-heading"><div><p class="kicker">EXPLORE & LEARN</p><h1>拓展</h1><p class="muted">收藏好工具，发现新知识。</p></div>${result.can_manage ? '<button class="primary-button" id="extensionAdd">＋ 添加资源</button>' : ''}</section><div class="extension-wall">${items.map(item => `<article class="extension-tile"><a class="extension-link" href="${escape(item.href)}" ${item.kind === 'link' ? 'target="_blank" rel="noopener noreferrer"' : 'download'} aria-label="${escape(item.title)} · ${item.kind === 'file' ? '下载文件' : '打开链接'}">${item.cover ? `<img src="${escape(item.cover)}" alt="" loading="lazy">` : `<span class="extension-placeholder" aria-hidden="true">${item.kind === 'file' ? '↓' : '↗'}</span>`}<span class="extension-copy"><small>${item.kind === 'file' ? '↓ 文件下载' : '↗ 外部链接'}</small><strong>${escape(item.title)}</strong><span>${escape(item.description || item.filename)}</span></span></a>${result.can_manage ? `<div class="extension-controls"><button data-edit="${item.id}">编辑</button><button data-delete="${item.id}">删除</button></div>` : ''}</article>`).join('')}</div>${items.length ? '' : '<div class="panel empty-state"><h2>资源墙等待上新</h2><p>系统管理员添加的链接与文件会展示在这里。</p></div>'}`;
      root.querySelector('#extensionAdd')?.addEventListener('click', () => editor());
      root.querySelectorAll('[data-edit]').forEach(button => button.onclick = () => editor(items.find(i => i.id === Number(button.dataset.edit))));
      root.querySelectorAll('[data-delete]').forEach(button => button.onclick = () => remove(items.find(i => i.id === Number(button.dataset.delete))));
    } catch (error) { root.innerHTML = `<p role="alert">${escape(error.message)}</p><button id="extensionRetry" class="secondary-button">重试</button>`; root.querySelector('button').onclick = load; }
  }
  function dialog(content) {
    const el = document.createElement('dialog'); el.className = 'extension-dialog'; el.innerHTML = content;
    document.body.append(el); el.addEventListener('close', () => el.remove()); el.showModal();
    el.querySelector('[data-cancel]').onclick = () => el.close(); return el;
  }
  function remove(item) {
    const el = dialog(`<h2>删除资源</h2><p>确定删除“${escape(item.title)}”？删除后成员将无法再访问此资源。</p><p role="alert"></p><div class="extension-actions"><button data-cancel class="secondary-button">取消</button><button data-confirm class="primary-button">确认删除</button></div>`);
    el.querySelector('[data-confirm]').onclick = async event => {
      event.target.disabled = true;
      try { await api(`/api/extensions/${item.id}`, {method:'DELETE'}); el.close(); await load(); }
      catch (error) { el.querySelector('[role=alert]').textContent = error.message; event.target.disabled = false; }
    };
  }
  function editor(item = {}) {
    const el = dialog(`<form class="extension-form"><h2>${item.id ? '编辑资源' : '添加资源'}</h2><label>名称<input name="title" maxlength="100" required value="${escape(item.title)}"></label><label>简介<textarea name="description" maxlength="300" rows="2">${escape(item.description)}</textarea></label><label>资源类型<select name="kind"><option value="link">超链接</option><option value="file" ${item.kind === 'file' ? 'selected' : ''}>下载文件</option></select></label><label data-url>链接地址<input type="url" name="url" placeholder="https://" value="${escape(item.url)}"></label><label data-file>下载文件<input type="file" name="file"><small>${item.filename ? `当前：${escape(item.filename)}，不选择则保留` : ''}</small></label><label>方格封面（可选）<input type="file" name="cover" accept="image/png,image/jpeg,image/webp"></label>${item.cover ? '<label class="extension-checkbox"><input type="checkbox" name="remove_cover" value="1">移除现有封面</label>' : ''}<p role="alert"></p><div class="extension-actions"><button type="button" data-cancel class="secondary-button">取消</button><button type="submit" class="primary-button">保存资源</button></div></form>`);
    const form = el.querySelector('form'), kind = form.elements.kind;
    function toggle() {
      form.querySelector('[data-url]').hidden = kind.value !== 'link';
      form.querySelector('[data-file]').hidden = kind.value !== 'file';
      form.elements.url.disabled = kind.value !== 'link';
      form.elements.url.required = kind.value === 'link';
      form.elements.file.disabled = kind.value !== 'file';
      form.elements.file.required = kind.value === 'file' && item.kind !== 'file';
    }
    kind.onchange = toggle; toggle();
    let busy = false;
    el.addEventListener('cancel', e => { if (busy) e.preventDefault(); });
    form.onsubmit = async event => {
      event.preventDefault(); if (busy) return;
      const body = new FormData(form);
      busy = true; form.querySelectorAll('button').forEach(b => b.disabled = true);
      try { await api(`/api/extensions${item.id ? '/' + item.id : ''}`, {method:'POST', body}); el.close(); await load(); }
      catch (error) { form.querySelector('[role=alert]').textContent = error.message; }
      finally { busy = false; form.querySelectorAll('button').forEach(b => b.disabled = false); }
    };
  }
  window.ExtensionResources = {load};
})();
