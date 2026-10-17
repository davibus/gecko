'use strict';
document.getElementById('login-form').addEventListener('submit',async event=>{
 event.preventDefault();const button=event.target.querySelector('button');button.disabled=true;
 const error=document.getElementById('error');error.textContent='';
 try {
  const response=await fetch('/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:document.getElementById('password').value})});
  if(response.ok) {location.replace('/');return;}
  const data=await response.json();error.textContent=data.error||'Could not sign in.';
 } catch(problem) {error.textContent='Could not connect. Please try again.';}
 finally {button.disabled=false;}
});
