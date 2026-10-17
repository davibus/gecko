'use strict';
// Keep the existing dashboard API, while each network request stays short on Vercel.
(() => {
 const directFetch = window.fetch.bind(window);
 let csrf = '';
 const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
 const failure = message => new Response(JSON.stringify({error:message}), {status:503,headers:{'Content-Type':'application/json'}});
 const deviceAccess=document.documentElement?.dataset.accessMode==='device';
 const signIn = response => {if(response.status===401 && !deviceAccess) location.assign('/login');return response;};
 async function unpack(ticket, metadata) {
  const parts=[];
  for(let index=0;index<metadata.chunks;index++) {
   const response=signIn(await directFetch('/cloud/chunk/'+ticket+'/'+index));
   if(!response.ok)return response;parts.push(await response.arrayBuffer());
  }
  const reader=new Blob(parts).stream().pipeThrough(new DecompressionStream('deflate')).getReader();
  const decoded=[];let size=0;
  while(true) {const {value,done}=await reader.read();if(done)break;size+=value.length;if(size>30000000){await reader.cancel();throw new Error('Result too large');}decoded.push(value);}
  let body=new Blob(decoded,{type:metadata.content_type});
  if(metadata.csrf) {const snapshot=JSON.parse(await body.text());snapshot.token=metadata.csrf;body=JSON.stringify(snapshot);}
  const headers={'Content-Type':metadata.content_type};
  if(metadata.filename)headers['Content-Disposition']="attachment; filename*=UTF-8''"+encodeURIComponent(metadata.filename);
  return new Response(body,{status:metadata.status,headers});
 }
 async function relay(path, options={}) {
  const started = signIn(await directFetch(path, options));
  if(started.status!==202) return started;
  const {ticket} = await started.json();
  const deadline = Date.now()+170000;
  while(Date.now()<deadline) {
   await pause(1500);
   const response = signIn(await directFetch('/cloud/result/'+ticket));
   if(response.status!==202) {
    if(response.ok && response.headers.get('Content-Type')?.startsWith('application/json')) {
     const metadata=await response.clone().json();
     if(metadata.packed)return unpack(ticket,metadata);
    }
    return response;
   }
  }
  return failure('The result is unconfirmed. Refresh to check the current state before repeating an edit or run.');
 }
 async function download(path) {
  const response=await relay(path);
  if(!response.ok) {const data=await response.json();throw new Error(data.error||'Download failed.');}
  const disposition=response.headers.get('Content-Disposition')||'';
  const matched=disposition.match(/filename\*=UTF-8''([^;]+)/i);
  const blob=URL.createObjectURL(await response.blob());
  const anchor=document.createElement('a');anchor.href=blob;anchor.download=matched?decodeURIComponent(matched[1]):'Gecko-resume.docx';
  document.body.append(anchor);anchor.click();anchor.remove();setTimeout(()=>URL.revokeObjectURL(blob),60000);
 }
 window.fetch = async (input, options={}) => {
  if(typeof input!=='string' || !input.startsWith('/api/')) return directFetch(input,options);
  try {
   if(input==='/api/open-resume') {
    const payload=JSON.parse(options.body);await download('/api/resume?id='+encodeURIComponent(payload.id));
    return new Response(JSON.stringify({opened:'downloaded'}),{headers:{'Content-Type':'application/json'}});
   }
   return await relay(input,options);
  } catch(error) {
   return failure('The connection was interrupted. Refresh to verify the current state before repeating an edit or run.');
  }
 };
 document.addEventListener('click',async event=>{
  const link=event.target.closest('a[href^="/api/resume?"]');
  if(!link)return;event.preventDefault();
  try {await download(link.getAttribute('href'));} catch(error) {alert(error.message);}
 });
 document.addEventListener('DOMContentLoaded',async()=>{
  const connection=document.querySelector('.connection');
  const sidebar=document.querySelector('.sidebar-bottom p');
  if(sidebar) sidebar.textContent='Connected to your Windows workspace. Your computer must be awake to view jobs, save changes, and run Gecko.';
  const logout=document.createElement('button');logout.className='button secondary';logout.textContent=deviceAccess?'Disconnect device':'Sign out';
  logout.addEventListener('click',async()=>{
   const response=await directFetch('/cloud/logout',{method:'POST',headers:{'X-Gecko-Token':csrf}});
   if(response.ok || response.status===401) {localStorage.removeItem('gecko.manual-intake.draft.v1');location.assign(deviceAccess?'/':'/login');}
  });
  document.querySelector('.header-actions')?.append(logout);
  async function check() {
   try {
    const response=signIn(await directFetch('/cloud/connection'));
    if(!response.ok)throw new Error('Connection unavailable');
    const status=await response.json();csrf=status.csrf;
    if(connection) connection.textContent=status.online?'Gecko computer connected':'Gecko computer offline';
   } catch(error) {if(connection)connection.textContent='Connection unavailable';}
  }
  await check();setInterval(check,30000);
 });
})();
