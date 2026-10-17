'use strict';
const GeckoMatchScores = (() => {
 const factors = [
  ['ability','Core skills','The important skills the role requires.'],
  ['ability','Relevant experience','Similar work you have already done.'],
  ['ability','Seniority','The right level of responsibility.'],
  ['ability','Industry familiarity','Knowledge of the industry and customers.'],
  ['ability','Tools and technology','Their systems or transferable equivalents.'],
  ['ability','Education and certifications','The stated requirements you meet.'],
  ['ability','Evidence of results','Accomplishments that address their needs.'],
  ['ability','Transferable skills','Experience that can bridge the gaps.'],
  ['desire','Daily responsibilities','How much you would enjoy the daily work.'],
  ['ability','Strengths alignment','How well the role uses your strengths.'],
  ['desire','Leadership balance','The right mix of managing and doing.'],
  ['ability','Scope of work','Familiar team, budget, or operational scale.'],
  ['ability','Learning curve','How quickly you could become effective.'],
  ['desire','Compensation','How well the pay meets your target.'],
  ['desire','Benefits','How well the benefits meet your needs.'],
  ['desire','Location','An acceptable location or commute.'],
  ['desire','Remote flexibility','Your preferred working arrangement.'],
  ['desire','Schedule','Workable hours and availability.'],
  ['desire','Travel','An acceptable amount of travel.'],
  ['desire','Employment type','Permanent, contract, or temporary fit.'],
  ['desire','Company interest','How much you want to work here.'],
  ['desire','Career direction','Progress toward your next goal.'],
  ['opportunity','Company stability','Confidence in the company outlook.'],
  ['opportunity','Hiring momentum','Evidence the opening is active.'],
  ['opportunity','Connection advantage','A referral or relevant relationship.']
 ];
 const groups={ability:'Can I do it?',desire:'Do I want it?',opportunity:'Opportunity signals'};
 const key='gecko.match-scores.v1';
 let model={weights:factors.map(()=>1),drafts:{},selected:'scratch'}, storageWarning='';
 const cleanEntry=x=>({ratings:factors.map((_,i)=>Number.isInteger(x?.ratings?.[i])&&x.ratings[i]>=0&&x.ratings[i]<=5?x.ratings[i]:null),blocked:x?.blocked===true,notes:typeof x?.notes==='string'?x.notes:''});
 function read(){try{const x=JSON.parse(localStorage.getItem(key));if(x&&typeof x==='object'){model.weights=factors.map((_,i)=>Number.isFinite(x.weights?.[i])?Math.max(0,Math.min(10,x.weights[i])):1);model.drafts={};for(const [id,draft] of Object.entries(x.drafts||{}))if(id==='scratch'||id.startsWith('job:'))model.drafts[id]=cleanEntry(draft);if(x.selected==='scratch'||String(x.selected).startsWith('job:'))model.selected=x.selected;}}catch{storageWarning='Browser storage is unavailable or could not be read. Changes may last only until this page closes.';}}
 function save(){try{localStorage.setItem(key,JSON.stringify(model));storageWarning='';}catch{storageWarning='Could not save in this browser. Keep this page open to retain your changes.';}const status=document.getElementById('match-save-status');if(status)status.textContent=storageWarning||'Saved in this browser. Ratings are personal assessments; job records are unchanged.';}
 function calculate(ratings,weights,group){let earned=0,rated=0,total=0;factors.forEach((f,i)=>{if(group&&f[0]!==group)return;const w=weights[i]||0;total+=w;if(Number.isFinite(ratings[i])&&ratings[i]>=0&&ratings[i]<=5){rated+=w;earned+=w*ratings[i]/5;}});return {score:rated?Math.round(earned/rated*100):null,coverage:total?Math.round(rated/total*100):0,rated,total};}
 function draft(){return model.drafts[model.selected]||(model.drafts[model.selected]=cleanEntry({}));}
 function summary(){const d=draft(),overall=calculate(d.ratings,model.weights),cards=[['Application priority',overall],...Object.entries(groups).map(([id,label])=>[label,calculate(d.ratings,model.weights,id)])];document.getElementById('match-summary').innerHTML=cards.map(([label,s])=>`<div class="stat"><span class="stat-label">${esc(label)}</span><strong>${s.score===null?'—':s.score+'/100'}</strong><small>${s.coverage}% of weighted factors rated</small></div>`).join('');document.getElementById('match-verdict').textContent=d.blocked?'Dealbreaker flagged — review before prioritizing this job.':!overall.total?'All weights are zero. Give at least one factor a weight.':overall.score===null?'Choose ratings to begin. Unknown factors stay out of the score.':overall.coverage<100?'Provisional score — some factors are still unknown.':'All active factors rated. This is a fit score, not a hiring probability.';}
 function render(jobs){
  const root=document.getElementById('match-section');if(!root)return;
  const d=draft(),sorted=[...jobs].sort((a,b)=>String(a.fields.Company).localeCompare(String(b.fields.Company)));
  const known=sorted.some(j=>'job:'+j.id===model.selected);
  root.innerHTML=`<div class="activity-card"><h2>Your match score playground</h2><p>Try the 25 factors below. Rate each from 0 (poor fit) to 5 (excellent fit). Use weight 0 to ignore a factor, or up to 10 to emphasize it. Weights carry across jobs; ratings and notes are saved separately for each job in this browser.</p><label class="match-picker">Try a job<select id="match-job" aria-label="Try a job"><option value="scratch">Practice / scratchpad</option>${!known&&model.selected!=='scratch'?`<option value="${esc(model.selected)}" selected>Previously selected job (${esc(model.selected.slice(4))})</option>`:''}${sorted.map(j=>`<option value="${esc('job:'+j.id)}" ${model.selected==='job:'+j.id?'selected':''}>${esc(j.fields.Company)} · ${esc(j.fields['Job Title'])} (#${esc(j.id)})</option>`).join('')}</select></label><p>Scores are your own assessment. Existing saved Gecko scores are not imported or replaced. Application priority is the weighted average of all rated factors; the other cards show its components.</p><p>These numbers are not interview or offer probabilities. Those require evidence from actual hiring outcomes.</p></div><div id="match-summary" class="match-summary"></div><p id="match-verdict" role="status"></p><div class="activity-card"><label><input id="match-blocked" type="checkbox" ${d.blocked?'checked':''}> This job has a dealbreaker</label><label class="match-picker">Notes<textarea id="match-notes" rows="3" placeholder="What makes this job a good or poor fit?">${esc(d.notes)}</textarea></label><div class="actions"><button id="match-clear" class="button secondary">Clear this job’s ratings and notes</button><button id="match-reset-weights" class="button secondary">Reset all weights to 1</button></div><p id="match-save-status" role="status">${esc(storageWarning||'Saved in this browser. Ratings are personal assessments; job records are unchanged.')}</p></div>${Object.entries(groups).map(([group,label])=>`<div class="match-group"><h2>${label}</h2><div class="match-factors">${factors.map(([g,name,help],i)=>g===group?`<div class="match-factor"><h3>${i+1}. ${esc(name)}</h3><p>${esc(help)}</p><div class="match-controls"><label>Rating<select data-match-rating="${i}" aria-label="${esc(name)} rating"><option value="">Unknown</option>${[0,1,2,3,4,5].map(n=>`<option value="${n}" ${d.ratings[i]===n?'selected':''}>${n}${n===0?' — Poor fit':n===5?' — Excellent fit':''}</option>`).join('')}</select></label><label>Weight<input data-match-weight="${i}" aria-label="${esc(name)} weight" type="number" min="0" max="10" step="1" value="${model.weights[i]}"></label></div></div>`:'').join('')}</div></div>`).join('')}`;
  document.getElementById('match-job').onchange=e=>{model.selected=e.target.value;save();render(jobs);};
  root.querySelectorAll('[data-match-rating]').forEach(el=>el.onchange=()=>{draft().ratings[Number(el.dataset.matchRating)]=el.value===''?null:Number(el.value);save();summary();});
  root.querySelectorAll('[data-match-weight]').forEach(el=>el.onchange=()=>{const value=el.value===''?1:Number(el.value);model.weights[Number(el.dataset.matchWeight)]=Number.isFinite(value)?Math.max(0,Math.min(10,Math.round(value))):1;el.value=model.weights[Number(el.dataset.matchWeight)];save();summary();});
  document.getElementById('match-blocked').onchange=e=>{draft().blocked=e.target.checked;save();summary();};
  document.getElementById('match-notes').oninput=e=>{draft().notes=e.target.value;save();};
  document.getElementById('match-clear').onclick=()=>{model.drafts[model.selected]=cleanEntry({});save();render(jobs);};
  document.getElementById('match-reset-weights').onclick=()=>{model.weights=factors.map(()=>1);save();render(jobs);};
  summary();
 }
 if(typeof window!=='undefined')read();
 return {render,calculate,factors};
})();
if(typeof module!=='undefined')module.exports=GeckoMatchScores;
