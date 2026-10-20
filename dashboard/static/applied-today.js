'use strict';
const appliedTodayHidden={},appliedTodayColumns=[['opportunity','Opportunity'],['resumeCreated','Resume created'],['dateFound','Date found'],['salary','Location / salary'],['progress','Status'],['action','Next action'],['personalPriority','Personal priority'],['appliedDate','Applied date'],['source','Source']];
let appliedTodaySort={key:'opportunity',direction:'asc'};
function applicationDay(job){
 const value=String(job.fields['Applied Date']||job.meta.applied_at||'').trim();
 if(/^\d{4}-\d{2}-\d{2}$/.test(value))return value;
 const date=new Date(value);return isNaN(date)?'':new Intl.DateTimeFormat('en-CA',{timeZone:'America/Denver',year:'numeric',month:'2-digit',day:'2-digit'}).format(date);
}
function jobsAppliedToday(jobs,day){return jobs.filter(job=>job.applied&&applicationDay(job)===day);}
function renderAppliedToday(){
 let section=$('applied-today-section');
 if(!section){section=document.createElement('section');section.id='applied-today-section';$('work-section').after(section);}
 section.hidden=state.view!=='jobs';if(section.hidden)return;
 const jobs=jobsAppliedToday(state.jobs,today());
 const value=(job,key)=>String(columnValue(job,key)||'').trim();
 const rows=jobs.filter(job=>appliedTodayColumns.every(([key])=>!(appliedTodayHidden[key]||[]).includes(value(job,key))));
 rows.sort((a,b)=>GeckoFilters.compareValues(value(a,appliedTodaySort.key),value(b,appliedTodaySort.key),appliedTodaySort.direction));
 section.innerHTML='<div class="section-heading"><h2>Jobs I’ve applied to today</h2><span>'+rows.length+' of '+jobs.length+'</span></div><p class="subtext">Applications recorded for '+esc(today())+' · Mountain Time</p><div class="table-wrap jobs-scroll"><table class="applied-today-table"><thead><tr>'+appliedTodayColumns.map(([key,label])=>{
  const hidden=appliedTodayHidden[key]||[],values=[...new Set(jobs.map(job=>value(job,key)))].sort((a,b)=>a.localeCompare(b,undefined,{numeric:true}));
  const sorted=appliedTodaySort.key===key,desc=sorted&&appliedTodaySort.direction==='desc';
  const sortLabel=['dateFound','appliedDate'].includes(key)?(desc?'Newest first ↓':'Oldest first ↑'):(desc?'Z–A ↓':'A–Z ↑');
  return '<th aria-sort="'+(sorted?(desc?'descending':'ascending'):'none')+'">'+esc(label.toUpperCase())+' <button type="button" class="column-filter '+(hidden.length?'filtered':'')+'" data-today-filter="'+key+'" aria-label="Filter '+esc(label)+' in today’s applications" aria-pressed="'+!!hidden.length+'" aria-expanded="false">▽</button><button type="button" class="column-sort '+(sorted?'sorted':'')+'" data-today-sort="'+key+'" aria-label="Sort '+esc(label)+' in today’s applications">'+sortLabel+'</button><div class="today-column-values" data-today-values="'+key+'" hidden>'+values.map(v=>'<label><input type="checkbox" data-today-value="'+key+'" value="'+esc(v)+'" '+(hidden.includes(v)?'':'checked')+'>'+esc(v||'(Blank)')+'</label>').join('')+'<button type="button" class="text-button" data-today-clear="'+key+'">Clear filter</button></div></th>';
 }).join('')+'<th></th></tr></thead><tbody>'+rows.map(job=>opportunityRow(job,false)).join('')+'</tbody></table></div>'+(!rows.length?'<p class="loading">'+(jobs.length?'No applications match these column filters.':'No applications recorded for today yet.')+'</p>':'');
 section.querySelectorAll('[data-today-filter]').forEach(button=>button.onclick=()=>{const panel=section.querySelector('[data-today-values="'+button.dataset.todayFilter+'"]');panel.hidden=!panel.hidden;button.setAttribute('aria-expanded',String(!panel.hidden));});
 section.querySelectorAll('[data-today-sort]').forEach(button=>button.onclick=()=>{const key=button.dataset.todaySort;appliedTodaySort={key,direction:appliedTodaySort.key===key&&appliedTodaySort.direction==='asc'?'desc':'asc'};renderAppliedToday();});
 section.querySelectorAll('[data-today-value]').forEach(input=>input.onchange=()=>{const key=input.dataset.todayValue;appliedTodayHidden[key]=[...section.querySelectorAll('[data-today-value="'+key+'"]')].filter(i=>!i.checked).map(i=>i.value);renderAppliedToday();});
 section.querySelectorAll('[data-today-clear]').forEach(button=>button.onclick=()=>{delete appliedTodayHidden[button.dataset.todayClear];renderAppliedToday();});
 section.querySelectorAll('[data-job]').forEach(button=>button.onclick=()=>openJob(button.dataset.job));
 bindWorkspaceRows(section);
}
