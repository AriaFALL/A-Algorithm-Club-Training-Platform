/* Site confirmations, powered by locally hosted SweetAlert2. */
(() => {
  const symbols = {
    ticket: '<path d="M4 5h16v5a2 2 0 0 0 0 4v5H4v-5a2 2 0 0 0 0-4V5Z"/><path d="M15 5v3m0 3v2m0 3v3"/>',
    cart: '<path d="M3 4h2l2 11h12l2-8H6"/><circle cx="9" cy="20" r="1"/><circle cx="18" cy="20" r="1"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v1"/>'
  };
  async function open({title, text, confirmText = '确定', cancelText = '取消', kind = 'info', confirm = false}) {
    if (!window.Swal) throw new Error('弹窗组件未加载，请刷新页面后重试');
    return Swal.fire({
      titleText: title, text, icon: 'info',
      iconHtml: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${symbols[kind] || symbols.info}</svg>`,
      confirmButtonText: confirmText, cancelButtonText: cancelText,
      showCancelButton: confirm, focusCancel: confirm, buttonsStyling: false,
      reverseButtons: true, heightAuto: false, scrollbarPadding: false,
      returnFocus: true, showCloseButton: false,
      customClass: {container:'club-dialog-container', popup:'club-dialog', title:'club-dialog-title', htmlContainer:'club-dialog-copy', icon:'club-dialog-symbol', actions:'club-dialog-actions', confirmButton:'club-dialog-confirm', cancelButton:'club-dialog-cancel'},
      showClass: {popup:'club-dialog-enter'}, hideClass: {popup:'club-dialog-leave'}
    });
  }
  window.clubDialog = {
    confirm: async options => (await open({...options, confirm:true})).isConfirmed,
    notice: options => open(options)
  };
})();
