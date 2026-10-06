(() => {
  const container=document.getElementById('account-links');
  if(!container || location.protocol==='file:')return;
  async function refresh(){
    try{
      const response=await fetch('/api/auth/session/',{credentials:'same-origin',cache:'no-store'});
      if(!response.ok)return;
      const session=await response.json();
      if(!session.authenticated)return;
      const dashboard=document.createElement('a');
      dashboard.href=session.redirect;
      dashboard.textContent='Dashboard';
      const signout=document.createElement('button');signout.type='button';signout.textContent='Sign out';
      signout.onclick=async()=>{
        signout.disabled=true;
        try{
          const result=await fetch('/api/auth/logout/',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRFToken':session.csrfToken},body:'{}'});
          if(result.ok)location.reload();else {signout.textContent='Retry sign out';signout.disabled=false;}
        }catch{signout.textContent='Retry sign out';signout.disabled=false;}
      };
      container.replaceChildren(dashboard,signout);
    }catch{}
  }
  refresh();window.addEventListener('pageshow',refresh);
})();
