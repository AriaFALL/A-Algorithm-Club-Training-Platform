/* Presentation only: never overwrite score or other server-rendered data. */
(() => {
  'use strict';
  const init = () => {
    const view = document.getElementById('dashboardView');
    if (!view) return;
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
    let running = [];
    let wasActive = false;
    const enter = () => {
      const active = view.classList.contains('active');
      if (active === wasActive) return;
      wasActive = active;
      running.forEach(a => a.cancel()); running = [];
      if (!active || reduced.matches) return;
      [view.querySelector('.atlas-hero'), view.querySelector('.pulse-panel'), view.querySelector('.metric-grid'), view.querySelector('.content-grid')].filter(Boolean).forEach((el,i) => {
        running.push(el.animate([{opacity:0,transform:'translateY(12px)'},{opacity:1,transform:'translateY(0)'}],{duration:420,delay:i*45,fill:'both',easing:'cubic-bezier(.2,.75,.25,1)'}));
      });
    };
    new MutationObserver(enter).observe(view,{attributes:true,attributeFilter:['class']});
    reduced.addEventListener('change',() => {
      running.forEach(a => a.cancel()); running = [];
    });
    enter();
  };
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',init,{once:true}); else init();
})();
