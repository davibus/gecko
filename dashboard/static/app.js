'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const state = {jobs:[],view:'today',page:0,token:'',selected:null,activity:null,loading:false};
const PAGE_SIZE = 15;
let impromptuFilters=null;
let columnSort=null;
const historyFilters={};
const historyViews=['deleted','rejected','uninterested'];
const sourceFilters={source:'',minimum:'',status:'',explanation:''};
const trendVisible={found:true,resumes:true,applications:true,followups:true};
const today = () => new Intl.DateTimeFormat('en-CA',{timeZone:'America/Denver',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
const displayTimeZone = 'America/Denver';
const dateText = value => value ? new Date(value).toLocaleString('en-US',{timeZone:displayTimeZone,year:'numeric',month:'short',day:'numeric',hour:'numeric',minute:'2-digit',timeZoneName:'short'}) : 'Not recorded';
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
  const data=await api('/api/jobs');state.jobs=data.jobs;state.manualIds=data.manual_ids||[];state.history=data.history||{};state.runIds=data.run_ids||[];state.runMode=data.run_mode;state.columns=data.columns||[];state.runFilterOptions=data.run_filter_options;state.token=data.token;state.activity=data.activity;state.refreshed=data.refreshed_at;
  $('freshness').textContent='Last refreshed '+dateText(data.refreshed_at);$('footer-time').textContent='Tracker refreshed '+dateText(data.refreshed_at);
  $('sheet-link').href=data.sheet_url;$('sheet-link').hidden=!data.sheet_url;banner('');
  const prior=$('source-filter').value;
  $('source-filter').innerHTML='<option value="">All sources</option>'+[...new Set(state.jobs.map(j=>j.fields.Source).filter(Boolean))].sort().map(s=>`<option>${esc(s)}</option>`).join('');
  $('source-filter').value=prior;render();
 }catch(error){banner('Your local workspace could not be refreshed. '+error.message+(state.jobs.length?' Displayed jobs are from the last successful refresh.':''));$('freshness').textContent='Refresh failed · data may be stale';}
 finally{state.loading=false;$('refresh').disabled=false;$('refresh').textContent='↻ Refresh';}
}
function setView(view){if(document.querySelector('.dirty')){notify('Save your edited rows before changing views.');return;}state.view=view;state.page=0;$('stage-filter').value='';$('search').value='';location.hash=view;render();}
const viewNames={manual:'Individually submitted applications',today:'Today',jobs:'All jobs',applications:'Applications',resumes:'Resumes',activity:'Gecko activity',tracker:'Editable tracker',deleted:'Jobs Deleted',rejected:'Jobs Rejected',uninterested:'Not Interested'};
function render(){
 $('opportunities-table').classList.toggle('all-jobs',state.view==='jobs');
 document.querySelectorAll('[data-view]').forEach(b=>b.classList.toggle('active',b.dataset.view===state.view));
 $('crumb').textContent=viewNames[state.view];
 $('page-title').innerHTML=state.view==='today'?'Your next move.':esc(viewNames[state.view]);
 const subtitles={today:'Your opportunities, applications, and next steps. All together.',jobs:'Find the roles worth your time. Review each one on your terms.',applications:'Every application, every conversation, every next step.',resumes:'Your tailored resumes, connected to the right opportunity.',activity:'Know what Gecko is doing, and what needs your attention.'};
 $('page-subtitle').textContent=subtitles[state.view]||'Your columns, your notes, your complete job tracker.';
 $('manual-section').hidden=state.view!=='manual';
 $('history-section').hidden=!historyViews.includes(state.view);
 $('stats').hidden=state.view==='manual'||historyViews.includes(state.view);
 $('tracker-section').hidden=state.view!=='tracker';
 $('today-intro').hidden=state.view!=='today';$('work-section').hidden=['activity','tracker','manual',...historyViews].includes(state.view);$('activity-section').hidden=state.view!=='activity';
 const active=state.jobs.filter(j=>!['Closed','Declined'].includes(j.stage));
 const stats=[['Opportunities',active.filter(j=>!j.applied).length,'Ready for your review','jobs'],['Resumes ready',active.filter(j=>!j.applied&&j.resume_available).length,'Your next applications','resumes'],['Applications',state.jobs.filter(j=>j.applied).length,'Every step, in one place','applications'],['Follow-ups due',state.jobs.filter(due).length,'Keep the conversation going','today']];
 $('stats').innerHTML=stats.map(([label,n,note,view])=>`<button class="stat" data-stat-view="${view}"><span class="stat-label">${label}</span><strong>${state.refreshed?n:'—'}</strong><small>${note}</small></button>`).join('');
 if(state.view==='jobs'){
  const day=today();
  const ready=active.filter(j=>!j.applied&&j.resume_available);
  const applications=state.jobs.filter(j=>j.applied);
  const followUps=state.jobs.filter(j=>j.meta.follow_up&&!['Closed','Offer','Declined'].includes(j.stage));
  const follow=GeckoMetrics.activity(followUps,day,j=>j.meta.follow_up);
  follow.total=state.jobs.filter(due).length;
  const cards=[
   ['Jobs Found',GeckoMetrics.jobsFound(state.jobs,day),''],
   ['Resumes ready',GeckoMetrics.activity(ready,day,j=>j.fields['Resume Created Date']||j.fields['Resume Date']||j.meta.resume_created_at),'Ready resumes by creation date'],
   ['Applications',GeckoMetrics.activity(applications,day,j=>j.fields['Applied Date']||j.meta.applied_at),'By recorded application date'],
   ['Follow-ups due',follow,'Due on each day; total includes overdue']
  ];
  $('stats').innerHTML=cards.map(([label,metric,note])=>{
   const delta=metric.change===null?'—':metric.change>0?'+'+metric.change:String(metric.change);
   const tone=metric.change>0?'stat-positive':metric.change<0?'stat-negative':'';
   const values=[['Today',metric.today??'—',''],['Yesterday',metric.yesterday??'—',''],['Total',metric.total,''],['Change',delta,tone]];
   const detail=metric.undated?metric.undated+' missing dates'+(metric.today===null?' · daily counts unavailable':' · daily counts include dated records only'):note;
   return `<div class="stat jobs-found-stat"><span class="stat-label">${label}</span><div class="jobs-found-grid">${values.map(([name,n,color])=>`<div><small>${name}</small><strong class="${state.refreshed?color:''}">${state.refreshed?n:'—'}</strong></div>`).join('')}</div>${detail?`<small class="metric-note">${esc(detail)}</small>`:''}</div>`;
  }).join('');

 }
 renderTrend();
 renderSources();
 document.querySelectorAll('[data-stat-view]').forEach(b=>b.onclick=()=>setView(b.dataset.statView));
 const focus=[...active].sort((a,b)=>priority(a)-priority(b)).find(j=>priority(j)<9);
 $('focus-title').textContent=focus?nextAction(focus):state.refreshed?'Your queue is clear.':'Connect to your tracker.';
 $('focus-copy').textContent=focus?`${focus.fields.Company} · ${focus.fields['Job Title']}`:state.refreshed?'Explore all jobs or run Gecko to discover fresh opportunities.':'Refresh to load your jobs from your workspace.';
 $('focus-button').textContent=focus?'Open opportunity →':'View all jobs →';$('focus-button').onclick=()=>focus?openJob(focus.id):setView('jobs');
 $('list-title').textContent={today:'Your action queue',jobs:'All opportunities',applications:'Your application pipeline',resumes:'Your resume library',activity:''}[state.view];
 $('list-caption').textContent=state.view==='today'?'Follow-ups, replies, prepared resumes, and jobs to review.':'Select an opportunity to open its complete workspace.';
 if(historyViews.includes(state.view)){ $('page-subtitle').textContent='Saved records and reasons, kept for reference.';return renderHistory();}
 if(state.view==='manual') return renderManual();
 if(state.view==='tracker') return renderTracker();
 if(state.view==='activity') return renderActivity();
 let list=state.jobs.filter(j=>state.view==='today'?priority(j)<9:state.view==='applications'?j.applied:state.view==='resumes'?!!(j.fields['Resume Created']||j.fields['Resume Link']):true);
 const query=$('search').value.trim().toLowerCase(),stage=$('stage-filter').value,source=$('source-filter').value;
 list=list.filter(j=>(!stage||j.stage===stage)&&(!source||j.fields.Source===source)&&(!query||[j.fields.Company,j.fields['Job Title'],j.fields.Location,j.fields.Source,j.id].join(' ').toLowerCase().includes(query)));
 list=list.filter(j=>GeckoFilters.matches(j,columnFilters,nextAction(j)));
 renderFilterSummary();
 const sort=$('sort').value;
 list.sort((a,b)=>sort==='company'?String(a.fields.Company).localeCompare(String(b.fields.Company)):sort==='newest'?String(b.fields['Date Found']).localeCompare(String(a.fields['Date Found'])):priority(a)-priority(b)||String(b.fields['Date Found']).localeCompare(String(a.fields['Date Found'])));
 if(columnSort)list.sort((a,b)=>GeckoFilters.compareValues(columnValue(a,columnSort.key),columnValue(b,columnSort.key),columnSort.direction));
 updateColumnSortControls();
 state.page=Math.max(0,Math.min(state.page,Math.ceil(list.length/PAGE_SIZE)-1));
 $('result-count').textContent=list.length+' opportunities';
 $('jobs').innerHTML=list.slice(state.page*PAGE_SIZE,(state.page+1)*PAGE_SIZE).map(j=>`<tr><td><div class="opportunity"><span class="company-icon">${esc(String(j.fields.Company||'?').slice(0,2).toUpperCase())}</span><div><button class="job-link" data-job="${esc(j.id)}" ${!j.editable?'disabled':''}>${esc(j.fields['Job Title']||'Untitled opportunity')}</button><span class="subtext">${esc(j.fields.Company)} <span>·</span> ${esc(j.fields.Source)}${!j.editable?' · Tracker identity needs review':''}</span></div></div></td><td class="date-found">${esc(j.fields['Date Found']||'—')}</td><td>${esc(j.fields.Location||'Location not listed')}<span class="subtext">${esc(j.fields.Salary||j.fields['Work Arrangement']||'Salary not listed')}</span></td><td><span class="badge ${j.applied?'applied':j.resume_available?'ready':j.stage==='Review'?'warn':''}">${esc(j.stage)}</span></td><td><span class="next-action">${esc(nextAction(j))}</span></td><td class="all-jobs-column">${esc(j.fields['Personal priority']||'—')}</td><td class="all-jobs-column">${esc(j.fields['Applied Date']||'—')}</td><td class="all-jobs-column">${esc(j.fields.Source||'—')}</td><td><button class="arrow" data-job="${esc(j.id)}" aria-label="Open ${esc(j.fields.Company)} job" ${!j.editable?'disabled':''}>↗</button></td></tr>`).join('');
 $('empty').hidden=!!list.length;$('empty').textContent=state.refreshed?'No opportunities match this view. Try another filter or view all jobs.':'Loading your workspace…';
 $('page-count').textContent=list.length?`${state.page*PAGE_SIZE+1}–${Math.min((state.page+1)*PAGE_SIZE,list.length)} of ${list.length}`:'0 results';
 $('prev').disabled=state.page===0;$('next').disabled=(state.page+1)*PAGE_SIZE>=list.length;
 document.querySelectorAll('[data-job]').forEach(b=>b.onclick=()=>openJob(b.dataset.job));
}



function renderHistory(){
 const category=state.view,rows=state.history?.[category]||[];
 const columns={company:'Company',title:'Job Title',source:'Source',location:'Location',date:'Recorded Date',reason:'Reason / Notes'};
 const filters=historyFilters[category]||(historyFilters[category]={});
 const visible=rows.filter(row=>Object.entries(filters).every(([key,value])=>String(row[key]||'').toLowerCase().includes(value.toLowerCase())));
 const intro={deleted:'Removed or archived job records. No permanent deletion is performed here.',rejected:'Jobs recorded as rejected by Gecko or marked Reject in your tracker. This does not imply an employer rejection.',uninterested:'Jobs with Apply? set to No, including roles you declined or that did not meet eligibility rules.'};
 const icon='<svg width="15" height="15" viewBox="0 0 24 24" aria-hidden="true"><path d="M3 4h18l-7 8v7l-4 2v-9z" fill="none" stroke="currentColor" stroke-width="2"/></svg>';
 $('history-section').innerHTML='<p class="history-explanation">'+intro[category]+'</p><div class="section-heading"><h2>Saved jobs</h2><span>'+visible.length+' of '+rows.length+' records</span></div><div class="table-wrap history-table"><table><thead><tr>'+Object.entries(columns).map(([key,label])=>'<th>'+label+' <button class="column-filter" data-history-focus="'+key+'" aria-label="Filter '+label+'">'+icon+'</button><input data-history-filter="'+key+'" aria-label="Search '+label+'" value="'+esc(filters[key]||'')+'" placeholder="Filter…"></th>').join('')+'</tr></thead><tbody>'+visible.map(row=>'<tr><td>'+esc(row.company||'—')+'</td><td>'+(row.url?'<a href="'+esc(row.url)+'" target="_blank" rel="noopener noreferrer">'+esc(row.title||'Open saved job')+'</a>':esc(row.title||'—'))+'<small class="subtext">'+esc(row.id?'ID '+row.id:'')+'</small></td><td>'+esc(row.source||'—')+'</td><td>'+esc(row.location||'—')+'</td><td>'+esc(row.date||'Not recorded')+'</td><td><details><summary>'+esc(String(row.reason||'Reason not recorded').slice(0,110))+'</summary><div class="history-notes">'+esc(row.reason)+'</div></details></td></tr>').join('')+'</tbody></table></div>'+(!visible.length?'<p class="loading">'+(rows.length?'No saved jobs match your filters.':'No jobs are recorded in this category yet.')+'</p>':'')+'<div class="actions"><button class="button secondary" id="clear-history-filters">Clear filters</button></div>';
 $('history-section').querySelectorAll('[data-history-filter]').forEach(input=>input.oninput=()=>{const caret=input.selectionStart;filters[input.dataset.historyFilter]=input.value;renderHistory();const next=$('history-section').querySelector('[data-history-filter="'+input.dataset.historyFilter+'"]');next.focus();next.setSelectionRange(caret,caret);});
 $('history-section').querySelectorAll('[data-history-focus]').forEach(b=>b.onclick=()=>$('history-section').querySelector('[data-history-filter="'+b.dataset.historyFocus+'"]').focus());
 $('clear-history-filters').onclick=()=>{historyFilters[category]={};renderHistory();};
}

function renderSources(){
 let panel=$('source-summary');
 if(!panel){panel=document.createElement('section');panel.id='source-summary';panel.className='weekly-trend';const row=document.createElement('div');row.id='source-summary-row';$('weekly-trend').after(row);row.append(panel);}
 panel.hidden=state.view!=='jobs';$('source-summary-row').hidden=panel.hidden;if(panel.hidden)return;
 const report=state.activity?.sources;
 const names={adzuna:'Adzuna Official',himalayas:'Himalayas',ashby:'Ashby',greenhouse:'Greenhouse',indeed:'Indeed',jobicy:'Jobicy',personio:'Personio',lever:'Lever',linkedin:'LinkedIn',remoteok:'Remote OK',remotive:'Remotive',usajobs:'USAJOBS',weworkremotely:'We Work Remotely','web-careers':'Web Careers',workable:'Workable',smartrecruiters:'SmartRecruiters',workingnomads:'Working Nomads',themuse:'The Muse',glassdoor:'Glassdoor',ziprecruiter:'ZipRecruiter'};
 const rows=(report?.rows||[]).map(r=>({...r,label:names[r.source]||r.source}));
 const filtered=rows.filter(r=>r.label.toLowerCase().includes(sourceFilters.source.toLowerCase())&&(!sourceFilters.minimum||r.found>=Number(sourceFilters.minimum))&&(!sourceFilters.status||r.status===sourceFilters.status)&&String(r.explanation||'').toLowerCase().includes(sourceFilters.explanation.toLowerCase()));
 const icon='<svg width="15" height="15" viewBox="0 0 24 24" aria-hidden="true"><path d="M3 4h18l-7 8v7l-4 2v-9z" fill="none" stroke="currentColor" stroke-width="2"/></svg>';
 panel.innerHTML='<div class="trend-heading"><h2>Job Sources</h2><p>'+(report?'Latest saved discovery breakdown · '+esc(dateText(report.recorded_at)):'No saved discovery breakdown available.')+'</p></div><p class="trend-note">Jobs found are listings retrieved before eligibility checks and duplicate removal, not new jobs added to your tracker. Counts describe this saved run, not today’s activity.</p><div class="source-controls"><label>Source<input id="source-name-query" value="'+esc(sourceFilters.source)+'" placeholder="All sources"></label><label>Minimum jobs found<input id="source-min-query" type="number" min="0" value="'+esc(sourceFilters.minimum)+'" placeholder="Any count"></label><label>Run status<select id="source-status-query"><option value="">All statuses</option>'+[...new Set(rows.map(r=>r.status))].sort().map(status=>'<option '+(status===sourceFilters.status?'selected':'')+'>'+esc(status)+'</option>').join('')+'</select></label><label>Explanation<input id="source-explanation-query" value="'+esc(sourceFilters.explanation)+'" placeholder="Search explanations"></label><button class="button secondary" id="clear-source-filters">Clear filters</button></div><div class="table-wrap source-table"><table><thead><tr>'+[['Source','source-name-query'],['Jobs found','source-min-query'],['Run status','source-status-query'],['Explanation','source-explanation-query']].map(([name,id])=>'<th>'+name+' <button class="column-filter" data-source-focus="'+id+'" aria-label="Filter '+name+' in Job Sources">'+icon+'</button></th>').join('')+'</tr></thead><tbody>'+filtered.map(r=>'<tr><td>'+esc(r.label)+'</td><td>'+Number(r.found).toLocaleString()+'</td><td>'+esc(r.status)+'</td><td class="source-explanation">'+esc(r.explanation||'No explanation recorded.')+'</td></tr>').join('')+'</tbody></table></div><p class="trend-note">'+filtered.length+' sources shown'+(!filtered.length?' · No sources match these filters.':'')+'</p>';
 const bind=(id,key)=>$(id)[id==='source-status-query'?'onchange':'oninput']=()=>{const position=$(id).selectionStart;sourceFilters[key]=$(id).value;renderSources();$(id).focus();if(position!==null)$(id).setSelectionRange(position,position);};
 bind('source-name-query','source');bind('source-min-query','minimum');bind('source-status-query','status');bind('source-explanation-query','explanation');
 panel.querySelectorAll('[data-source-focus]').forEach(b=>b.onclick=()=>$(b.dataset.sourceFocus).focus());
 $('clear-source-filters').onclick=()=>{Object.assign(sourceFilters,{source:'',minimum:'',status:'',explanation:''});renderSources();};
}

function renderTrend(){
 let panel=$('weekly-trend');
 if(!panel){panel=document.createElement('section');panel.id='weekly-trend';panel.className='weekly-trend';$('stats').after(panel);}
 panel.hidden=state.view!=='jobs';if(panel.hidden)return;
 if(!state.refreshed){panel.innerHTML='<p class="loading">Loading seven-day activity…</p>';return;}
 const {dates,series}=GeckoMetrics.week(state.jobs,today());
 const selected=series.filter(s=>trendVisible[s.key]);
 const points=selected.flatMap(s=>s.values).filter(v=>v!==null);
 const step=Math.max(1,Math.ceil(Math.max(1,...points)/4));const max=step*4;
 const x=i=>56+i*110,y=n=>218-n/max*180;
 const label=date=>new Date(date+'T12:00:00Z').toLocaleDateString('en-US',{timeZone:'UTC',weekday:'short',month:'short',day:'numeric'});
 const grid=Array.from({length:5},(_,i)=>{const value=i*step;return '<line x1="56" x2="716" y1="'+y(value)+'" y2="'+y(value)+'" stroke="#e7ece3"/><text x="44" y="'+(y(value)+4)+'" text-anchor="end">'+value+'</text>';}).join('');
 const lines=selected.map(s=>{
  if(s.values.every(v=>v===null))return '';
  let path='',previous=false;
  s.values.forEach((v,i)=>{if(v===null){previous=false;return;}path+=(previous?' L':' M')+x(i)+' '+y(v);previous=true;});
  return '<path d="'+path+'" fill="none" stroke="'+s.color+'" stroke-width="2.5" stroke-dasharray="'+s.dash+'"/>'+s.values.map((v,i)=>v===null?'':'<circle tabindex="0" cx="'+x(i)+'" cy="'+y(v)+'" r="4" fill="white" stroke="'+s.color+'" stroke-width="2" aria-label="'+esc(s.label+', '+dates[i]+': '+v)+'"><title>'+esc(s.label+' · '+label(dates[i])+': '+v)+'</title></circle>').join('');
 }).join('');
 const empty=!selected.length?'Turn on a series to see its trend.':!points.length?'No dated records for the selected series.':'';
 panel.innerHTML='<div class="trend-heading"><h2>Past 7 days</h2><p>Daily counts · '+label(dates[0])+' – '+label(dates[6])+' · Mountain Time</p></div><div class="trend-layout"><div class="trend-options" role="group" aria-label="Chart series">'+series.map(s=>'<button class="trend-toggle" data-trend="'+s.key+'" aria-pressed="'+trendVisible[s.key]+'" style="--series-color:'+s.color+'"><span class="trend-swatch"></span><span>'+s.label+'<small>'+(trendVisible[s.key]?'On':'Off')+(s.undated?' · '+s.undated+' missing dates':'')+'</small></span></button>').join('')+'</div><div class="trend-plot"><svg viewBox="0 0 760 275" role="img" aria-label="Daily job search activity over the past seven days"><text x="56" y="20">Count</text>'+grid+'<line x1="56" x2="716" y1="218" y2="218" stroke="#b7c3af"/>'+lines+dates.map((d,i)=>'<text x="'+x(i)+'" y="245" text-anchor="middle">'+new Date(d+'T12:00:00Z').toLocaleDateString('en-US',{timeZone:'UTC',weekday:'short'})+'</text><text x="'+x(i)+'" y="262" text-anchor="middle">'+d.slice(5).replace('-','/')+'</text>').join('')+(empty?'<text x="386" y="120" text-anchor="middle">'+empty+'</text>':'')+'</svg></div></div><p class="trend-note">Counts use recorded dates, not cumulative totals. Missing dates are excluded; an entirely undated series has no line. Follow-ups are grouped by their current due date.</p><details class="trend-data"><summary>View daily values</summary><div class="table-wrap"><table><thead><tr><th>Date</th>'+selected.map(s=>'<th>'+s.label+'</th>').join('')+'</tr></thead><tbody>'+dates.map((d,i)=>'<tr><td>'+d+'</td>'+selected.map(s=>'<td>'+(s.values[i]??'Unavailable')+'</td>').join('')+'</tr>').join('')+'</tbody></table></div></details>';
 panel.querySelectorAll('[data-trend]').forEach(button=>button.onclick=()=>{trendVisible[button.dataset.trend]=!trendVisible[button.dataset.trend];renderTrend();panel.querySelector('[data-trend="'+button.dataset.trend+'"]').focus();});
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
 try{const operation=await api('/api/run',payload);state.activity={...state.activity,operation,busy:true};$('run-dialog').close();$('job-dialog').close();setView('activity');notify('Gecko started. You can follow progress here.');return true;}
 catch(error){if($('job-dialog').open)$('detail-error').textContent=error.message;else{$('run-dialog').close();banner(error.message);}}
}
function elapsedText(start, end, running){
 const from=Date.parse(start),to=end?Date.parse(end):running?Date.now():NaN;
 if(!Number.isFinite(from)||!Number.isFinite(to)||to<from)return 'Not available';
 const seconds=Math.floor((to-from)/1000),hours=Math.floor(seconds/3600),minutes=Math.floor(seconds%3600/60);
 return hours+' hours '+minutes+' minutes '+(seconds%60)+' seconds';
}
function elapsedMarkup(record, running, end){
 return '<p class="run-elapsed"><strong>'+ (running?'Time elapsed: ':'Total duration: ')+'</strong><span data-elapsed-start="'+esc(record.started_at||'')+'" data-elapsed-end="'+esc(end||'')+'" data-elapsed-running="'+running+'">'+elapsedText(record.started_at,end,running)+'</span></p>';
}
setInterval(()=>{if(state.view==='activity')document.querySelectorAll('[data-elapsed-running="true"]').forEach(el=>{el.textContent=elapsedText(el.dataset.elapsedStart,el.dataset.elapsedEnd,true);});},1000);
function renderActivity(){
 const activity=state.activity||{},op=activity.operation,pipeline=activity.pipeline,exported=activity.export;
 const summary=op?`${op.kind==='resume'?'Tailored resume · Job '+op.job_id:(op.kind==='impromptu'?'Impromptu filtered discovery':'Daily Gecko workflow')+(op.job_ids?' · IDs '+op.job_ids.join(', '):'')} — ${op.status}`:'No dashboard run yet';
 $('activity-section').innerHTML=`<div class="activity-card"><h3>Run Gecko model</h3><p><strong>Model:</strong> ${esc(activity.runner?.model||'Not available')} · <strong>Reasoning:</strong> ${esc(activity.runner?.effort||'Not available')}</p><p>${activity.runner?.verified?'Connection verified '+esc(dateText(activity.runner.verified_at))+'. Each run verifies its runtime settings again.':'Runtime verification runs before job processing. No fallback model is permitted.'}</p></div><div class="activity-card"><span class="eyebrow">WORKSPACE OPERATIONS</span><h3>${esc(summary)}</h3>${op?`<p><strong>Model:</strong> ${esc(op.model_info?.model||'Not recorded for this run')}${op.model_info?(op.model_info.verified?' · Runtime verified':' · Awaiting runtime verification'):''}</p><p><strong>Reasoning level:</strong> ${esc(op.model_info?.effort||'Not recorded for this run')}</p><button id="stop-operation" class="button danger" ${op.status!=='running'||!activity.can_stop?'disabled':''}>Stop run</button>`:''}<p>${activity.busy?'Gecko’s processing lock is active. Editing is paused until the run finishes.':'No Gecko processing lock is active.'}</p>${op?`${elapsedMarkup(op,op.status==='running'&&activity.busy,op.finished_at)}<p><strong>Started:</strong> ${esc(dateText(op.started_at))}</p><p><strong>Finished:</strong> ${op.finished_at?esc(dateText(op.finished_at)):'Not finished'}</p>${op.error?`<div class="warning">${esc(op.error)}</div>`:''}${op.log?`<p class="subtext">Local log: ${esc(op.log)}</p>`:''}`:''}</div><div class="activity-card"><span class="eyebrow">LAST CANONICAL PIPELINE RECORD</span>${pipeline?`${elapsedMarkup(pipeline,pipeline.status==='running'&&activity.busy,pipeline.finished_at||(pipeline.status!=='running'?pipeline.updated_at:null))}<p><strong>Model:</strong> ${esc(pipeline.model_info?.model||'Not recorded for this run')} · <strong>Reasoning:</strong> ${esc(pipeline.model_info?.effort||'Not recorded')}${pipeline.model_info?.verified?' · Runtime verified':''}</p><h3>${esc(pipeline.status)} · ${esc(pipeline.current_step||'Gecko workflow')}</h3><p><strong>Started:</strong> ${esc(dateText(pipeline.started_at))}</p><p><strong>Finished:</strong> ${pipeline.status!=='running'?esc(dateText(pipeline.finished_at||pipeline.updated_at)):'Not finished'}</p><ul>${(pipeline.steps||[]).map(s=>`<li>${esc(s.name)} — ${s.exit_code===0?'completed':'stopped (exit '+esc(s.exit_code)+')'}</li>`).join('')}</ul><p class="subtext">This is the last saved pipeline record; it does not by itself indicate a currently running process.</p>`:'<p>No pipeline history is available.</p>'}</div><div class="activity-card"><h3>Google Sheets export</h3>${exported?`<p>${esc(exported.status)} · ${esc(dateText(exported.finished_at||exported.started_at))}</p>${exported.status==='verified'&&/^https:\/\/docs\.google\.com\/spreadsheets\//.test(exported.url||'')?`<a class="button secondary" href="${esc(exported.url)}" target="_blank" rel="noopener noreferrer">Open verified export ↗</a><p>${esc(exported.rows)} tracker rows exported, including custom columns.</p>`:`<p>${esc(exported.error||'Export has not been verified.')}</p>`}`:'<p>No manual export recorded yet.</p>'}<p class="subtext">This is the latest export record; its time identifies which snapshot it contains. SQLite remains the main tracker.</p></div><div class="activity-card"><h3>What a daily run does</h3><p>Daily report → discovery and SQLite updates → approved eligible resumes → employer responses → database backup → final report. Google Sheets exports are manual using the button under Local workspace.</p><p>Resume creation uses Gecko’s existing validation and completion checks. Applications are never submitted by this dashboard.</p></div>`;
 const stop=$('stop-operation');if(stop)stop.onclick=async()=>{if(!confirm('Stop this Gecko run and its active work? Completed saves remain; unfinished work may need review.'))return;stop.disabled=true;try{await api('/api/stop',{started_at:op.started_at});notify('Stop requested.');state.activity=await api('/api/activity');renderActivity();}catch(e){notify(e.message);stop.disabled=false;}};
}
$('date-label').textContent=new Date().toLocaleDateString('en-US',{timeZone:displayTimeZone,weekday:'long',month:'long',day:'numeric',year:'numeric'}).toUpperCase();
document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>setView(b.dataset.view));
$('refresh').onclick=refresh;$('close-job').onclick=()=>$('job-dialog').close();
$('run-gecko').onclick=()=>{if(impromptuFilters){showImpromptuConfirmation();return;}if(!state.runMode){banner('Refresh to load the verified run scope.');return;}const full=state.runMode==='full';$('run-title').textContent=full?'Run full Gecko workflow':'Run '+state.runIds.length+' selected jobs';$('run-scope').textContent=full?'Search all configured sources and process the full eligible job queue using your normal preferences.':'Only these jobs will be processed: '+state.runIds.join(', ')+'.';$('confirm-run').textContent=full?'Start full Gecko run':'Start selected '+state.runIds.length+'-job run';$('run-dialog').showModal();};$('close-run').onclick=$('cancel-run').onclick=()=>$('run-dialog').close();$('confirm-run').onclick=()=>startRun({kind:'gecko'});
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
$('export-sheet').onclick=async()=>{if(document.querySelector('.dirty')){notify('Save your edited rows before exporting.');return;}const b=$('export-sheet'),status=$('export-status');b.disabled=true;b.textContent='Exporting…';$('export-link').hidden=true;status.textContent='Creating and verifying your Google Sheets copy…';try{const result=await api('/api/export',{});$('export-link').href=result.url;$('export-link').hidden=false;status.textContent=`Export verified: ${result.rows} rows.`;}catch(e){status.textContent='Export failed: '+e.message;}finally{b.disabled=false;b.textContent='Export to Google Sheets';}};
window.addEventListener('beforeunload',e=>{if(document.querySelector('.dirty')){e.preventDefault();e.returnValue='';}});
const columnFilters={opportunity:'',location:'',minimum:'',maximum:'',unknown:true,hiddenStages:[],hideApplied:false,hiddenActions:[],hiddenValues:{}};
let filterColumn='';
const fieldFilters={dateFound:'Date Found',personalPriority:'Personal priority',appliedDate:'Applied Date',source:'Source'};
const filterNames={dateFound:'Date Found',opportunity:'Opportunity',salary:'Location / salary',progress:'Progress',action:'Next action',personalPriority:'Personal Priority',appliedDate:'Applied Date',source:'Source'};
function hasColumnFilter(key){if(fieldFilters[key])return !!columnFilters.hiddenValues[fieldFilters[key]]?.length;return key==='opportunity'?!!columnFilters.opportunity:key==='salary'?!!(columnFilters.location||columnFilters.minimum||columnFilters.maximum||!columnFilters.unknown):key==='progress'?!!(columnFilters.hiddenStages.length||columnFilters.hideApplied):!!columnFilters.hiddenActions.length;}
function renderFilterSummary(){
 document.querySelectorAll('[data-filter]').forEach(b=>{const on=hasColumnFilter(b.dataset.filter);b.classList.toggle('filtered',on);b.setAttribute('aria-pressed',String(on));});
 const active=Object.keys(filterNames).filter(hasColumnFilter);
 $('active-filters').innerHTML=active.length?'<span>Filters: </span>'+active.map(k=>`<button class="filter-chip" data-edit-filter="${k}">${esc(filterNames[k])} · edit</button>`).join('')+'<button class="button secondary" id="clear-filters">Clear column filters</button>':'';
 document.querySelectorAll('[data-edit-filter]').forEach(b=>b.onclick=()=>openColumnFilter(b.dataset.editFilter));
 if($('clear-filters'))$('clear-filters').onclick=()=>{Object.assign(columnFilters,{opportunity:'',location:'',minimum:'',maximum:'',unknown:true,hiddenStages:[],hideApplied:false,hiddenActions:[],hiddenValues:{}});state.page=0;render();};
}
function openColumnFilter(key){
 filterColumn=key;$('filter-title').textContent='Filter '+filterNames[key];
 const checkbox=(label,checked,kind)=>`<label class="filter-choice"><input type="checkbox" data-choice="${kind}" value="${esc(label)}" ${checked?'checked':''}>${esc(label)}</label>`;
 if(key==='opportunity')$('filter-fields').innerHTML=`<label>Company, title, or source<input id="column-query" value="${esc(columnFilters.opportunity)}" placeholder="For example: Indeed or marketing"></label>`;
 if(key==='salary')$('filter-fields').innerHTML=`<label>Location or work arrangement<input id="column-location" value="${esc(columnFilters.location)}" placeholder="For example: Utah or remote"></label><p>Annual USD salary range. Jobs are included when their stated range overlaps yours.</p><div class="salary-bounds"><label>Minimum ($ / year)<input id="salary-min" type="number" min="0" step="any" value="${esc(columnFilters.minimum)}"></label><label>Maximum ($ / year)<input id="salary-max" type="number" min="0" step="any" value="${esc(columnFilters.maximum)}"></label></div>${checkbox('Include unknown, hourly, or other-currency salaries',columnFilters.unknown,'unknown')}<p class="subtext">Hourly pay is not converted to annual pay. Ambiguous salaries stay in the unknown group.</p>`;
 if(key==='progress')$('filter-fields').innerHTML='<p>Uncheck stages you don’t want to see.</p>'+checkbox('Hide all jobs already applied to',columnFilters.hideApplied,'applied')+[...new Set(state.jobs.map(j=>j.stage))].sort().map(s=>checkbox(s,!columnFilters.hiddenStages.includes(s),'stage')).join('');
 if(key==='action')$('filter-fields').innerHTML='<p>Uncheck next actions you don’t want to see.</p>'+[...new Set(state.jobs.map(nextAction))].sort().map(s=>checkbox(s,!columnFilters.hiddenActions.includes(s),'action')).join('');
 if(fieldFilters[key]){
  const field=fieldFilters[key],hidden=columnFilters.hiddenValues[field]||[];
  const values=[...new Set(state.jobs.map(j=>String(j.fields[field]??'').trim()))].sort((a,b)=>a.localeCompare(b,undefined,{numeric:true}));
  $('filter-fields').innerHTML='<p>Uncheck values you don’t want to see.</p>'+values.map(value=>`<label class="filter-choice"><input type="checkbox" data-choice="field-value" value="${esc(value)}" ${hidden.includes(value)?'':'checked'}>${esc(value||'(Blank)')}</label>`).join('');
 }
 if(key==='salary')for(const id of ['salary-min','salary-max'])$(id).oninput=()=>$('salary-max').setCustomValidity('');
 $('filter-dialog').showModal();
}
function clearColumn(key){if(fieldFilters[key])delete columnFilters.hiddenValues[fieldFilters[key]];if(key==='opportunity')columnFilters.opportunity='';if(key==='salary')Object.assign(columnFilters,{location:'',minimum:'',maximum:'',unknown:true});if(key==='progress')Object.assign(columnFilters,{hiddenStages:[],hideApplied:false});if(key==='action')columnFilters.hiddenActions=[];}
$('close-filter').onclick=()=>$('filter-dialog').close();
$('reset-column').onclick=()=>{clearColumn(filterColumn);$('filter-dialog').close();state.page=0;render();};
$('filter-form').onsubmit=e=>{e.preventDefault();
 if(fieldFilters[filterColumn])columnFilters.hiddenValues[fieldFilters[filterColumn]]=[...document.querySelectorAll('[data-choice="field-value"]')].filter(c=>!c.checked).map(c=>c.value);
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

function runFilterDefaults(){
 const o=state.runFilterOptions;
 return {sources:[...o.sources],titles:[...o.titles],arrangements:[...o.arrangements],matches:[...o.matches],costs:o.costs.filter(x=>x!=='Fee required'),locations:[...o.locations],priorities:[...new Set(['High','Medium','Low','Unassigned',...state.jobs.map(j=>j.fields['Personal priority']).filter(Boolean)])],salary_min:'',salary_max:'',salary_unknown:true};
}
function drawRunFilters(value){
 const options={...state.runFilterOptions,priorities:[...new Set([...runFilterDefaults().priorities,...value.priorities])]};
 const labels={sources:'Sources',titles:'Job titles (title contains)',costs:'Application cost',arrangements:'Work arrangement',locations:'Locations / Utah areas',matches:'Match type — saved fit score',priorities:'Personal Priority'};
 $('run-filter-fields').innerHTML=Object.entries(labels).map(([key,label])=>'<fieldset><legend>'+label+'</legend><div class="run-choice-grid">'+options[key].map(v=>'<label><input type="checkbox" name="'+key+'" value="'+esc(v)+'" '+(value[key].includes(v)?'checked':'')+'>'+esc(v)+'</label>').join('')+'</div></fieldset>').join('')+'<fieldset><legend>Annual salary (USD)</legend><div class="salary-bounds"><label>Minimum<input id="run-salary-min" type="number" min="0" max="10000000" value="'+(value.salary_min??'')+'"></label><label>Maximum<input id="run-salary-max" type="number" min="0" max="10000000" value="'+(value.salary_max??'')+'"></label></div><label><input id="run-salary-unknown" type="checkbox" '+(value.salary_unknown?'checked':'')+'>Include unknown, hourly, or other-currency salary</label></fieldset><p class="trend-note">New jobs usually have no saved fit score, Personal Priority, or verified fee information. Keep Unrated, Unassigned, and Unknown checked to include them. Strong = 80–100; Possible = 50–79; Low = 0–49. Scores are saved assessments, not new evaluations. Remote / anywhere includes remote listings; other locations match the listed city or Utah. Existing Gecko eligibility and completed-resume protections still apply.</p>';
 $('run-filter-error').textContent='';
}
$('run-filters').onclick=()=>{if(!state.runFilterOptions){notify('Refresh to load run filter options.');return;}drawRunFilters(impromptuFilters||runFilterDefaults());$('run-filters-dialog').showModal();};
$('close-run-filters').onclick=()=>$('run-filters-dialog').close();
$('reset-run-filters').onclick=()=>drawRunFilters(runFilterDefaults());
$('disable-run-filters').onclick=()=>{impromptuFilters=null;$('run-filters').textContent='Filters';$('run-filters-dialog').close();notify('Existing run mode restored.');};
$('run-filters-form').onsubmit=e=>{
 e.preventDefault();const value={};
 for(const key of ['sources','titles','costs','arrangements','locations','matches','priorities']){
  value[key]=[...document.querySelectorAll('#run-filter-fields input[name="'+key+'"]:checked')].map(x=>x.value);
  if(!value[key].length){$('run-filter-error').textContent='Select at least one option for '+key+'.';return;}
 }
 value.salary_min=$('run-salary-min').value===''?null:Number($('run-salary-min').value);
 value.salary_max=$('run-salary-max').value===''?null:Number($('run-salary-max').value);
 value.salary_unknown=$('run-salary-unknown').checked;
 if(value.salary_min!==null&&value.salary_max!==null&&value.salary_min>value.salary_max){$('run-filter-error').textContent='Maximum salary must be at least the minimum.';return;}
 impromptuFilters=value;$('run-filters').textContent='Filters ✓';$('run-filters-dialog').close();notify('Filters ready. Click Run Gecko to review and start this impromptu search.');
};
function showImpromptuConfirmation(){
 $('impromptu-summary').innerHTML='<dl>'+Object.entries(impromptuFilters).map(([key,value])=>'<dt>'+esc(key.replaceAll('_',' '))+'</dt><dd>'+esc(Array.isArray(value)?value.join(', '):value===null?'No limit':value===true?'Include':value===false?'Exclude':value)+'</dd>').join('')+'</dl>';
 $('impromptu-confirm').showModal();
}
$('cancel-impromptu').onclick=()=>$('impromptu-confirm').close();
$('start-impromptu').onclick=async()=>{const button=$('start-impromptu');button.disabled=true;try{const ok=await startRun({kind:'impromptu',filters:impromptuFilters});if(ok){impromptuFilters=null;$('run-filters').textContent='Filters';}$('impromptu-confirm').close();}finally{button.disabled=false;}};


const sortableColumns={opportunity:'Opportunity',dateFound:'Date Found',salary:'Location / Salary',progress:'Progress',action:'Next Action',personalPriority:'Personal Priority',appliedDate:'Applied Date',source:'Source'};
function columnValue(job,key){
 const f=job.fields;
 return {opportunity:f['Job Title'],dateFound:f['Date Found'],salary:[f.Location,f.Salary].filter(Boolean).join(' · '),progress:job.stage,action:nextAction(job),personalPriority:f['Personal priority'],appliedDate:f['Applied Date'],source:f.Source}[key];
}
function updateColumnSortControls(){
 if(columnSort){let option=$('column-sort-option');if(!option){option=document.createElement('option');option.id='column-sort-option';option.value='column';option.disabled=true;$('sort').append(option);}option.textContent=sortableColumns[columnSort.key]+' · '+(columnSort.direction==='asc'?'ascending':'descending');$('sort').value='column';}
 document.querySelectorAll('#opportunities-table [data-column-sort]').forEach(button=>{
  const key=button.dataset.columnSort,active=columnSort?.key===key;
  const date=['dateFound','appliedDate'].includes(key);
  const direction=active?columnSort.direction:'asc';
  button.textContent=(date?(direction==='asc'?'Oldest first':'Newest first'):(direction==='asc'?'A–Z':'Z–A'))+(active?(direction==='asc'?' ↑':' ↓'):' ↕');
  button.classList.toggle('sorted',active);
  button.setAttribute('aria-label','Sort '+sortableColumns[key]+(active&&direction==='asc'?' descending':' ascending'));
  button.closest('th').setAttribute('aria-sort',active?(direction==='asc'?'ascending':'descending'):'none');
 });
}
for(const [key,label] of Object.entries(sortableColumns)){
 const header=document.querySelector('#opportunities-table [data-filter="'+key+'"]').closest('th');
 const button=document.createElement('button');button.className='column-sort';button.dataset.columnSort=key;header.append(button);
 button.onclick=()=>{columnSort={key,direction:columnSort?.key===key&&columnSort.direction==='asc'?'desc':'asc'};state.page=0;render();};
}
$('sort').addEventListener('change',()=>{columnSort=null;state.page=0;render();});

render();refresh();
setInterval(async()=>{try{const wasRunning=state.activity?.operation?.status==='running';state.activity=await api('/api/activity');if(state.view==='activity')renderActivity();if(wasRunning&&state.activity.operation?.status!=='running'){notify('Gecko '+state.activity.operation.status+'. Refreshing your tracker.');await refresh();}}catch{/* Keep the last observed state; explicit refresh surfaces connection errors. */}},10000);
