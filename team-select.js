const $=s=>document.querySelector(s);
const list=$('#teamList');
clubApi.request('/api/me').then(async (response)=>{
  if (response.status === 401) { location.href='/auth.html'; return; }
  const data=await response.json().catch(()=>({}));
  if (!response.ok) { list.innerHTML='<div class="auth-message" role="status">团队列表加载失败，请刷新重试</div>'; return; }
  const teams=data.teams||[];
  if (!teams.length) { list.innerHTML='<div class="empty-team-state">当前账号还没有加入团队，请选择加入或创建团队。</div>'; return; }
  teams.forEach(t=>{const b=document.createElement('button');b.className='secondary-button auth-submit team-choice';b.type='button';const copy=document.createElement('span');const name=document.createElement('strong');name.textContent=t['team__name']||'未命名团队';const code=document.createElement('small');code.textContent=t['team__code']||'';copy.append(name,code);const arrow=document.createElement('span');arrow.setAttribute('aria-hidden','true');arrow.textContent='→';b.append(copy,arrow);b.onclick=async()=>{b.disabled=true;const response=await clubApi.request('/api/team/select',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({team_id:t.team_id})});if(response.ok)location.href='/';else{b.disabled=false;const payload=await response.json().catch(()=>({}));$('#message').textContent=payload.error||'进入团队失败，请重试';}};list.appendChild(b)})
}).catch(()=>{list.innerHTML='<div class="auth-message" role="status">网络连接失败，请刷新重试</div>';});
$('#createTeam').onclick=()=>location.href='/create-team.html'; $('#joinTeam').onclick=()=>location.href='/join-team.html'; $('#logout').onclick=async()=>{await clubApi.request('/api/auth/logout',{method:'POST'});location.href='/auth.html'};
