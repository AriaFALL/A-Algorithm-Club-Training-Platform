/* Shared API transport for all pages. Keeps CSRF/session handling consistent. */
(() => {
  const readCookie = (name) => decodeURIComponent(
    document.cookie.split('; ').find((item) => item.startsWith(`${name}=`))?.split('=')[1] || '',
  );

  let refreshPromise = null;
  async function csrfToken(force = false) {
    const current = readCookie('csrftoken');
    if (current && !force) return current;
    if (!refreshPromise) {
      refreshPromise = fetch('/api/csrf', {
        credentials: 'same-origin',
        cache: 'no-store',
        headers: {Accept: 'application/json'},
      }).then(async (response) => {
        if (!response.ok) throw new Error('无法获取安全令牌');
        const payload = await response.json();
        return payload.csrfToken || readCookie('csrftoken');
      }).finally(() => { refreshPromise = null; });
    }
    return refreshPromise;
  }

  async function request(url, options = {}) {
    const method = (options.method || 'GET').toUpperCase();
    const headers = new Headers(options.headers || {});
    if (!headers.has('Accept')) headers.set('Accept', 'application/json');
    if (!['GET', 'HEAD', 'OPTIONS'].includes(method) && !headers.has('X-CSRFToken')) {
      headers.set('X-CSRFToken', await csrfToken());
    }
    const requestOptions = {...options, method, headers, credentials: 'same-origin'};
    let response = await fetch(url, requestOptions);
    // A stale tab or a rotated cookie can cause one CSRF failure. Refresh the
    // token once, then retry only when Django returned its HTML CSRF page.
    const contentType = response.headers.get('content-type') || '';
    if (response.status === 403 && contentType.includes('text/html') && !['GET', 'HEAD'].includes(method)) {
      headers.set('X-CSRFToken', await csrfToken(true));
      response = await fetch(url, requestOptions);
    }
    return response;
  }

  window.clubApi = {request, csrfToken, readCookie};
})();
