'use strict';
let preparationRecords=[],preparationLoading=false,preparationDispatching=false;
function preparationLabel(record){return ({preparing:'Preparing',ready_for_review:'Ready for your review',needs_attention:'Needs your attention'})[record.status]||record.status;}
function renderPreparationCards(){
 const box=$('preparation-records');if(!box)return;
 box.innerHTML=preparationRecords.map(record=>{
  const job=state.jobs.find(j=>j.id===record.id),applied=job?.applied;
  return '<div class="history-item"><strong>'+esc(record.company?record.company+' — '+record.title:'Indeed posting')+'</strong><p><strong>'+esc(applied?'Applied':preparationLabel(record))+'</strong> · '+esc(record.reason)+'</p>'+(record.missing_fields?.length?'<ul>'+record.missing_fields.map(q=>'<li>'+esc(q)+'</li>').join('')+'</ul>':'')+'<div class="actions">'+(!applied?'<a class="button secondary" href="'+esc(record.application_url||record.url)+'" target="_blank" rel="noopener noreferrer">'+(record.status==='ready_for_review'?'Open review':'Open existing application')+'</a>':'')+(record.id?'<button class="button secondary" type="button" data-prepared-job="'+esc(record.id)+'">Open saved job '+esc(record.id)+'</button>':'')+'</div>'+(record.status==='ready_for_review'&&!applied?'<p class="subtext">Review every answer in the employer’s tab, complete any CAPTCHA, and submit yourself. Then open the saved job and use Save and applied. If the site asks you to resume a draft, use that draft.</p>':'')+'</div>';
 }).join('');
 box.querySelectorAll('[data-prepared-job]').forEach(button=>button.onclick=()=>openManualJob(button.dataset.preparedJob));
 box.querySelectorAll('.history-item').forEach((card,index)=>{
  const record=preparationRecords[index];if(record.status!=='needs_attention'||!record.retry_safe)return;
  const button=document.createElement('button');button.type='button';button.className='button secondary';button.textContent='Continue preparation';
  button.onclick=async()=>{button.disabled=true;try{await api('/api/prepare-application',{url:record.url,retry_id:record.preparation_id});await loadPreparations();}catch(error){$('preparation-message').textContent=error.message;}finally{button.disabled=false;}};
  card.querySelector('.actions').append(button);
 });
}
async function loadPreparations(){
 if(preparationLoading||!$('preparation-records'))return;preparationLoading=true;
 try{preparationRecords=await api('/api/prepared-applications');renderPreparationCards();}
 catch(error){$('preparation-message').textContent=error.message;}
 finally{preparationLoading=false;}
}
function renderPreparationPanel(){
 if(!$('manual-new-top')){
  const actions=document.createElement('div');actions.className='actions';actions.id='manual-new-actions';
  const button=document.createElement('button');button.id='manual-new-top';button.type='button';button.className='button primary';button.textContent='New job';button.onclick=startNewManualJob;
  actions.append(button);$('manual-section').prepend(actions);
 }
 if(!$('preparation-panel')){
  const panel=document.createElement('section');panel.id='preparation-panel';panel.className='activity-card';
  panel.innerHTML='<h2>Prepare application from link</h2><p>Paste an Indeed or LinkedIn job link. Gecko saves the job and creates its tailored resume; OpenClaw fills the application and stops for your review. You handle CAPTCHA and submit it yourself.</p><label for="preparation-url">Job posting link</label><input id="preparation-url" type="url" placeholder="https://www.indeed.com/viewjob?jk=…"><p><button type="button" id="prepare-application" class="button primary">Prepare application</button></p><p id="preparation-message" role="status">Preparation continues if you refresh this page. Progress and Stop are in Gecko activity.</p><div id="preparation-records" aria-live="polite"></div>';
  $('manual-new-actions').after(panel);
  $('prepare-application').onclick=async()=>{
   if(preparationDispatching)return;
   const input=$('preparation-url');if(!input.value.trim()||!input.validity.valid){$('preparation-message').textContent='Paste a valid Indeed or LinkedIn job link first.';input.focus();return;}
   preparationDispatching=true;$('prepare-application').disabled=true;
   try{await api('/api/prepare-application',{url:input.value.trim()});$('preparation-message').textContent='Preparation started. You can leave this page; Gecko will stop before submission.';input.value='';await loadPreparations();}
   catch(error){$('preparation-message').textContent=error.message;}
   finally{preparationDispatching=false;$('prepare-application').disabled=false;}
  };
  loadPreparations();
 }
 renderPreparationCards();
}
function startNewManualJob(){
 if(manualBusy||preparationDispatching){manualMessage('Wait for the current form operation to finish, then click New job.');return;}
 const form=$('manual-form');
 manualEdit=null;manualDirty=false;manualPending=false;manualResume=null;manualResumeWatching=null;
 form.reset();form.elements.url.readOnly=false;form.elements.applied.disabled=false;form.elements.applied_date.required=false;form.elements.applied_date.value='';
 $('manual-resume-file').value='';$('manual-resume-status').textContent='No resume attached.';$('manual-resume-remove').hidden=true;
 $('manual-form-title').textContent='Add a job or application';$('manual-new').hidden=true;
 form.querySelector('p').textContent='Save this new job to your individually added jobs and All Jobs. Saving does not submit an application.';
 renderManualGeneratedResume(null);manualMessage('Ready for a new job.');
 try{localStorage.removeItem(manualDraftKey);}catch{}
 $('preparation-url').value='';$('preparation-message').textContent='Paste your new Indeed or LinkedIn job link to get started.';
 renderManualTable();$('preparation-url').focus();$('manual-new-top').scrollIntoView({block:'start',behavior:'instant'});
}
setInterval(()=>{if($('preparation-panel')&&!$('manual-section').hidden)loadPreparations();},5000);
let manualResumeWatching=null;
async function createManualResumeFromProfile(){
 const form=$('manual-form');if(!form||manualBusy)return;
 if(form.elements.applied.checked){manualMessage('This application is marked submitted. Review its existing resume before creating another.');return;}
 for(const key of ['url','Company','Job Title']){const input=form.elements.namedItem(key);if(!input.value.trim()||input.validity&&!input.validity.valid){manualMessage('Enter '+(key==='url'?'the job posting link':key)+' in this profile first.');input.focus();return;}}
 const payload=Object.fromEntries(new FormData(form));payload.applied=false;
 if(manualEdit){payload.id=manualEdit.id;payload.version=manualEdit.version;}
 if(typeof manualResume!=='undefined'&&manualResume)payload.resume_token=manualResume.token;
 manualPending=false;storeManualDraft(form);manualBusy=true;
 const disabled=Array.from(form.elements).map(input=>[input,input.disabled]);disabled.forEach(([input])=>input.disabled=true);
 let started=false,postingWarning='';
 try{
  const activity=await api('/api/activity');
  if(activity.busy||activity.operation?.status==='running')throw Error('Gecko is running. Your profile is preserved; try again when it finishes.');
  const assertAvailable=job=>{
   if(job.applied)throw Error('This job is already recorded as applied. No resume was regenerated.');
   if(String(job.fields['Resume Created']||'').trim()||String(job.fields['Resume Link']||'').trim())throw Error('This job already has a completed or linked resume. Review the existing file; regeneration is blocked.');
   if(['no','reject','delete / reject'].includes(String(job.fields['Apply?']||'').trim().toLowerCase()))throw Error('This job is marked Do not apply. Review its approval before creating a resume.');
  };
  if(manualEdit){const original=await api('/api/job?id='+encodeURIComponent(manualEdit.id));if(original.version!==manualEdit.version)throw Error('This job changed. Refresh and reopen it before creating a resume.');assertAvailable(original);}
  manualMessage('Checking the job posting for additional information…');
  let imported;
  try{
   await api('/api/manual-import',{url:payload.url});
   const deadline=Date.now()+440000;
   do{imported=await api('/api/manual-import');if(imported.status!=='running')break;if(Date.now()>deadline)throw Error('The posting check timed out.');await new Promise(resolve=>setTimeout(resolve,2000));}while(true);
   if(imported.status!=='ready')throw Error(imported.error||'The job posting could not be read.');
   if(imported.url!==payload.url)throw Error('The posting check returned a different link.');
  }catch(error){postingWarning='The posting could not be refreshed; using the saved job description. ';imported=null;}
  if(imported){
   const details=imported.details||{},normalize=value=>String(value||'').trim().replace(/\s+/g,' ').toLowerCase();
   if(normalize(details.Company)!==normalize(payload.Company)||normalize(details['Job Title'])!==normalize(payload['Job Title']))throw Error('The posting company or title differs from this profile. Review the posting before creating a resume; your saved details were preserved.');
   for(const key of manualFields)if(!['Notes','description','Company','Job Title'].includes(key)&&!String(payload[key]||'').trim()&&details[key])payload[key]=details[key];
   const saved=String(payload.description||'').trim(),latest=String(details.description||'').trim();
   payload.description=!saved?latest:latest&&!saved.includes(latest)?saved+'\n\nAdditional information from the current job posting:\n'+latest:saved;
  }
  if(String(payload.description||'').trim().length<600)throw Error('A complete job description is still needed. Add it to this profile and click Create resume again.');
  if(payload.description.length>30000)throw Error('The combined job description is too long. Review and shorten it in this profile before creating a resume.');
  for(const key of manualFields)if(key in payload)form.elements.namedItem(key).value=payload[key];
  manualMessage(postingWarning+'Saving this job profile and preparing its tailored resume…');
  const saved=await api('/api/manual',payload);
  let job=await api('/api/job?id='+encodeURIComponent(saved.id));
  manualEdit={id:job.id,version:job.version};manualDirty=false;assertAvailable(job);
  if(!job.eligible)throw Error('This saved job needs eligibility review before creating a resume.');
  if(!job.can_generate){job=await api('/api/edit',{id:job.id,version:job.version,action:'approve'});manualEdit={id:job.id,version:job.version};}
  if(!job.can_generate)throw Error('This job is not ready for resume generation. Review its eligibility and approval.');
  const index=state.jobs.findIndex(current=>current.id===job.id);if(index<0)state.jobs.push(job);else state.jobs[index]={...state.jobs[index],...job};
  if(!(state.manualIds||[]).includes(job.id))state.manualIds=[...(state.manualIds||[]),job.id];
  $('manual-form-title').textContent='Edit job '+job.id+' · '+job.fields.Company;$('manual-new').hidden=false;
  form.elements.url.readOnly=true;renderManualTable();renderManualGeneratedResume(job);
  const operation=await api('/api/run',{kind:'resume',id:job.id,version:job.version,manual_upload:true});
  state.activity={...activity,operation,busy:true};manualResumeWatching=job.id;started=true;
  manualMessage(postingWarning+'Creating the tailored resume for job '+job.id+'. It will attach here automatically after validation. Progress is available in Gecko activity.');
  notify('Creating the tailored resume for job '+job.id+'.');
 }catch(error){manualMessage(error.message);}
 finally{
  disabled.forEach(([input,value])=>input.disabled=value);manualBusy=false;
  if($('manual-create-resume'))$('manual-create-resume').disabled=started;
  if(started){try{localStorage.removeItem(manualDraftKey);}catch{}}else storeManualDraft(form);
 }
}



const manualFields=['Company','Job Title','Source','Location','Salary','Work Arrangement','Employment Type','Personal priority','Date Posted','Notes','description'];
let manualBusy=false;
let manualPending=false;
let manualEdit=null;
let manualDirty=false;
let manualResume=null;
const manualDraftKey='gecko.manual-intake.draft.v1';
function manualMessage(message){
 for(const id of ['manual-status','manual-save-status'])if($(id))$(id).textContent=message;
}
function storeManualDraft(form){
 try{localStorage.setItem(manualDraftKey,JSON.stringify({fields:Object.fromEntries(new FormData(form)),applied:form.elements.applied.checked,pending:manualPending,edit:manualEdit,resume:manualResume}));}catch{/* The form remains usable if browser storage is unavailable. */}
}
async function saveManualForm(form){
 if(manualBusy)return;
 form.elements.applied_date.required=form.elements.applied.checked;
 const invalid=Array.from(form.elements).find(el=>el.willValidate&&!el.validity.valid);
 if(invalid){manualMessage('Not saved: '+(invalid.name==='url'?'Enter the job posting link.':invalid.name==='applied_date'?'Enter the date you applied.':'Enter '+invalid.name+'.'));invalid.focus();return;}
 const payload=Object.fromEntries(new FormData(form));payload.applied=form.elements.applied.checked;if(manualEdit){payload.id=manualEdit.id;payload.version=manualEdit.version;}if(manualResume)payload.resume_token=manualResume.token;
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
  manualResume=null;form.reset();$('manual-resume-status').textContent='No resume attached.';$('manual-resume-remove').hidden=true;form.elements.applied_date.value=today();form.elements.applied_date.required=false;
  await refresh();manualMessage('Saved: job ID '+saved.id+' appears under Your individually added jobs and in All Jobs. Status: '+(saved.applied?'Applied':'Not applied')+'.');notify('Job '+saved.id+' saved and verified.');
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
function cleanManualImport(details,url){
 const clean={...details};
 try{const host=new URL(url).hostname.toLowerCase();if((host==='indeed.com'||host.endsWith('.indeed.com'))&&/^https?:/.test(clean.Source||''))clean.Source='Indeed';}catch{}
 for(const key of ['Salary','description'])if(typeof clean[key]==='string')clean[key]=clean[key].replaceAll('â€“','–').replaceAll('â€”','—').replaceAll('â€™',"'");
 return clean;
}
function renderManual(){
 const root=$('manual-section');
 $('page-subtitle').textContent='Add a job you found yourself. Review the details, then save it to both this list and All Jobs.';
 if(!root.dataset.built){
  root.dataset.built='yes';
  root.innerHTML='<form id="manual-form" class="activity-card" novalidate><div class="section-heading"><h2 id="manual-form-title">Add a job or application</h2><button type="button" id="manual-create-resume" class="button primary">Create resume</button></div><p>Saving assigns a unique job ID and adds the job below and in All Jobs as Not applied.<br>Saving does not submit an application. Use Save and applied only after you have submitted it.</p><label>Job posting link<input name="url" type="url" required placeholder="https://www.indeed.com/viewjob?jk=…"></label><button type="button" id="manual-fetch" class="button secondary">Auto-fill with OpenClaw</button><p id="manual-status" role="status">You can also enter details yourself. Review imported information before saving.</p><div class="manual-fields">'+manualFields.map(k=>'<label>'+esc(k==='description'?'Job description':k)+(k==='Notes'||k==='description'?'<textarea name="'+k+'"></textarea>':'<input name="'+k+'" '+(['Company','Job Title'].includes(k)?'required':'')+(k==='Date Posted'?' type="date"':'')+'>')+'</label>').join('')+'<div class="manual-resume"><span>Resume attachment</span><p><button type="button" class="button secondary" id="manual-resume-attach">Attach resume</button> <button type="button" class="text-button" id="manual-resume-remove" hidden>Remove</button></p><input id="manual-resume-file" type="file" accept=".pdf,.docx" hidden><p id="manual-resume-status" role="status">No resume attached.</p><p class="subtext">PDF or DOCX, up to 10 MB. Attached when you save this job.</p></div></div><div id="manual-generated-resume" class="detail-section" aria-live="polite" hidden></div><label><input type="checkbox" name="applied"> I already submitted this application</label><label>Application date<input type="date" name="applied_date"></label><p id="manual-save-status" class="manual-save-status" role="status" aria-live="polite"></p><div class="actions"><button type="submit" class="button primary" id="manual-save">Save job</button><button type="button" class="button primary" id="manual-save-applied">Save and applied</button><button type="button" class="button secondary" id="manual-new" hidden>Add another job</button></div></form><div id="manual-table"></div>';
  const form=$('manual-form');form.elements.applied_date.value=today();
  $('manual-save-applied').onclick=()=>{if(manualBusy)return;form.elements.applied.checked=true;if(!form.elements.applied_date.value)form.elements.applied_date.value=today();saveManualForm(form);};
  $('manual-new').onclick=startNewManualJob;
  form.onsubmit=e=>{e.preventDefault();saveManualForm(form);};
  form.oninput=()=>{manualDirty=true;const wasPending=manualPending;manualPending=false;form.elements.applied_date.required=form.elements.applied.checked;storeManualDraft(form);if(wasPending){manualMessage('Draft changed. Click Save job to save these updated details.');renderManualTable();}};
  try{const draft=JSON.parse(localStorage.getItem(manualDraftKey)||'null');if(draft?.fields){manualEdit=draft.edit||null;manualDirty=true;if(manualEdit){$('manual-form-title').textContent='Edit job '+manualEdit.id;form.elements.url.readOnly=true;$('manual-new').hidden=false;}manualResume=draft.resume||null;if(manualResume){$('manual-resume-status').textContent=manualResume.name;$('manual-resume-remove').hidden=false;}draft.fields=cleanManualImport(draft.fields,draft.fields.url);for(const [key,value] of Object.entries(draft.fields)){const el=form.elements.namedItem(key);if(el&&el.type!=='checkbox')el.value=value;}form.elements.applied.checked=!!draft.applied;form.elements.applied_date.required=!!draft.applied;manualPending=!!draft.pending;manualMessage(manualPending?'Pending save restored. This job will save when Gecko finishes.':'Your unsaved draft was restored. Review it and click Save job.');}}catch{}
  $('manual-create-resume').onclick=createManualResumeFromProfile;
  $('manual-resume-attach').onclick=()=>$('manual-resume-file').click();
  $('manual-resume-remove').onclick=()=>{manualResume=null;$('manual-resume-file').value='';$('manual-resume-status').textContent='No resume attached.';$('manual-resume-remove').hidden=true;manualPending=false;storeManualDraft(form);};
  $('manual-resume-file').onchange=async()=>{
   const file=$('manual-resume-file').files[0];if(!file||manualBusy)return;
   manualPending=false;manualBusy=true;$('manual-save').disabled=true;$('manual-resume-attach').disabled=true;$('manual-resume-remove').disabled=true;
   $('manual-resume-status').textContent='Uploading resume…';
   try{
    if(!/\.(pdf|docx)$/i.test(file.name)||file.size>10*1024*1024)throw Error('Choose a PDF or DOCX resume no larger than 10 MB.');
    const upload=()=>fetch('/api/manual-resume',{method:'POST',headers:{'Content-Type':'application/octet-stream','X-Gecko-Token':state.token,'X-Filename':encodeURIComponent(file.name)},body:file});
    let response=await upload(),result=await response.json();
    if(response.status===403&&result.error==='Reload Gecko before making changes.'){state.token=(await api('/api/jobs')).token;response=await upload();result=await response.json();}
    if(!response.ok)throw Error(result.error||'Upload failed.');
    manualResume=result;$('manual-resume-status').textContent=result.name+' — ready to attach when you save.';$('manual-resume-remove').hidden=false;
   }catch(err){$('manual-resume-status').textContent=err.message+(manualResume?' Keeping '+manualResume.name+'.':'');}
   finally{manualBusy=false;$('manual-save').disabled=false;$('manual-resume-attach').disabled=false;$('manual-resume-remove').disabled=false;storeManualDraft(form);}
  };
  $('manual-fetch').onclick=async()=>{
   if(manualBusy)return;const url=form.elements.url.value;if(!url){manualMessage('Enter a posting link first.');return;}
   manualPending=false;storeManualDraft(form);manualBusy=true;Array.from(form.elements).forEach(el=>el.disabled=true);manualMessage('OpenClaw is reading the posting. This can take a few minutes…');
   try{await api('/api/manual-import',{url});let result;const deadline=Date.now()+440000;do{await new Promise(r=>setTimeout(r,2000));result=await api('/api/manual-import');if(Date.now()>deadline)throw Error('Import is taking too long. You can enter the details manually.');}while(result.status==='running');if(result.status!=='ready')throw Error(result.error||'Import did not finish.');if(result.url!==url)throw Error('The import link changed. Please try again.');result.details=cleanManualImport(result.details,url);for(const key of manualFields)if(result.details[key])form.elements.namedItem(key).value=result.details[key];manualMessage('Details imported. Review and correct them, then save.');}catch(err){manualMessage(err.message);}finally{manualBusy=false;Array.from(form.elements).forEach(el=>el.disabled=false);storeManualDraft(form);}
  };
 }
 const resumeOperation=state.activity?.operation;
 if($('manual-create-resume')){$('manual-create-resume').disabled=manualBusy||state.activity?.busy||resumeOperation?.status==='running';$('manual-create-resume').textContent=resumeOperation?.kind==='resume'&&String(resumeOperation.job_id)===manualEdit?.id&&resumeOperation.status==='running'?'Creating resume…':'Create resume';}
 if(manualResumeWatching&&String(resumeOperation?.job_id)===manualResumeWatching&&resumeOperation.status!=='running'){manualMessage(resumeOperation.status==='complete'?'Tailored resume completed and attached to job '+manualResumeWatching+'.':'Resume '+resumeOperation.status+'. '+(resumeOperation.error||'Review Gecko activity.'));manualResumeWatching=null;}
 if(manualEdit)renderManualGeneratedResume(state.jobs.find(j=>j.id===manualEdit.id));
 renderManualTable();
 renderPreparationPanel();
}
function renderManualTable(){
 const cols=['ID','Company','Job Title','Source','Location','Applied Date','Status'];
 const rows=state.jobs.filter(j=>(state.manualIds||[]).includes(j.id)).map(j=>({...j.fields,ID:j.id,Status:j.applied?'Applied':'Not applied','Applied Date':j.fields['Applied Date']||j.meta.applied_at||''}));
 const shown=rows.filter(r=>cols.every(k=>String(r[k]||'').toLowerCase().includes((manualFilters[k]||'').toLowerCase()))).sort((a,b)=>String(a[manualSort.key]||'').localeCompare(String(b[manualSort.key]||''),undefined,{numeric:true})*manualSort.direction);
 const pendingForm=$('manual-form');
 const pendingNotice=manualPending?'<div class="manual-save-status" role="status"><strong>Pending save: '+esc(pendingForm.elements.namedItem('Company').value)+' — '+esc(pendingForm.elements.namedItem('Job Title').value)+'</strong><br>This entry is preserved in this browser. It will receive its job ID and appear in both lists after Gecko finishes and the save is verified.</div>':'';
 $('manual-table').innerHTML=pendingNotice+'<div class="section-heading"><h2>Your individually added jobs</h2><span>'+shown.length+' of '+rows.length+(manualPending?' saved · 1 pending':'')+'</span></div><p>Open a job to record an application or update its next steps. All Jobs uses the same record.</p><div class="table-wrap"><table><thead><tr>'+cols.map(k=>'<th>'+esc(k)+' <button type="button" class="column-filter" data-manual-focus="'+k+'" aria-label="Filter '+k+'">▽</button><button type="button" class="column-filter" data-manual-sort="'+k+'" aria-label="Sort '+k+'">↕</button><input data-manual-filter="'+k+'" aria-label="Search '+k+'" value="'+esc(manualFilters[k]||'')+'" placeholder="Filter…"></th>').join('')+'</tr></thead><tbody>'+shown.map(r=>'<tr data-workspace-job="'+esc(r.ID)+'" data-workspace-label="'+esc(r.Company)+' — '+esc(r['Job Title'])+'">'+cols.map(k=>'<td>'+(k==='Job Title'?'<button class="text-button" data-manual-open="'+esc(r.ID)+'">'+esc(r[k])+'</button>':k==='Status'?'<span class="manual-application-status '+(r.Status==='Applied'?'applied':'not-applied')+'">'+esc(r.Status)+'</span>':esc(r[k]||'—'))+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>'+(!rows.length?'<p>'+(manualPending?'No saved records yet. Your pending entry is shown above.':'No individually added jobs yet. Add your first posting above.')+'</p>':'');
 const root=$('manual-table');root.querySelectorAll('[data-manual-open]').forEach(b=>b.onclick=()=>openManualJob(b.dataset.manualOpen));bindWorkspaceRows(root,row=>openManualJob(row.dataset.workspaceJob));
 root.querySelectorAll('[data-manual-filter]').forEach(input=>input.oninput=()=>{const key=input.dataset.manualFilter,caret=input.selectionStart;manualFilters[key]=input.value;renderManualTable();const next=root.querySelector('[data-manual-filter="'+key+'"]');next.focus();next.setSelectionRange(caret,caret);});
 root.querySelectorAll('[data-manual-focus]').forEach(b=>b.onclick=()=>root.querySelector('[data-manual-filter="'+b.dataset.manualFocus+'"]').focus());
 root.querySelectorAll('[data-manual-sort]').forEach(b=>b.onclick=()=>{manualSort={key:b.dataset.manualSort,direction:manualSort.key===b.dataset.manualSort?-manualSort.direction:1};renderManualTable();});
}


async function openManualJob(id,afterSave=false){
 if(manualBusy&&!afterSave)return;
 if(manualDirty){manualMessage('Save your current changes before opening another job.');return;}
 manualMessage('Opening saved job '+id+'…');
 try{
  const job=await api('/api/job?id='+encodeURIComponent(id));
  if(!(state.manualIds||[]).includes(job.id))throw Error('This job is not in your individually added list.');
  if(manualDirty){manualMessage('Your draft changed while this job was loading. Save it before opening another job.');return;}
  const form=$('manual-form');
  manualEdit={id:job.id,version:job.version};manualPending=false;
  if(typeof manualResume!=='undefined'){manualResume=null;$('manual-resume-status').innerHTML=job.attached_resume?'<a href="/api/manual-resume?id='+encodeURIComponent(job.id)+'&amp;view=1" target="_blank" rel="noopener noreferrer">'+esc(job.attached_resume.name)+'</a><br><a class="button secondary" href="/api/manual-resume?id='+encodeURIComponent(job.id)+'&amp;view=1" target="_blank" rel="noopener noreferrer">Open saved resume</a> <a href="/api/manual-resume?id='+encodeURIComponent(job.id)+'">Download</a>':'No resume attached.';$('manual-resume-remove').hidden=true;}
  form.elements.url.value=job.url;form.elements.url.readOnly=true;
  for(const key of manualFields)form.elements.namedItem(key).value=key==='description'?(job.description||''):key==='Notes'?job.notes:(job.fields[key]||'');
  form.elements.applied.checked=job.applied;form.elements.applied.disabled=job.applied;
  form.elements.applied_date.value=String(job.fields['Applied Date']||job.meta.applied_at||today()).slice(0,10);
  form.elements.applied_date.required=job.applied;
  $('manual-form-title').textContent='Edit job '+job.id+' · '+job.fields.Company;
  form.querySelector('p').textContent='Continue your saved job or application. Saving updates this same record in this list and All Jobs.';
  $('manual-new').hidden=false;
  renderManualGeneratedResume(job);
  manualMessage('Job '+job.id+' loaded. Save job keeps its current application status; Save and applied records your completed application.');
  manualDirty=false;
  window.scrollTo({top:0,left:0,behavior:'instant'});
 }catch(error){manualMessage('Could not open this job: '+error.message);}
}


function renderManualGeneratedResume(job){
 const box=$('manual-generated-resume');if(!box)return;
 box.hidden=!job;
 if(!job){box.innerHTML='';return;}
 const created=String(job.fields['Resume Created']||'').trim().toLowerCase()==='x';
 if(created&&job.resume_available){
  box.innerHTML='<h3>Tailored resume attached</h3><p>'+esc(job.resume_name)+'</p><a class="button secondary" href="/api/resume?id='+encodeURIComponent(job.id)+'">Download tailored resume</a><p class="subtext">Automatically linked to job '+esc(job.id)+' when Gecko completed and verified this resume.</p>';
 }else{
  box.innerHTML='<h3>Tailored resume</h3><p>'+(created?'Resume creation is recorded, but its linked file needs review. Gecko will preserve the existing completed resume.':'Your tailored resume will attach here automatically after Gecko finishes and validates it.')+'</p>';
 }
}
