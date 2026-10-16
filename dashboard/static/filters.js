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
  if(f.opportunity && ![fields.Company,fields['Job Title'],fields.Source].join(' ').toLowerCase().includes(f.opportunity.toLowerCase()))return false;
  if(f.location && ![fields.Location,fields['Work Arrangement']].join(' ').toLowerCase().includes(f.location.toLowerCase()))return false;
  if(f.hideApplied&&job.applied || f.hiddenStages.includes(job.stage) || f.hiddenActions.includes(action))return false;
  if(f.minimum!==''||f.maximum!==''||!f.unknown){
   const salary=annualSalary(fields.Salary);
   if(!salary)return f.unknown;
   if(f.minimum!==''&&salary.max<Number(f.minimum))return false;
   if(f.maximum!==''&&salary.min>Number(f.maximum))return false;
  }
  return true;
 }
 return {annualSalary,matches};
})();
if(typeof module!=='undefined')module.exports=GeckoFilters;
