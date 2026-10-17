'use strict';
(async()=>{
 const token=location.hash.slice(1);
 // Remove the setup key before loading the workspace or making another request.
 history.replaceState(null,'','/connect');
 if(!token){location.replace('/');return;}
 try {
  const response=await fetch('/cloud/connect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token})});
  if(!response.ok){const data=await response.json();document.getElementById('connection-status').textContent=data.error||'Could not connect this device.';return;}
  location.replace('/');
 } catch(error){document.getElementById('connection-status').textContent='The connection was interrupted. Open your private Gecko setup link again.';}
})();
