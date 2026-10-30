/* Non-searchable platform filters; native change handlers remain the source of truth. */
document.addEventListener('DOMContentLoaded', () => {
  if (!window.TomSelect) return;
  document.querySelectorAll('[data-rating-platform], #contestPlatform').forEach(select => {
    if (select.tomselect) return;
    const label = select.getAttribute('aria-label') || '比赛平台';
    new TomSelect(select, {
      create: false,
      maxItems: 1,
      allowEmptyOption: true,
      controlInput: null,
      searchField: [],
      onInitialize() {
        this.wrapper.classList.add('platform-select');
        this.control.setAttribute('aria-label', label);
        select.classList.add('platform-select-native');
      }
    });
  });
});
