/* One continuous glass selection surface, shared by all sidebar entries. */
(() => {
  const init = () => {
    const sidebar = document.querySelector('.sidebar');
    if (!sidebar || sidebar.querySelector('.menu-glass-indicator')) return;
    const mobile = matchMedia('(max-width:760px)');
    const main = document.querySelector('.main-content');
    const toggle = document.createElement('button');
    const chevron = direction => {
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('class', 'ui-chevron');
      svg.setAttribute('aria-hidden', 'true'); svg.setAttribute('focusable', 'false');
      const path = document.createElementNS(svg.namespaceURI, 'path');
      path.setAttribute('d', direction === 'right' ? 'm9 5 7 7-7 7' : 'm15 5-7 7 7 7');
      svg.append(path); return svg;
    };
    toggle.type = 'button'; toggle.className = 'mobile-menu-toggle'; toggle.append(chevron('right'));
    sidebar.id ||= 'mainSidebar';
    toggle.setAttribute('aria-controls', sidebar.id); toggle.setAttribute('aria-label', '展开菜单');
    const backdrop = document.createElement('div'); backdrop.className = 'mobile-menu-backdrop'; backdrop.hidden = true;
    const closeButton = document.createElement('button'); closeButton.type = 'button';
    closeButton.className = 'mobile-menu-close'; closeButton.append(chevron('left')); closeButton.setAttribute('aria-label', '收起菜单');
    sidebar.prepend(closeButton); document.body.append(backdrop, toggle);
    function setOpen(open, restoreFocus = true) {
      open = mobile.matches && open;
      document.body.classList.toggle('mobile-menu-open', open);
      toggle.setAttribute('aria-expanded', String(open)); toggle.hidden = open;
      backdrop.hidden = !open; sidebar.inert = mobile.matches && !open;
      if (main) main.inert = open;
      if (open) closeButton.focus(); else if (restoreFocus && mobile.matches) toggle.focus();
    }
    toggle.onclick = () => setOpen(true);
    closeButton.onclick = backdrop.onclick = () => setOpen(false);
    sidebar.addEventListener('click', event => { if (event.target.closest('.nav-item[data-view]')) setOpen(false); });
    sidebar.addEventListener('keydown', event => {
      if (!mobile.matches || !document.body.classList.contains('mobile-menu-open')) return;
      if (event.key === 'Escape') { event.preventDefault(); setOpen(false); }
      if (event.key === 'Tab') {
        const controls = [...sidebar.querySelectorAll('button:not([disabled]),a[href],input,select')].filter(el => el.getClientRects().length);
        const first = controls[0], last = controls[controls.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }
    });
    mobile.addEventListener('change', () => setOpen(false, false));
    setOpen(false, false);
    const indicator = document.createElement('div');
    indicator.className = 'menu-glass-indicator';
    indicator.setAttribute('aria-hidden', 'true');
    const surface = document.createElement('div');
    surface.className = 'menu-glass-surface';
    indicator.append(surface); sidebar.prepend(indicator);
    const reduced = matchMedia('(prefers-reduced-motion: reduce)');
    let selected = null, scheduled = 0, bounce = null, positioned = false;
    const sync = () => {
      scheduled = 0;
      if (sidebar.dataset.glassDragging) return;
      const active = sidebar.querySelector('.nav-item.active:not([hidden])');
      const rect = active?.getBoundingClientRect();
      if (!active || !rect.width || !rect.height) {if (!indicator.hidden) indicator.hidden = true; return;}
      if (indicator.hidden) indicator.hidden = false;
      const container = sidebar.getBoundingClientRect();
      const x = rect.left - container.left + sidebar.scrollLeft - sidebar.clientLeft;
      const y = rect.top - container.top + sidebar.scrollTop - sidebar.clientTop;
      indicator.style.width = `${rect.width}px`;
      indicator.style.height = `${rect.height}px`;
      indicator.style.transform = `translate3d(${x}px,${y}px,0)`;
      sidebar.querySelectorAll('.nav-item').forEach(item => {
        if(item === active) item.setAttribute('aria-current','page'); else item.removeAttribute('aria-current');
      });
      if (positioned && selected !== active && !reduced.matches) {
        bounce?.cancel();
        bounce = surface.animate([{transform:'scale(1,1)'},{transform:'scale(.98,1.12)',offset:.35},{transform:'scale(1,1)'}],{duration:420,easing:'cubic-bezier(.16,1,.3,1)'});
      }
      selected = active;
      if (!positioned) {positioned = true; requestAnimationFrame(() => sidebar.classList.add('glass-menu-ready'));}
    };
    const schedule = () => {if (!scheduled) scheduled = requestAnimationFrame(sync);};
    new MutationObserver(schedule).observe(sidebar,{subtree:true,childList:true,attributes:true,attributeFilter:['class','hidden']});
    const resize = new ResizeObserver(schedule);
    resize.observe(sidebar);
    sidebar.querySelectorAll('.nav-list,.sidebar-footer').forEach(el => resize.observe(el));
    window.addEventListener('resize',schedule);
    reduced.addEventListener('change',()=>{bounce?.cancel();schedule();});
    sync();
  };
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',init,{once:true}); else init();
})();
