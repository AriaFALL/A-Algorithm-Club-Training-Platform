(() => {
  async function joinTeam(code) {
    const response = await clubApi.request('/api/auth/join', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({team_code:code.trim()})
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || '加入失败，请稍后重试');
    return data;
  }
  window.openJoinTeamDialog = async () => {
    const result = await Swal.fire({
      titleText:'加入团队', text:'输入团队码，即可加入训练团队。',
      input:'text', inputLabel:'团队码', inputPlaceholder:'例如：ACM2026',
      inputAttributes:{maxlength:'32', autocomplete:'off', autocapitalize:'off', spellcheck:'false'},
      showCancelButton:true, confirmButtonText:'加入团队', cancelButtonText:'取消',
      reverseButtons:true, buttonsStyling:false, heightAuto:false, scrollbarPadding:false,
      showLoaderOnConfirm:true, allowOutsideClick:() => !Swal.isLoading(), allowEscapeKey:() => !Swal.isLoading(),
      customClass:{container:'club-dialog-container', popup:'club-dialog team-join-dialog', title:'club-dialog-title', htmlContainer:'club-dialog-copy', actions:'club-dialog-actions', confirmButton:'club-dialog-confirm', cancelButton:'club-dialog-cancel'},
      showClass:{popup:'club-dialog-enter'}, hideClass:{popup:'club-dialog-leave'},
      preConfirm:async code => {
        if (!code.trim()) {Swal.showValidationMessage('请填写团队码');return false;}
        try {return await joinTeam(code);} catch(error) {Swal.showValidationMessage(error.message);return false;}
      }
    });
    if (result.isConfirmed) location.href = '/';
  };
  document.addEventListener('DOMContentLoaded', () => {
    const form = document.querySelector('#joinTeamForm');
    if (!form) return;
    form.addEventListener('submit', async event => {
      event.preventDefault();
      const button = form.querySelector('button[type="submit"]');
      const message = document.querySelector('#message');
      if (button.disabled) return;
      button.disabled = true; button.textContent = '正在加入…'; message.textContent = '';
      try {await joinTeam(form.elements.team_code.value);location.href='/';}
      catch(error) {message.textContent=error.message;}
      finally {button.disabled=false;button.textContent='加入团队';}
    });
  });
})();
