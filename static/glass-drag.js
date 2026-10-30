/* Shared pointer gestures for every liquid-glass selection surface. */
(() => {
  let gesture = null, frame = 0, suppressed = null;
  const visible = button => !button.disabled && !button.hidden && button.getClientRects().length && getComputedStyle(button).visibility !== 'hidden';
  function describe(button) {
    const group = button.closest('.segmented, .auth-tabs, .sidebar');
    if (!group) return null;
    const type = group.matches('.sidebar') ? 'menu' : group.matches('.auth-tabs') ? 'auth' : 'segment';
    if (type === 'menu' && !button.matches('.nav-item')) return null;
    const selector = type === 'menu' ? '.nav-item' : type === 'auth' ? '[data-auth-tab]' : '.segment';
    const items = [...group.querySelectorAll(selector)].filter(visible);
    const indicator = group.querySelector(type === 'menu' ? '.menu-glass-indicator' : type === 'auth' ? '.auth-glass-indicator' : '.segment-indicator');
    if (items.length < 2 || !indicator) return null;
    const axis = type === 'segment' ? 'x' : 'y';
    const rects = items.map(item => item.getBoundingClientRect());
    const centers = rects.map(rect => axis === 'x' ? rect.left + rect.width/2 : rect.top + rect.height/2);
    const selected = Math.max(0, items.findIndex(item => item.classList.contains('active')));
    return {group, type, items, indicator, axis, rects, centers, selected};
  }
  function paint(state, coordinate) {
    const {centers, rects, axis, group, indicator, type} = state;
    const position = Math.max(centers[0], Math.min(centers.at(-1), centers[state.selected] + coordinate - state.start));
    let index = centers.findIndex(center => center >= position);
    if (index < 0) index = centers.length - 1;
    const previous = Math.max(0, index - 1);
    const fraction = index === previous ? 0 : (position - centers[previous]) / (centers[index] - centers[previous]);
    const mix = key => rects[previous][key] + (rects[index][key] - rects[previous][key]) * fraction;
    const parent = group.getBoundingClientRect();
    if (type === 'segment') {
      group.style.setProperty('--segment-x', `${mix('left') - parent.left + group.scrollLeft - group.clientLeft}px`);
      group.style.setProperty('--segment-width', `${mix('width')}px`);
    } else if (type === 'auth') {
      indicator.style.transform = `translateY(${mix('top') - parent.top - 4}px)`;
    } else {
      indicator.style.width = `${mix('width')}px`;
      indicator.style.height = `${mix('height')}px`;
      indicator.style.transform = `translate3d(${mix('left') - parent.left + group.scrollLeft - group.clientLeft}px,${mix('top') - parent.top + group.scrollTop - group.clientTop}px,0)`;
    }
    state.nearest = centers.reduce((best, center, i) => Math.abs(center-position) < Math.abs(centers[best]-position) ? i : best, 0);
  }
  function finish(cancelled = false) {
    const state = gesture;
    if (!state) return;
    gesture = null; cancelAnimationFrame(frame); frame = 0;
    if (!state.dragging) return;
    const target = state.items[cancelled ? state.selected : state.nearest];
    // Restore transitions before moving from the last dragged position to the snap point.
    state.group.classList.remove('glass-dragging');
    delete state.group.dataset.glassDragging;
    if (state.type === 'auth') state.indicator.style.transform = state.originalTransform;
    else {
      const saved = state.selected;
      state.selected = state.items.indexOf(target);
      paint(state, state.start);
      state.selected = saved;
    }
    suppressed = {group:state.group, until:performance.now()+450};
    if (state.group.hasPointerCapture(state.id)) state.group.releasePointerCapture(state.id);
    if (!cancelled && target?.isConnected && visible(target)) {
      target.focus({preventScroll:true});
      if (!target.classList.contains('active')) target.click();
    }
  }
  document.addEventListener('pointerdown', event => {
    if (gesture || event.isPrimary === false || event.button !== 0) return;
    const button = event.target.closest('button');
    const state = button && describe(button);
    if (!state) return;
    gesture = {...state, id:event.pointerId, start:state.axis === 'x' ? event.clientX : event.clientY,
      otherStart:state.axis === 'x' ? event.clientY : event.clientX, coordinate:0,
      nearest:state.selected, dragging:false, originalTransform:state.indicator.style.transform};
  }, true);
  document.addEventListener('pointermove', event => {
    const state = gesture;
    if (!state || event.pointerId !== state.id) return;
    const coordinate = state.axis === 'x' ? event.clientX : event.clientY;
    if (!state.dragging) {
      const distance = Math.abs(coordinate-state.start);
      const cross = Math.abs((state.axis === 'x' ? event.clientY : event.clientX)-state.otherStart);
      if (cross > 8 && cross > distance) {gesture=null;return;}
      if (distance < 6) return;
      state.dragging = true;
      state.group.dataset.glassDragging = 'true';
      state.group.classList.add('glass-dragging');
      state.group.setPointerCapture(event.pointerId);
      state.indicator.getAnimations().forEach(animation => animation.cancel());
    }
    event.preventDefault();
    state.coordinate = coordinate;
    if (!frame) frame = requestAnimationFrame(() => {frame=0;if (gesture === state) paint(state,state.coordinate);});
  }, {capture:true, passive:false});
  document.addEventListener('pointerup', event => {
    if (!gesture || event.pointerId !== gesture.id) return;
    if (gesture.dragging) {event.preventDefault();paint(gesture,gesture.axis === 'x' ? event.clientX : event.clientY);}
    finish();
  }, true);
  document.addEventListener('pointercancel', event => {if (gesture?.id === event.pointerId) finish(true);}, true);
  // Touch starts with implicit capture on the button. Transferring that capture
  // to the group emits a bubbling lostpointercapture for the button, not a cancel.
  document.addEventListener('lostpointercapture', event => {
    if (gesture?.id === event.pointerId && event.target === gesture.group) finish(true);
  }, true);
  document.addEventListener('click', event => {
    if (event.isTrusted && suppressed && performance.now() < suppressed.until && suppressed.group.contains(event.target)) {
      event.preventDefault(); event.stopImmediatePropagation(); suppressed=null;
    }
  }, true);
  window.addEventListener('resize', () => finish(true));
  window.addEventListener('blur', () => finish(true));
  document.addEventListener('visibilitychange', () => {if (document.hidden) finish(true);});
})();
