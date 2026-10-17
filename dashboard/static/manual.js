'use strict';
const manualFields=['Company','Job Title','Source','Location','Salary','Work Arrangement','Employment Type','Personal priority','Date Posted','Notes','description'];
let manualBusy=false;
const manualFilters={};
let manualSort={key:'ID',direction:1};
function renderManual(){
 const root=$('manual-section');
 $('page-subtitle').textContent='Add a job you found yourself. Review the details, then save it to both this list and All Jobs.';
 if(!root.dataset.built){
  root.dataset.built='yes';
  root.innerHTML='<form id="manual-form" class="activity-card"><h2>Add a job or application</h2><p>A unique job ID is assigned when you save. Saving does not submit an application.</p><label>Job posting link<input name="url" type="url" required placeholder="https://www.indeed.com/viewjob?jk=…"></label><button type="button" id="manual-fetch" class="button secondary">Auto-fill with OpenClaw</button><p id="manual-status" role="status">You can also enter details yourself. Review imported information before saving.</p><div class="manual-fields">'+manualFields.map(k=>'<label>'+esc(k==='description'?'Job description':k)+(k==='Notes'||k==='description'?'<textarea name="'+k+'"></textarea>':'<input name="'+k+'" '+(['Company','Job Title'].includes(k)?'required':'')+(k==='Date Posted'?' type="date"':'')+'>')+'</label>').join('')+'</div><label><input type="checkbox" name="applied"> I already submitted this application</label><label>Application date<input type="date" name="applied_date"></label><div class="actions"><button class="button primary" id="manual-save">Save job</button></div></form><div id="manual-table"></div>';
  const form=$('manual-form');form.elements.applied_date.value=today();
  form.onsubmit=async e=>{e.preventDefault();if(manualBusy)return;const payload=Object.fromEntries(new FormData(form));payload.applied=form.elements.applied.checked;manualBusy=true;$('manual-save').disabled=true;try{const saved=await api('/api/manual',payload);form.reset();form.elements.applied_date.value=today();$('manual-status').textContent='Saved job ID '+saved.id+' to this list and All Jobs.';await refresh();notify('Job '+saved.id+' saved.');}catch(err){$('manual-status').textContent=err.message;}finally{manualBusy=false;$('manual-save').disabled=false;}};
  $('manual-fetch').onclick=async()=>{
   if(manualBusy)return;const url=form.elements.url.value;if(!url){$('manual-status').textContent='Enter a posting link first.';return;}
   manualBusy=true;Array.from(form.elements).forEach(el=>el.disabled=true);$('manual-status').textContent='OpenClaw is reading the posting. This can take a few minutes…';
   try{await api('/api/manual-import',{url});let result;const deadline=Date.now()+440000;do{await new Promise(r=>setTimeout(r,2000));result=await api('/api/manual-import');if(Date.now()>deadline)throw Error('Import is taking too long. You can enter the details manually.');}while(result.status==='running');if(result.status!=='ready')throw Error(result.error||'Import did not finish.');if(result.url!==url)throw Error('The import link changed. Please try again.');for(const key of manualFields)if(result.details[key])form.elements.namedItem(key).value=result.details[key];$('manual-status').textContent='Details imported. Review and correct them, then save.';}catch(err){$('manual-status').textContent=err.message;}finally{manualBusy=false;Array.from(form.elements).forEach(el=>el.disabled=false);}
  };
 }
 renderManualTable();
}
function renderManualTable(){
 const cols=['ID','Company','Job Title','Source','Location','Applied Date','Status'];
 const rows=state.jobs.filter(j=>(state.manualIds||[]).includes(j.id)).map(j=>({...j.fields,ID:j.id,Status:j.applied?'Applied':'Not yet applied','Applied Date':j.fields['Applied Date']||j.meta.applied_at||''}));
 const shown=rows.filter(r=>cols.every(k=>String(r[k]||'').toLowerCase().includes((manualFilters[k]||'').toLowerCase()))).sort((a,b)=>String(a[manualSort.key]||'').localeCompare(String(b[manualSort.key]||''),undefined,{numeric:true})*manualSort.direction);
 $('manual-table').innerHTML='<div class="section-heading"><h2>Your individually added jobs</h2><span>'+shown.length+' of '+rows.length+'</span></div><p>Open a job to record an application or update its next steps. All Jobs uses the same record.</p><div class="table-wrap"><table><thead><tr>'+cols.map(k=>'<th>'+esc(k)+' <button type="button" class="column-filter" data-manual-focus="'+k+'" aria-label="Filter '+k+'">▽</button><button type="button" class="column-filter" data-manual-sort="'+k+'" aria-label="Sort '+k+'">↕</button><input data-manual-filter="'+k+'" aria-label="Search '+k+'" value="'+esc(manualFilters[k]||'')+'" placeholder="Filter…"></th>').join('')+'</tr></thead><tbody>'+shown.map(r=>'<tr>'+cols.map(k=>'<td>'+(k==='Job Title'?'<button class="text-button" data-manual-open="'+esc(r.ID)+'">'+esc(r[k])+'</button>':esc(r[k]||'—'))+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>'+(!rows.length?'<p>No individually added jobs yet. Add your first posting above.</p>':'');
 const root=$('manual-table');root.querySelectorAll('[data-manual-open]').forEach(b=>b.onclick=()=>openJob(b.dataset.manualOpen));
 root.querySelectorAll('[data-manual-filter]').forEach(input=>input.oninput=()=>{const key=input.dataset.manualFilter,caret=input.selectionStart;manualFilters[key]=input.value;renderManualTable();const next=root.querySelector('[data-manual-filter="'+key+'"]');next.focus();next.setSelectionRange(caret,caret);});
 root.querySelectorAll('[data-manual-focus]').forEach(b=>b.onclick=()=>root.querySelector('[data-manual-filter="'+b.dataset.manualFocus+'"]').focus());
 root.querySelectorAll('[data-manual-sort]').forEach(b=>b.onclick=()=>{manualSort={key:b.dataset.manualSort,direction:manualSort.key===b.dataset.manualSort?-manualSort.direction:1};renderManualTable();});
}
