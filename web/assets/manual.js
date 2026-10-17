'use strict';
const manualFields=['Company','Job Title','Source','Location','Salary','Work Arrangement','Employment Type','Personal priority','Date Posted','Notes','description'];
let manualBusy=false;
let manualPending=false;
let manualEdit=null;
let manualDirty=false;
const manualDraftKey='gecko.manual-intake.draft.v1';
function manualMessage(message){
 for(const id of ['manual-status','manual-save-status'])if($(id))$(id).textContent=message;
}
function storeManualDraft(form){
 try{localStorage.setItem(manualDraftKey,JSON.stringify({fields:Object.fromEntries(new FormData(form)),applied:form.elements.applied.checked,pending:manualPending,edit:manualEdit}));}catch{/* The form remains usable if browser storage is unavailable. */}
}
async function saveManualForm(form){
 if(manualBusy)return;
 form.elements.applied_date.required=form.elements.applied.checked;
 const invalid=Array.from(form.elements).find(el=>el.willValidate&&!el.validity.valid);
 if(invalid){manualMessage('Not saved: '+(invalid.name==='url'?'Enter the job posting link.':invalid.name==='applied_date'?'Enter the date you applied.':'Enter '+invalid.name+'.'));invalid.focus();return;}
 const payload=Object.fromEntries(new FormData(form));payload.applied=form.elements.applied.checked;if(manualEdit){payload.id=manualEdit.id;payload.version=manualEdit.version;}
 manualBusy=true;$('manual-save').disabled=$('manual-save-applied').disabled=true;storeManualDraft(form);
 try{
  const activity=await api('/api/activity');
  if(activity.busy||activity.operation?.status==='running'){
   manualPending=true;storeManualDraft(form);manualMessage('Waiting to save: Gecko is running. Your draft is kept in this browser and will save automatically when the run finishes. Keep this dashboard open, or reopen it later to resume.');renderManualTable();notify('Draft preserved. Waiting for Gecko to finish.');return;
  }
  manualMessage('Saving and verifying your job…');
  const saved=await api('/api/manual',payload);
  const snapshot=await api('/api/jobs');
  if(!(snapshot.manual_ids||[]).includes(saved.id)||snapshot.jobs.filter(j=>j.id===saved.id).length!==1)throw Error('The save returned an ID, but list verification failed. Keep this form and check the existing job before retrying.');
  manualPending=false;manualDirty=false;try{localStorage.removeItem(manualDraftKey);}catch{}
  if(saved.updated){await refresh();await openManualJob(saved.id,true);manualMessage('Saved job '+saved.id+'. Status: '+(saved.applied?'Applied':'Not applied')+'.');notify('Job '+saved.id+' updated and verified.');return;}
  form.reset();form.elements.applied_date.value=today();form.elements.applied_date.required=false;
  await refresh();manualMessage('Saved and verified: job ID '+saved.id+' appears below and in All Jobs.');notify('Job '+saved.id+' saved and verified.');
 }catch(err){
  manualPending=false;storeManualDraft(form);manualMessage('Not saved: '+(/Permission denied/i.test(err.message)?'Gecko is busy. Your draft is preserved; click Save job again after the run finishes.':err.message));notify('Job was not saved. See the message beside Save job.');
 }finally{manualBusy=false;$('manual-save').disabled=$('manual-save-applied').disabled=false;}
}
setInterval(async()=>{
 const form=$('manual-form');if(!form||!manualPending||manualBusy)return;
 try{const activity=await api('/api/activity');if(!activity.busy&&activity.operation?.status!=='running')await saveManualForm(form);}catch{/* Retain the draft and try after the connection recovers. */}
},10000);

const manualFilters={};
let manualSort={key:'ID',direction:1};
function renderManual(){
 const root=$('manual-section');
 $('page-subtitle').textContent='Add a job you found yourself. Review the details, then save it to both this list and All Jobs.';
 if(!root.dataset.built){
  root.dataset.built='yes';
  root.innerHTML='<form id="manual-form" class="activity-card" novalidate><h2 id="manual-form-title">Add a job or application</h2><p>A unique job ID is assigned when you save. Saving does not submit an application. Save and applied records that you have already submitted it.</p><label>Job posting link<input name="url" type="url" required placeholder="https://www.indeed.com/viewjob?jk=…"></label><button type="button" id="manual-fetch" class="button secondary">Auto-fill with OpenClaw</button><p id="manual-status" role="status">You can also enter details yourself. Review imported information before saving.</p><div class="manual-fields">'+manualFields.map(k=>'<label>'+esc(k==='description'?'Job description':k)+(k==='Notes'||k==='description'?'<textarea name="'+k+'"></textarea>':'<input name="'+k+'" '+(['Company','Job Title'].includes(k)?'required':'')+(k==='Date Posted'?' type="date"':'')+'>')+'</label>').join('')+'</div><label><input type="checkbox" name="applied"> I already submitted this application</label><label>Application date<input type="date" name="applied_date"></label><p id="manual-save-status" class="manual-save-status" role="status" aria-live="polite"></p><div class="actions"><button type="submit" class="button primary" id="manual-save">Save job</button><button type="button" class="button primary" id="manual-save-applied">Save and applied</button><button type="button" class="button secondary" id="manual-new" hidden>Add another job</button></div></form><div id="manual-table"></div>';
  const form=$('manual-form');form.elements.applied_date.value=today();
  $('manual-save-applied').onclick=()=>{if(manualBusy)return;form.elements.applied.checked=true;if(!form.elements.applied_date.value)form.elements.applied_date.value=today();saveManualForm(form);};
  $('manual-new').onclick=()=>{if(manualBusy||manualDirty){manualMessage('Save your current changes before adding another job.');return;}manualEdit=null;if(typeof manualResume!=='undefined'){manualResume=null;$('manual-resume-status').textContent='No resume attached.';$('manual-resume-remove').hidden=true;}form.reset();form.elements.url.readOnly=false;form.elements.applied.disabled=false;form.elements.applied_date.value=today();form.elements.applied_date.required=false;$('manual-form-title').textContent='Add a job or application';$('manual-new').hidden=true;manualMessage('Enter the new job details.');};
  form.onsubmit=e=>{e.preventDefault();saveManualForm(form);};
  form.oninput=()=>{manualDirty=true;const wasPending=manualPending;manualPending=false;form.elements.applied_date.required=form.elements.applied.checked;storeManualDraft(form);if(wasPending){manualMessage('Draft changed. Click Save job to save these updated details.');renderManualTable();}};
  try{const draft=JSON.parse(localStorage.getItem(manualDraftKey)||'null');if(draft?.fields){manualEdit=draft.edit||null;manualDirty=true;if(manualEdit){$('manual-form-title').textContent='Edit job '+manualEdit.id;form.elements.url.readOnly=true;$('manual-new').hidden=false;}for(const [key,value] of Object.entries(draft.fields)){const el=form.elements.namedItem(key);if(el&&el.type!=='checkbox')el.value=value;}form.elements.applied.checked=!!draft.applied;form.elements.applied_date.required=!!draft.applied;manualPending=!!draft.pending;manualMessage(manualPending?'Pending save restored. This job will save when Gecko finishes.':'Your unsaved draft was restored. Review it and click Save job.');}}catch{}
  $('manual-fetch').onclick=async()=>{
   if(manualBusy)return;const url=form.elements.url.value;if(!url){manualMessage('Enter a posting link first.');return;}
   manualPending=false;storeManualDraft(form);manualBusy=true;Array.from(form.elements).forEach(el=>el.disabled=true);manualMessage('OpenClaw is reading the posting. This can take a few minutes…');
   try{await api('/api/manual-import',{url});let result;const deadline=Date.now()+440000;do{await new Promise(r=>setTimeout(r,2000));result=await api('/api/manual-import');if(Date.now()>deadline)throw Error('Import is taking too long. You can enter the details manually.');}while(result.status==='running');if(result.status!=='ready')throw Error(result.error||'Import did not finish.');if(result.url!==url)throw Error('The import link changed. Please try again.');for(const key of manualFields)if(result.details[key])form.elements.namedItem(key).value=result.details[key];manualMessage('Details imported. Review and correct them, then save.');}catch(err){manualMessage(err.message);}finally{manualBusy=false;Array.from(form.elements).forEach(el=>el.disabled=false);storeManualDraft(form);}
  };
 }
 renderManualTable();
}
function renderManualTable(){
 const cols=['ID','Company','Job Title','Source','Location','Applied Date','Status'];
 const rows=state.jobs.filter(j=>(state.manualIds||[]).includes(j.id)).map(j=>({...j.fields,ID:j.id,Status:j.applied?'Applied':'Not yet applied','Applied Date':j.fields['Applied Date']||j.meta.applied_at||''}));
 const shown=rows.filter(r=>cols.every(k=>String(r[k]||'').toLowerCase().includes((manualFilters[k]||'').toLowerCase()))).sort((a,b)=>String(a[manualSort.key]||'').localeCompare(String(b[manualSort.key]||''),undefined,{numeric:true})*manualSort.direction);
 const pendingForm=$('manual-form');
 const pendingNotice=manualPending?'<div class="manual-save-status" role="status"><strong>Pending save: '+esc(pendingForm.elements.namedItem('Company').value)+' — '+esc(pendingForm.elements.namedItem('Job Title').value)+'</strong><br>This entry is preserved in this browser. It will receive its job ID and appear in both lists after Gecko finishes and the save is verified.</div>':'';
 $('manual-table').innerHTML=pendingNotice+'<div class="section-heading"><h2>Your individually added jobs</h2><span>'+shown.length+' of '+rows.length+(manualPending?' saved · 1 pending':'')+'</span></div><p>Open a job to record an application or update its next steps. All Jobs uses the same record.</p><div class="table-wrap"><table><thead><tr>'+cols.map(k=>'<th>'+esc(k)+' <button type="button" class="column-filter" data-manual-focus="'+k+'" aria-label="Filter '+k+'">▽</button><button type="button" class="column-filter" data-manual-sort="'+k+'" aria-label="Sort '+k+'">↕</button><input data-manual-filter="'+k+'" aria-label="Search '+k+'" value="'+esc(manualFilters[k]||'')+'" placeholder="Filter…"></th>').join('')+'</tr></thead><tbody>'+shown.map(r=>'<tr data-workspace-job="'+esc(r.ID)+'" data-workspace-label="'+esc(r.Company)+' — '+esc(r['Job Title'])+'">'+cols.map(k=>'<td>'+(k==='Job Title'?'<button class="text-button" data-manual-open="'+esc(r.ID)+'">'+esc(r[k])+'</button>':esc(r[k]||'—'))+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>'+(!rows.length?'<p>'+(manualPending?'No saved records yet. Your pending entry is shown above.':'No individually added jobs yet. Add your first posting above.')+'</p>':'');
 const root=$('manual-table');root.querySelectorAll('[data-manual-open]').forEach(b=>b.onclick=()=>openManualJob(b.dataset.manualOpen));bindWorkspaceRows(root,row=>openManualJob(row.dataset.workspaceJob));
 root.querySelectorAll('[data-manual-filter]').forEach(input=>input.oninput=()=>{const key=input.dataset.manualFilter,caret=input.selectionStart;manualFilters[key]=input.value;renderManualTable();const next=root.querySelector('[data-manual-filter="'+key+'"]');next.focus();next.setSelectionRange(caret,caret);});
 root.querySelectorAll('[data-manual-focus]').forEach(b=>b.onclick=()=>root.querySelector('[data-manual-filter="'+b.dataset.manualFocus+'"]').focus());
 root.querySelectorAll('[data-manual-sort]').forEach(b=>b.onclick=()=>{manualSort={key:b.dataset.manualSort,direction:manualSort.key===b.dataset.manualSort?-manualSort.direction:1};renderManualTable();});
}


async function openManualJob(id,afterSave=false){
 if(manualBusy&&!afterSave)return;
 if(manualDirty){manualMessage('Save your current changes before opening another job.');return;}
 try{
  const job=await api('/api/job?id='+encodeURIComponent(id));
  if(!(state.manualIds||[]).includes(job.id))throw Error('This job is not in your individually added list.');
  if(manualDirty){manualMessage('Your draft changed while this job was loading. Save it before opening another job.');return;}
  const form=$('manual-form');
  manualEdit={id:job.id,version:job.version};manualPending=false;
  if(typeof manualResume!=='undefined'){manualResume=null;$('manual-resume-status').textContent=job.attached_resume?job.attached_resume.name+' — existing attachment preserved.':'No resume attached.';$('manual-resume-remove').hidden=true;}
  form.elements.url.value=job.url;form.elements.url.readOnly=true;
  for(const key of manualFields)form.elements.namedItem(key).value=key==='description'?(job.description||''):key==='Notes'?job.notes:(job.fields[key]||'');
  form.elements.applied.checked=job.applied;form.elements.applied.disabled=job.applied;
  form.elements.applied_date.value=String(job.fields['Applied Date']||job.meta.applied_at||today()).slice(0,10);
  form.elements.applied_date.required=job.applied;
  $('manual-form-title').textContent='Edit job '+job.id+' · '+job.fields.Company;
  form.querySelector('p').textContent='Continue your saved job or application. Saving updates this same record in this list and All Jobs.';
  $('manual-new').hidden=false;
  manualMessage('Job '+job.id+' loaded. Save job keeps its current application status; Save and applied records your completed application.');
  manualDirty=false;
  window.scrollTo({top:0,left:0,behavior:'instant'});
 }catch(error){manualMessage('Could not open this job: '+error.message);}
}
