const auth$ = (selector, root=document) => root.querySelector(selector);
const authMessage = (text, error=true) => { auth$('#authMessage').textContent = text; auth$('#authMessage').style.color = error ? '#c26e65' : '#3d9c79'; };
const systemNotice = new URLSearchParams(location.search).get('notice');
if (systemNotice === 'password-changed') authMessage('密码已保存，请使用新密码重新登录。', false);
if (systemNotice === 'restored') authMessage('数据恢复完成，请使用备份时的账号密码重新登录。', false);
document.querySelectorAll('[data-auth-tab]').forEach((button) => button.addEventListener('click', () => {
  document.querySelectorAll('[data-auth-tab]').forEach((item) => {
    item.classList.toggle('active', item === button);
    item.setAttribute('aria-selected', String(item === button));
    item.tabIndex = item === button ? 0 : -1;
  });
  document.querySelector('.auth-tabs').classList.toggle('is-register', button.dataset.authTab === 'register');
  document.querySelectorAll('.auth-form').forEach((form) => {
    const active = form.id === `${button.dataset.authTab}Form`;
    form.classList.toggle('active', active); form.hidden = !active;
  });
  authMessage('');
}));
document.querySelector('.auth-tabs')?.addEventListener('keydown', event => {
  if (!['ArrowDown', 'ArrowUp', 'ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
  event.preventDefault();
  const tabs = [...document.querySelectorAll('[data-auth-tab]')];
  const index = event.key === 'Home' ? 0 : event.key === 'End' ? 1 : 1 - tabs.indexOf(document.activeElement);
  tabs[index]?.click(); tabs[index]?.focus();
});
async function submitAuth(form, endpoint) {
  const data = Object.fromEntries(new FormData(form).entries());
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 15000);
  let response;
  try {
    response = await clubApi.request(`/api/auth/${endpoint}`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data), signal:controller.signal});
  } catch (error) {
    throw new Error(error.name === 'AbortError' ? '服务器响应超时，请稍后重试' : '无法连接服务器，请检查网络或网站状态');
  } finally {
    window.clearTimeout(timeout);
  }
  const contentType = response.headers.get('content-type') || '';
  const result = contentType.includes('application/json') ? await response.json().catch(() => ({})) : {};
  if (!response.ok) throw new Error(result.error || '操作失败，请稍后重试');
  authMessage(endpoint === 'register' ? '注册成功，正在进入团队选择…' : '登录成功，正在进入训练台…', false);
  window.location.href = endpoint === 'register' ? '/team-select.html' : '/';
}
auth$('#loginForm')?.addEventListener('submit', async (event) => { event.preventDefault(); try { await submitAuth(event.target, 'login'); } catch (error) { authMessage(error.message); } });
auth$('#registerForm')?.addEventListener('submit', async event => {
  event.preventDefault(); const form = event.target, button = form.querySelector('[type=submit]');
  if (button.disabled) return;
  if (form.elements.password.value !== form.elements.confirm_password.value) { authMessage('两次密码不一致'); return; }
  button.disabled = true;
  try { await submitAuth(form, 'register'); } catch (error) { authMessage(error.message); }
  finally { button.disabled = false; }
});
