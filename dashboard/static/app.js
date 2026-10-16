'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const state = {jobs:[],view:'today',page:0,token:'',selected:null,activity:null,loading:false};
const PAGE_SIZE = 15;
const today = () => new Intl.DateTimeFormat('en-CA',{timeZone:'America/Denver',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
const dateText = value => value ? new Date(value).toLocaleString('en-US',{timeZone:'America/Denver',month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}) + ' MT' : 'Not recorded';
const due = job => job.meta.follow_up && job.meta.follow_up <= today() && !['Closed','Offer','Declined'].includes(job.stage);
const isReply = job => job.applied && !!job.fields.Response && !['Closed','Offer'].includes(job.stage);
function nextAction(j){
 if(due(j)) return 'Follow-up due';
 if(isReply(j)) return 'Review employer response';
 if(j.meta.deadline && j.meta.deadline < today() && !j.applied) return 'Deadline passed · review';
 if(j.meta.deadline && !j.applied) return 'Deadline ' + j.meta.deadline;
 if(j.stage==='Declined' || j.stage==='Closed') return 'No action needed';
 if(j.stage==='Offer') return 'Review offer';
 if(j.stage==='Interview') return 'Prepare for interview';
 if(j.applied) return j.meta.follow_up ? 'Follow up ' + j.meta.follow_up : 'Set a follow-up';
 if(j.resume_available) return 'Review resume & apply';
 if(j.issues.some(x=>x.startsWith('Resume'))) return 'Review resume link';
 if(j.can_generate) return 'Prepare tailored resume';
 return j.eligible ? 'Review opportunity' : 'Review eligibility';
}
function priority(j){if(['Closed','Declined','Offer'].includes(j.stage))return 99;return due(j)?0:isReply(j)?1:j.meta.deadline&&!j.applied?2:j.stage==='Resume ready'?3:j.can_generate?4:j.stage==='Review'&&j.eligible?5:j.stage==='Review'?6:9;}
async function api(path, body){
 const response = await fetch(path, body ? {method:'POST',headers:{'Content-Type':'application/json','X-Gecko-Token':state.token},body:JSON.stringify(body)} : {});
 const data = await response.json();
 if(!response.ok) throw new Error(data.error || 'Could not complete this request.');
 return data;
}
function notify(message){$('toast').textContent=message;$('toast').hidden=false;clearTimeout(state.toastTimer);state.toastTimer=setTimeout(()=>$('toast').hidden=true,6500);}
function banner(message){$('banner').textContent=message;$('banner').hidden=!message;}
async function refresh(){
 if(document.querySelector('.dirty')){notify('Save your edited rows before refreshing.');return;}
 if(state.loading) return;
 state.loading=true;$('refresh').disabled=true;$('refresh').textContent='Refreshing…';
 try{
  const data=await api('/api/jobs');state.jobs=data.jobs;state.runIds=data.run_ids||[];state.columns=data.columns||[];state.token=data.token;state.activity=data.activity;state.refreshed=data.refreshed_at;
  $('freshness').textContent='Updated '+dateText(data.refreshed_at);$('footer-time').textContent='Tracker refreshed '+dateText(data.refreshed_at);
  $('sheet-link').href=data.sheet_url;$('sheet-link').hidden=!data.sheet_url;banner('');
  const prior=$('source-filter').value;
  $('source-filter').innerHTML='<option value="">All sources</option>'+[...new Set(state.jobs.map(j=>j.fields.Source).filter(Boolean))].sort().map(s=>`<option>${esc(s)}</option>`).join('');
  $('source-filter').value=prior;render();
 }catch(error){banner('Your local workspace could not be refreshed. '+error.message+(state.jobs.length?' Displayed jobs are from the last successful refresh.':''));$('freshness').textContent='Refresh failed · data may be stale';}
 finally{state.loading=false;$('refresh').disabled=false;$('refresh').textContent='↻ Refresh';}
}
function setView(view){if(document.querySelector('.dirty')){notify('Save your edited rows before changing views.');return;}state.view=view;state.page=0;$('stage-filter').value='';$('search').value='';location.hash=view;render();}
const viewNames={today:'Today',jobs:'All jobs',applications:'Applications',resumes:'Resumes',activity:'Gecko activity',tracker:'Editable tracker'};
function render(){
 document.querySelectorAll('[data-view]').forEach(b=>b.classList.toggle('active',b.dataset.view===state.view));
 $('crumb').textContent=viewNames[state.view];
 $('page-title').innerHTML=state.view==='today'?'Your next move.':esc(viewNames[state.view]);
 const subtitles={today:'Your opportunities, applications, and next steps. All together.',jobs:'Find the roles worth your time. Review each one on your terms.',applications:'Every application, every conversation, every next step.',resumes:'Your tailored resumes, connected to the right opportunity.',activity:'Know what Gecko is doing, and what needs your attention.'};
 $('page-subtitle').textContent=subtitles[state.view]||'Your columns, your notes, your complete job tracker.';
 $('tracker-section').hidden=state.view!=='tracker';
 $('today-intro').hidden=state.view!=='today';$('work-section').hidden=['activity','tracker'].includes(state.view);$('activity-section').hidden=state.view!=='activity';
 const active=state.jobs.filter(j=>!['Closed','Declined'].includes(j.stage));
 const stats=[['Opportunities',active.filter(j=>!j.applied).length,'Ready for your review','jobs'],['Resumes ready',active.filter(j=>!j.applied&&j.resume_available).length,'Your next applications','resumes'],['Applications',state.jobs.filter(j=>j.applied).length,'Every step, in one place','applications'],['Follow-ups due',state.jobs.filter(due).length,'Keep the conversation going','today']];
 $('stats').innerHTML=stats.map(([label,n,note,view])=>`<button class="stat" data-stat-view="${view}"><span class="stat-label">${label}</span><strong>${state.refreshed?n:'—'}</strong><small>${note}</small></button>`).join('');
 document.querySelectorAll('[data-stat-view]').forEach(b=>b.onclick=()=>setView(b.dataset.statView));
 const focus=[...active].sort((a,b)=>priority(a)-priority(b)).find(j=>priority(j)<9);
 $('focus-title').textContent=focus?nextAction(focus):state.refreshed?'Your queue is clear.':'Connect to your tracker.';
 $('focus-copy').textContent=focus?`${focus.fields.Company} · ${focus.fields['Job Title']}`:state.refreshed?'Explore all jobs or run Gecko to discover fresh opportunities.':'Refresh to load your jobs from your workspace.';
 $('focus-button').textContent=focus?'Open opportunity →':'View all jobs →';$('focus-button').onclick=()=>focus?openJob(focus.id):setView('jobs');
 $('list-title').textContent={today:'Your action queue',jobs:'All opportunities',applications:'Your application pipeline',resumes:'Your resume library',activity:''}[state.view];
 $('list-caption').textContent=state.view==='today'?'Follow-ups, replies, prepared resumes, and jobs to review.':'Select an opportunity to open its complete workspace.';
 if(state.view==='tracker') return renderTracker();
 if(state.view==='activity') return renderActivity();
 let list=state.jobs.filter(j=>state.view==='today'?priority(j)<9:state.view==='applications'?j.applied:state.view==='resumes'?!!(j.fields['Resume Created']||j.fields['Resume Link']):true);
 const query=$('search').value.trim().toLowerCase(),stage=$('stage-filter').value,source=$('source-filter').value;
 list=list.filter(j=>(!stage||j.stage===stage)&&(!source||j.fields.Source===source)&&(!query||[j.fields.Company,j.fields['Job Title'],j.fields.Location,j.fields.Source,j.id].join(' ').toLowerCase().includes(query)));
 list=list.filter(j=>GeckoFilters.matches(j,columnFilters,nextAction(j)));
 renderFilterSummary();
 const sort=$('sort').value;
 list.sort((a,b)=>sort==='company'?String(a.fields.Company).localeCompare(String(b.fields.Company)):sort==='newest'?String(b.fields['Date Found']).localeCompare(String(a.fields['Date Found'])):priority(a)-priority(b)||String(b.fields['Date Found']).localeCompare(String(a.fields['Date Found'])));
 state.page=Math.max(0,Math.min(state.page,Math.ceil(list.length/PAGE_SIZE)-1));
 $('result-count').textContent=list.length+' opportunities';
 $('jobs').innerHTML=list.slice(state.page*PAGE_SIZE,(state.page+1)*PAGE_SIZE).map(j=>`<tr><td><div class="opportunity"><span class="company-icon">${esc(String(j.fields.Company||'?').slice(0,2).toUpperCase())}</span><div><button class="job-link" data-job="${esc(j.id)}" ${!j.editable?'disabled':''}>${esc(j.fields['Job Title']||'Untitled opportunity')}</button><span class="subtext">${esc(j.fields.Company)} <span>·</span> ${esc(j.fields.Source)}${!j.editable?' · Tracker identity needs review':''}</span></div></div></td><td>${esc(j.fields.Location||'Location not listed')}<span class="subtext">${esc(j.fields.Salary||j.fields['Work Arrangement']||'Salary not listed')}</span></td><td><span class="badge ${j.applied?'applied':j.resume_available?'ready':j.stage==='Review'?'warn':''}">${esc(j.stage)}</span></td><td><span class="next-action">${esc(nextAction(j))}</span></td><td><button class="arrow" data-job="${esc(j.id)}" aria-label="Open ${esc(j.fields.Company)} job" ${!j.editable?'disabled':''}>↗</button></td></tr>`).join('');
 $('empty').hidden=!!list.length;$('empty').textContent=state.refreshed?'No opportunities match this view. Try another filter or view all jobs.':'Loading your workspace…';
 $('page-count').textContent=list.length?`${state.page*PAGE_SIZE+1}–${Math.min((state.page+1)*PAGE_SIZE,list.length)} of ${list.length}`:'0 results';
 $('prev').disabled=state.page===0;$('next').disabled=(state.page+1)*PAGE_SIZE>=list.length;
 document.querySelectorAll('[data-job]').forEach(b=>b.onclick=()=>openJob(b.dataset.job));
}
async function openJob(id){
 $('job-detail').innerHTML='<div class="loading">Opening your job workspace…</div>';
 if(!$('job-dialog').open)$('job-dialog').showModal();
 try{const job=await api('/api/job?id='+encodeURIComponent(id));state.selected=job;renderDetail(job);}catch(error){$('job-detail').innerHTML=`<p class="error-inline">${esc(error.message)}</p>`;}
}
function renderDetail(j){
 const f=j.fields,meta=j.meta,e=j.evaluation;
 $('job-detail').innerHTML=`<div class="job-header"><span class="badge">${esc(j.stage)}</span><h2 id="job-title">${esc(f['Job Title'])}</h2><p>${esc(f.Company)} · ${esc(f.Location||'Location not listed')} · ${esc(f.Source)} · ID ${esc(j.id)}</p></div><div class="actions">${j.url?`<a class="button primary" href="${esc(j.url)}" target="_blank" rel="noopener noreferrer">Open application page ↗</a>`:''}${j.resume_available?'<button class="button secondary" id="open-resume">Open resume in Word</button>':''}${!j.applied?`<button class="button secondary" id="approve" ${!j.eligible||String(f['Apply?']).toLowerCase()==='yes'?'disabled':''}>Approve job</button><button class="button secondary" id="decline">Decline job</button>`:''}${j.can_generate?'<button class="button primary" id="generate">Prepare resume</button>':''}${!j.applied?'<button class="button secondary" id="applied">I applied to this job</button>':''}</div><div id="detail-error" class="error-inline" role="alert"></div>${j.issues.map(issue=>`<div class="warning">${esc(issue)}</div>`).join('')}<div class="detail-grid"><div><div class="detail-section"><h3>Opportunity details</h3><div class="detail-pairs">${[['Salary',f.Salary],['Work arrangement',f['Work Arrangement']],['Employment type',f['Employment Type']],['Date posted',f['Date Posted']],['Date found',f['Date Found']],['Last job run',f['Last Updated']]].map(([k,v])=>`<div><span>${k}</span><strong>${esc(v||'Not recorded')}</strong></div>`).join('')}</div></div><div class="detail-section"><h3>Fit & eligibility</h3><p>${j.eligible?'Passes the current location, fee, and expiration checks.':'Needs eligibility review before approval.'}</p>${e?`<p>Saved match score: <strong>${esc(e.match_score??'Not scored')}</strong></p><p>${esc(e.score_reason||e.triage_reason)}</p><p class="subtext">Cached evaluation from ${esc(dateText(e.evaluated_at))}. This is a saved assessment, not a new analysis.</p>`:'<p>No saved match assessment is available for this exact posting.</p>'}</div><div class="detail-section"><h3>Job description</h3><div class="description">${esc(j.description||'No archived description is available for this exact posting. Open the application page to review the current requirements.')}</div></div><div class="detail-section"><h3>Resume</h3><p>${esc(j.resume_name||'No verified local resume is linked to this job.')}</p>${j.resume_available?`<a href="/api/resume?id=${encodeURIComponent(j.id)}" class="button secondary">Download DOCX</a><p class="subtext">Existing tracker completion is shown here; this dashboard has not rerun historical Word validation.</p>`:''}</div></div><div><form id="details-form" class="detail-section"><h3>Notes & next steps</h3><label for="notes">Your notes</label><textarea id="notes">${esc(j.notes)}</textarea><label for="follow-up">Follow-up date</label><input id="follow-up" type="date" value="${esc(meta.follow_up||'')}"><label for="deadline">Application deadline (if known)</label><input id="deadline" type="date" value="${esc(meta.deadline||'')}">${j.applied?`<label for="application-stage">Application stage</label><select id="application-stage">${['Applied','Interview','Offer','Closed'].map(s=>`<option ${j.stage===s?'selected':''}>${s}</option>`).join('')}</select>`:''}<p class="subtext">Dates and history are saved in your local workspace. Existing notes are preserved.</p><button class="button primary" type="submit">Save changes</button></form><div class="detail-section"><h3>Employer response</h3><p>${esc(f.Response||'No response recorded.')}</p></div><div class="detail-section"><h3>Activity history</h3>${j.history.length?[...j.history].reverse().map(item=>`<div class="history-item">${esc(({approve:'Job approved',decline:'Job declined',applied:'Application recorded',details:'Notes or next steps updated'})[item.action]||item.action)}${item.stage?' · '+esc(item.stage):''}${item.follow_up?' · Follow-up '+esc(item.follow_up):''}<small>${esc(dateText(item.at))}</small></div>`).join(''):'<p>No dashboard activity recorded yet. Earlier activity is not inferred.</p>'}</div></div></div>`;
 $('details-form').onsubmit=event=>{event.preventDefault();edit('details',{notes:$('notes').value,follow_up:$('follow-up').value,deadline:$('deadline').value,stage:$('application-stage')?.value||''});};
 if($('approve'))$('approve').onclick=()=>edit('approve');
 if($('decline'))$('decline').onclick=()=>edit('decline');
 if($('applied'))$('applied').onclick=()=>edit('applied');
 if($('open-resume'))$('open-resume').onclick=async()=>{try{await api('/api/open-resume',{id:j.id});notify('Resume opened in your default Word document app.');}catch(error){$('detail-error').textContent=error.message;}};
 if($('generate'))$('generate').onclick=async()=>{await startRun({kind:'resume',id:j.id,version:j.version});};
}
async function edit(action, extras={}){
 const j=state.selected;const buttons=[...$('job-detail').querySelectorAll('button')];buttons.forEach(b=>b.disabled=true);$('detail-error').textContent='Saving and verifying in your local database…';
 try{const result=await api('/api/edit',{id:j.id,version:j.version,action,...extras});state.selected={...j,...result};renderDetail(state.selected);notify('Saved and verified in your local database.');await refresh();}
 catch(error){$('detail-error').textContent=error.message;buttons.forEach(b=>b.disabled=false);}
}
async function startRun(payload){
 try{const operation=await api('/api/run',payload);state.activity={...state.activity,operation,busy:true};$('run-dialog').close();$('job-dialog').close();setView('activity');notify('Gecko started. You can follow progress here.');}
 catch(error){if($('job-dialog').open)$('detail-error').textContent=error.message;else{$('run-dialog').close();banner(error.message);}}
}
function renderActivity(){
 const activity=state.activity||{},op=activity.operation,pipeline=activity.pipeline,exported=activity.export;
 const summary=op?`${op.kind==='resume'?'Tailored resume · Job '+op.job_id:'Daily Gecko workflow'+(op.job_ids?' · IDs '+op.job_ids.join(', '):'')} — ${op.status}`:'No dashboard run yet';
 $('activity-section').innerHTML=`<div class="activity-card"><span class="eyebrow">WORKSPACE OPERATIONS</span><h3>${esc(summary)}</h3><p>${activity.busy?'Gecko’s processing lock is active. Editing is paused until the run finishes.':'No Gecko processing lock is active.'}</p>${op?`<p>Started ${esc(dateText(op.started_at))}${op.finished_at?' · Finished '+esc(dateText(op.finished_at)):''}</p>${op.error?`<div class="warning">${esc(op.error)}</div>`:''}${op.log?`<p class="subtext">Local log: ${esc(op.log)}</p>`:''}`:''}</div><div class="activity-card"><span class="eyebrow">LAST CANONICAL PIPELINE RECORD</span>${pipeline?`<h3>${esc(pipeline.status)} · ${esc(pipeline.current_step||'Gecko workflow')}</h3><p>Recorded ${esc(dateText(pipeline.updated_at||pipeline.started_at))}</p><ul>${(pipeline.steps||[]).map(s=>`<li>${esc(s.name)} — ${s.exit_code===0?'completed':'stopped (exit '+esc(s.exit_code)+')'}</li>`).join('')}</ul><p class="subtext">This is the last saved pipeline record; it does not by itself indicate a currently running process.</p>`:'<p>No pipeline history is available.</p>'}</div><div class="activity-card"><h3>Google Sheets export</h3>${exported?`<p>${esc(exported.status)} · ${esc(dateText(exported.finished_at||exported.started_at))}</p>${exported.status==='verified'&&/^https:\/\/docs\.google\.com\/spreadsheets\//.test(exported.url||'')?`<a class="button secondary" href="${esc(exported.url)}" target="_blank" rel="noopener noreferrer">Open verified export ↗</a><p>${esc(exported.rows)} tracker rows exported, including custom columns.</p>`:`<p>${esc(exported.error||'Export has not been verified.')}</p>`}`:'<p>No automatic daily export recorded yet.</p>'}<p class="subtext">This is the latest export record; its time identifies which snapshot it contains. SQLite remains the main tracker.</p></div><div class="activity-card"><h3>What a daily run does</h3><p>Daily report → discovery and SQLite updates → approved eligible resumes → employer responses → database backup → final report → verified Google Sheets export.</p><p>Resume creation uses Gecko’s existing validation and completion checks. Applications are never submitted by this dashboard.</p></div>`;
}
$('date-label').textContent=new Date().toLocaleDateString('en-US',{timeZone:'America/Denver',weekday:'long',month:'long',day:'numeric',year:'numeric'}).toUpperCase();
document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>setView(b.dataset.view));
$('refresh').onclick=refresh;$('close-job').onclick=()=>$('job-dialog').close();
$('run-gecko').onclick=()=>{if(!state.runIds?.length){banner('Refresh to load the verified run scope.');return;}$('run-title').textContent='Run '+state.runIds.length+' selected jobs';$('run-scope').textContent='Only these jobs will be processed: '+state.runIds.join(', ')+'.';$('confirm-run').textContent='Start selected '+state.runIds.length+'-job run';$('run-dialog').showModal();};$('close-run').onclick=$('cancel-run').onclick=()=>$('run-dialog').close();$('confirm-run').onclick=()=>startRun({kind:'gecko'});
for(const id of ['search','stage-filter','source-filter','sort'])$(id).addEventListener(id==='search'?'input':'change',()=>{state.page=0;render();});
$('prev').onclick=()=>{state.page--;render();};$('next').onclick=()=>{state.page++;render();};
if(viewNames[location.hash.slice(1)])state.view=location.hash.slice(1);
window.addEventListener('hashchange',()=>{const view=location.hash.slice(1);if(viewNames[view]&&view!==state.view){if(document.querySelector('.dirty')){location.hash=state.view;notify('Save your edited rows before changing views.');return;}state.view=view;state.page=0;render();}});
let gridPage=0;
function renderTracker(){
 if(document.querySelector('.dirty')){notify('Save your edited rows before changing the tracker view.');return;}
 const query=$('grid-search').value.toLowerCase();
 const rows=state.jobs.filter(j=>Object.values(j.fields).join(' ').toLowerCase().includes(query));
 gridPage=Math.max(0,Math.min(gridPage,Math.ceil(rows.length/15)-1));
 const shown=rows.slice(gridPage*15,gridPage*15+15),cols=[...(state.columns||[])].sort((a,b)=>{const rank=c=>c.custom?0:['Company','Job Title'].includes(c.name)?1:c.editable?2:3;return rank(a)-rank(b);});
 $('tracker-table').innerHTML='<thead><tr><th>Save / open</th>'+cols.map(c=>`<th>${esc(c.name)}${c.custom?' · custom':''}</th>`).join('')+'</tr></thead><tbody>'+shown.map((j,i)=>`<tr data-grid-row="${i}"><td><button class="button secondary" data-save="${i}">Save row</button><button class="job-link" data-open="${i}">Open job ${esc(j.id)}</button></td>`+cols.map((c,k)=>`<td>${c.editable?`<textarea rows="2" data-col="${k}" aria-label="${esc(c.name)} for job ${esc(j.id)}">${esc(j.fields[c.name]??'')}</textarea>`:`<span title="Managed through job actions or Gecko">${esc(j.fields[c.name]??'')}</span>`}</td>`).join('')+'</tr>').join('')+'</tbody>';
 $('grid-count').textContent=`${rows.length?gridPage*15+1:0}–${Math.min(gridPage*15+15,rows.length)} of ${rows.length}`;
 $('grid-prev').disabled=gridPage===0;$('grid-next').disabled=(gridPage+1)*15>=rows.length;
 document.querySelectorAll('[data-open]').forEach(b=>b.onclick=()=>openJob(shown[+b.dataset.open].id));
 document.querySelectorAll('[data-save]').forEach(b=>b.onclick=async()=>{
  const j=shown[+b.dataset.save],changes={};b.closest('tr').querySelectorAll('[data-col]').forEach(input=>{const name=cols[+input.dataset.col].name;if(input.value!==input.dataset.originalValue)changes[name]=input.value;});
  if(!Object.keys(changes).length){$('grid-status').textContent='No changes to save.';return;}
  b.disabled=true;
  try{const saved=await api('/api/edit',{id:j.id,version:j.version,action:'cells',changes});Object.assign(j,saved);$('grid-status').textContent='Row saved and verified.';b.closest('tr').classList.remove('dirty');b.closest('tr').querySelectorAll('[data-col]').forEach(i=>i.dataset.originalValue=i.value);notify('Row saved.');}
  catch(e){$('grid-status').textContent=e.message;}finally{b.disabled=false;}
 });
 document.querySelectorAll('[data-col]').forEach(i=>{i.dataset.originalValue=i.value;i.oninput=()=>i.closest('tr').classList.add('dirty');});
}
$('grid-search').oninput=()=>{gridPage=0;renderTracker();};
$('grid-prev').onclick=()=>{gridPage--;renderTracker();};$('grid-next').onclick=()=>{gridPage++;renderTracker();};
function columnDialog(rename){if(document.querySelector('.dirty')){notify('Save your edited rows before changing columns.');return;}
 const custom=(state.columns||[]).filter(c=>c.custom);
 if(rename&&!custom.length){notify('Add a custom column first.');return;}
 $('column-title').textContent=rename?'Rename custom column':'Add column';$('column-old').hidden=!rename;$('column-old').previousElementSibling.hidden=!rename;
 $('column-old').innerHTML=custom.map(c=>`<option>${esc(c.name)}</option>`).join('');$('column-name').value=rename?custom[0].name:'';$('column-error').textContent='';$('column-dialog').showModal();
}
$('add-column').onclick=()=>columnDialog(false);$('rename-column').onclick=()=>columnDialog(true);$('column-cancel').onclick=()=>$('column-dialog').close();
$('column-old').onchange=()=>$('column-name').value=$('column-old').value;
$('column-form').onsubmit=async e=>{e.preventDefault();try{await api('/api/columns',{name:$('column-name').value,old:$('column-old').hidden?null:$('column-old').value,headers:state.columns.map(c=>c.name)});$('column-dialog').close();await refresh();notify('Columns saved.');}catch(e){$('column-error').textContent=e.message;}};
$('export-sheet').onclick=async()=>{if(document.querySelector('.dirty')){notify('Save your edited rows before exporting.');return;}const b=$('export-sheet');b.disabled=true;$('grid-status').textContent='Creating and verifying a new export tab in Google Sheets…';try{const result=await api('/api/export',{});$('export-link').href=result.url;$('export-link').hidden=false;$('grid-status').textContent=`Export verified: ${result.rows} rows. Sheets edits do not change this workspace.`;}catch(e){$('grid-status').textContent=e.message;}finally{b.disabled=false;}};
window.addEventListener('beforeunload',e=>{if(document.querySelector('.dirty')){e.preventDefault();e.returnValue='';}});
const columnFilters={opportunity:'',location:'',minimum:'',maximum:'',unknown:true,hiddenStages:[],hideApplied:false,hiddenActions:[]};
let filterColumn='';
const filterNames={opportunity:'Opportunity',salary:'Location / salary',progress:'Progress',action:'Next action'};
function hasColumnFilter(key){return key==='opportunity'?!!columnFilters.opportunity:key==='salary'?!!(columnFilters.location||columnFilters.minimum||columnFilters.maximum||!columnFilters.unknown):key==='progress'?!!(columnFilters.hiddenStages.length||columnFilters.hideApplied):!!columnFilters.hiddenActions.length;}
function renderFilterSummary(){
 document.querySelectorAll('[data-filter]').forEach(b=>{const on=hasColumnFilter(b.dataset.filter);b.classList.toggle('filtered',on);b.setAttribute('aria-pressed',String(on));});
 const active=Object.keys(filterNames).filter(hasColumnFilter);
 $('active-filters').innerHTML=active.length?'<span>Filters: </span>'+active.map(k=>`<button class="filter-chip" data-edit-filter="${k}">${esc(filterNames[k])} · edit</button>`).join('')+'<button class="button secondary" id="clear-filters">Clear column filters</button>':'';
 document.querySelectorAll('[data-edit-filter]').forEach(b=>b.onclick=()=>openColumnFilter(b.dataset.editFilter));
 if($('clear-filters'))$('clear-filters').onclick=()=>{Object.assign(columnFilters,{opportunity:'',location:'',minimum:'',maximum:'',unknown:true,hiddenStages:[],hideApplied:false,hiddenActions:[]});state.page=0;render();};
}
function openColumnFilter(key){
 filterColumn=key;$('filter-title').textContent='Filter '+filterNames[key];
 const checkbox=(label,checked,kind)=>`<label class="filter-choice"><input type="checkbox" data-choice="${kind}" value="${esc(label)}" ${checked?'checked':''}>${esc(label)}</label>`;
 if(key==='opportunity')$('filter-fields').innerHTML=`<label>Company, title, or source<input id="column-query" value="${esc(columnFilters.opportunity)}" placeholder="For example: Indeed or marketing"></label>`;
 if(key==='salary')$('filter-fields').innerHTML=`<label>Location or work arrangement<input id="column-location" value="${esc(columnFilters.location)}" placeholder="For example: Utah or remote"></label><p>Annual USD salary range. Jobs are included when their stated range overlaps yours.</p><div class="salary-bounds"><label>Minimum ($ / year)<input id="salary-min" type="number" min="0" step="any" value="${esc(columnFilters.minimum)}"></label><label>Maximum ($ / year)<input id="salary-max" type="number" min="0" step="any" value="${esc(columnFilters.maximum)}"></label></div>${checkbox('Include unknown, hourly, or other-currency salaries',columnFilters.unknown,'unknown')}<p class="subtext">Hourly pay is not converted to annual pay. Ambiguous salaries stay in the unknown group.</p>`;
 if(key==='progress')$('filter-fields').innerHTML='<p>Uncheck stages you don’t want to see.</p>'+checkbox('Hide all jobs already applied to',columnFilters.hideApplied,'applied')+[...new Set(state.jobs.map(j=>j.stage))].sort().map(s=>checkbox(s,!columnFilters.hiddenStages.includes(s),'stage')).join('');
 if(key==='action')$('filter-fields').innerHTML='<p>Uncheck next actions you don’t want to see.</p>'+[...new Set(state.jobs.map(nextAction))].sort().map(s=>checkbox(s,!columnFilters.hiddenActions.includes(s),'action')).join('');
 if(key==='salary')for(const id of ['salary-min','salary-max'])$(id).oninput=()=>$('salary-max').setCustomValidity('');
 $('filter-dialog').showModal();
}
function clearColumn(key){if(key==='opportunity')columnFilters.opportunity='';if(key==='salary')Object.assign(columnFilters,{location:'',minimum:'',maximum:'',unknown:true});if(key==='progress')Object.assign(columnFilters,{hiddenStages:[],hideApplied:false});if(key==='action')columnFilters.hiddenActions=[];}
$('close-filter').onclick=()=>$('filter-dialog').close();
$('reset-column').onclick=()=>{clearColumn(filterColumn);$('filter-dialog').close();state.page=0;render();};
$('filter-form').onsubmit=e=>{e.preventDefault();
 if(filterColumn==='opportunity')columnFilters.opportunity=$('column-query').value.trim();
 if(filterColumn==='salary'){
  const min=$('salary-min'),max=$('salary-max');max.setCustomValidity('');if(min.value&&max.value&&+min.value>+max.value){max.setCustomValidity('Maximum must be at least the minimum.');max.reportValidity();return;}
  Object.assign(columnFilters,{location:$('column-location').value.trim(),minimum:min.value,maximum:max.value,unknown:document.querySelector('[data-choice="unknown"]').checked});
 }
 if(filterColumn==='progress'){columnFilters.hideApplied=document.querySelector('[data-choice="applied"]').checked;columnFilters.hiddenStages=[...document.querySelectorAll('[data-choice="stage"]')].filter(c=>!c.checked).map(c=>c.value);}
 if(filterColumn==='action')columnFilters.hiddenActions=[...document.querySelectorAll('[data-choice="action"]')].filter(c=>!c.checked).map(c=>c.value);
 $('filter-dialog').close();state.page=0;render();
};
document.querySelectorAll('[data-filter]').forEach(b=>b.onclick=()=>openColumnFilter(b.dataset.filter));
render();refresh();
setInterval(async()=>{try{const wasRunning=state.activity?.operation?.status==='running';state.activity=await api('/api/activity');if(state.view==='activity')renderActivity();if(wasRunning&&state.activity.operation?.status!=='running'){notify('Gecko '+state.activity.operation.status+'. Refreshing your tracker.');await refresh();}}catch{/* Keep the last observed state; explicit refresh surfaces connection errors. */}},10000);
