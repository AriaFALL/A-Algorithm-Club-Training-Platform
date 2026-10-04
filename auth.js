const auth$ = (selector, root=document) => root.querySelector(selector);
const authMessage = (text, error=true) => { auth$('#authMessage').textContent = text; auth$('#authMessage').style.color = error ? '#c26e65' : '#3d9c79'; };
document.querySelectorAll('[data-auth-tab]').forEach((button) => button.addEventListener('click', () => {
  document.querySelectorAll('[data-auth-tab]').forEach((item) => item.classList.toggle('active', item === button));
  document.querySelectorAll('.auth-form').forEach((form) => form.classList.toggle('active', form.id === `${button.dataset.authTab}Form`));
  authMessage('');
}));
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
  authMessage('登录成功，正在进入训练台…', false);
  window.location.href = '/team-select.html';
}
auth$('#loginForm')?.addEventListener('submit', async (event) => { event.preventDefault(); try { await submitAuth(event.target, 'login'); } catch (error) { authMessage(error.message); } });
