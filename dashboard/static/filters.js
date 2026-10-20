'use strict';
const GeckoFilters = (() => {
 function annualSalary(value){
  const text=String(value||'').trim();
  if(!text || /hour|hr\b|month|week|day\b|EUR|GBP|CAD|AUD|NZD|CHF|INR|€|£|¥|CA\$|AU\$/i.test(text))return null;
  if(!/\$|USD/i.test(text))return null;
  // Only the leading compensation clause; do not combine unrelated figures in descriptions.
  const clause=text.split(/\n|Source:|Salary Transparency/i)[0];
  const tokens=[...clause.matchAll(/(?:USD\s*|\$\s*)?(\d[\d,]*(?:\.\d+)?)\s*(k\b)?/gi)];
  if(!tokens.length||tokens.length>2)return null;
  const nums=tokens.map(m=>Number(m[1].replaceAll(',',''))*(m[2]?1000:1));
  if(nums.some(n=>!Number.isFinite(n)||n<1000))return null;
  return {min:Math.min(...nums),max:Math.max(...nums)};
 }
 function matches(job,f,action){
  const fields=job.fields;
  if((f.hiddenResumes||[]).includes(resumeLabel(job)))return false;
  for(const [field,hidden] of Object.entries(f.hiddenValues||{})){
   if(hidden.includes(String(field==='Applied Date'?(fields[field]||job.meta?.applied_at||''):fields[field]??'').trim()))return false;
  }
  if(f.opportunity && ![fields.Company,fields['Job Title'],fields.Source].join(' ').toLowerCase().includes(f.opportunity.toLowerCase()))return false;
  if(f.location && ![fields.Location,fields['Work Arrangement']].join(' ').toLowerCase().includes(f.location.toLowerCase()))return false;
  if(f.hideApplied&&job.applied || (f.hiddenStages.includes(job.stage)||f.hiddenStages.includes(statusLabel(job))) || f.hiddenActions.includes(action))return false;
  if(f.minimum!==''||f.maximum!==''||!f.unknown){
   const salary=annualSalary(fields.Salary);
   if(!salary)return f.unknown;
   if(f.minimum!==''&&salary.max<Number(f.minimum))return false;
   if(f.maximum!==''&&salary.min>Number(f.maximum))return false;
  }
  return true;
 }
 function compareValues(left,right,direction='asc'){
  const a=String(left??'').trim(),b=String(right??'').trim();
  if(!a||!b)return a? -1:b?1:0;
  return a.localeCompare(b,undefined,{numeric:true,sensitivity:'base'})*(direction==='desc'?-1:1);
 }
 function resumeCreated(job){return String(job.fields['Resume Created']||'').trim().toLowerCase()==='x';}
 function resumeLabel(job){return job.attached_resume?'Manually uploaded':resumeCreated(job)?'Created':'Not created';}
 function needsResume(job){return !job.applied&&!job.resume_available&&!job.attached_resume&&!['Do not apply','Closed','Offer','Interview'].includes(job.stage);}
 function statusLabel(job){return needsResume(job)?'Needs resume':job.stage==='Resume ready'?'Ready to apply':job.stage;}
 return {resumeLabel,annualSalary,matches,compareValues,resumeCreated,needsResume,statusLabel};
})();
if(typeof module!=='undefined')module.exports=GeckoFilters;

'use strict';
const GeckoMetrics = (() => {
 function jobsFound(jobs, day){
  // Date Found is a calendar date, so use UTC arithmetic to avoid DST shifts.
  const prior=new Date(day+'T12:00:00Z');
  prior.setUTCDate(prior.getUTCDate()-1);
  const yesterday=prior.toISOString().slice(0,10);
  const count=date=>jobs.filter(j=>String(j.fields['Date Found']||'').trim()===date).length;
  const todayCount=count(day),yesterdayCount=count(yesterday);
  return {today:todayCount,yesterday:yesterdayCount,total:jobs.length,change:todayCount-yesterdayCount,day,previousDay:yesterday};
 }
 function activity(jobs,day,dateOf){
  const result=jobsFound([],day);
  const dates=jobs.map(dateOf).map(value=>String(value||'').trim().slice(0,10));
  const valid=dates.filter(value=>/^\d{4}-\d{2}-\d{2}$/.test(value));
  result.total=jobs.length;result.undated=jobs.length-valid.length;
  result.today=valid.filter(value=>value===day).length;
  result.yesterday=valid.filter(value=>value===result.previousDay).length;
  result.change=result.today-result.yesterday;
  if(result.undated && !valid.length)result.today=result.yesterday=result.change=null;
  return result;
 }
 function week(jobs,day){
  const dates=Array.from({length:7},(_,i)=>{const d=new Date(day+'T12:00:00Z');d.setUTCDate(d.getUTCDate()+i-6);return d.toISOString().slice(0,10);});
  const active=jobs.filter(j=>!['Closed','Do not apply'].includes(j.stage));
  const definitions=[
   ['found','Jobs Found','#607d42','',jobs,j=>j.fields['Date Found']],
   ['resumes','Resumes Ready','#367cad','7 4',active.filter(j=>!j.applied&&j.resume_available),j=>j.fields['Resume Created Date']||j.fields['Resume Date']||j.meta.resume_created_at],
   ['applications','Applications','#ae7625','2 4',jobs.filter(j=>j.applied),j=>j.fields['Applied Date']||j.meta.applied_at],
   ['followups','Follow-ups Due','#a65682','10 3 2 3',jobs.filter(j=>j.meta.follow_up&&!['Closed','Offer','Do not apply'].includes(j.stage)),j=>j.meta.follow_up]
  ];
  return {dates,series:definitions.map(([key,label,color,dash,rows,dateOf])=>({key,label,color,dash,undated:activity(rows,day,dateOf).undated,values:dates.map(date=>activity(rows,date,dateOf).today)}))};
 }
 return {jobsFound,activity,week};
})();
if(typeof module!=='undefined')module.exports.jobsFound=GeckoMetrics.jobsFound;

if(typeof module!=="undefined")module.exports.activity=GeckoMetrics.activity;

if(typeof module!=="undefined")module.exports.week=GeckoMetrics.week;
