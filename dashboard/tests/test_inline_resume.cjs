const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(process.argv[2]||'dashboard/static/manual.js','utf8');
function fixture(options={}){
 const job={id:'2848',version:'v1',url:'https://example.com/mira',applied:!!options.applied,eligible:true,can_generate:false,fields:{Company:'Mira Home','Job Title':'Senior Google Ads Specialist',Source:'Indeed',Location:'Lindon, UT 84042',Salary:'$95,000',Notes:'My notes','Resume Created':options.created?'X':'','Resume Link':''},notes:'My notes',description:options.short?'Short draft':'Saved facts. '.repeat(60),meta:{}};
 const controls={};
 for(const name of ['url','Company','Job Title','Source','Location','Salary','Work Arrangement','Employment Type','Personal priority','Date Posted','Notes','description','applied_date'])controls[name]={name,value:'',disabled:false,willValidate:false,validity:{valid:true},focus(){}};
 controls.applied={name:'applied',type:'checkbox',checked:false,disabled:false};
 const elements=Object.values(controls);Object.assign(elements,controls,{namedItem:key=>controls[key]});
 const form={elements,querySelector:()=>({})},nodes={'manual-form':form};
 for(const key of ['manual-form-title','manual-status','manual-save-status','manual-save','manual-save-applied','manual-new','manual-generated-resume','manual-resume-status','manual-resume-remove','manual-create-resume'])nodes[key]={};
 const calls=[];
 const ctx=vm.createContext({$:id=>nodes[id],esc:value=>String(value??''),state:{jobs:[job],manualIds:[job.id]},setInterval(){},setTimeout,localStorage:{setItem(){},removeItem(){}},today:()=> '2026-10-17',notify(){},window:{scrollTo(){}},FormData:class{constructor(f){this.f=f;}*[Symbol.iterator](){for(const el of this.f.elements)if(el.name&&el.type!=='checkbox'&&!el.disabled)yield [el.name,el.value];}},api:async(path,body)=>{
  calls.push({path,body});
  if(path==='/api/activity')return {busy:!!options.busy};
  if(path.startsWith('/api/job?'))return JSON.parse(JSON.stringify(job));
  if(path==='/api/manual-import')return body?{status:'running'}:options.blocked?{status:'failed',error:'Posting requires verification'}:{status:'ready',url:job.url,details:{Company:options.wrong?'Different employer':job.fields.Company,'Job Title':job.fields['Job Title'],Salary:'Do not replace my saved salary','Employment Type':'Full time',description:'Additional verified posting detail. '.repeat(25)}};
  if(path==='/api/manual'){assert.equal(body.id,'2848');assert.equal(body.version,'v1');Object.assign(job.fields,body);job.description=body.description;job.version='v2';return {id:job.id,updated:true,applied:false};}
  if(path==='/api/edit'){assert.equal(body.action,'approve');assert.equal(body.version,'v2');job.fields['Apply?']='Yes';job.can_generate=true;job.version='v3';return JSON.parse(JSON.stringify(job));}
  if(path==='/api/run')return {kind:'resume',job_id:2848,status:'running'};
  throw Error('Unexpected request '+path);
 }});
 vm.runInContext(source,ctx);ctx.renderManualTable=()=>{};
 return {ctx,job,calls,nodes,controls};
}
(async()=>{
 let f=fixture();await f.ctx.openManualJob('2848');f.calls.length=0;await f.ctx.createManualResumeFromProfile();
 const save=f.calls.find(c=>c.path==='/api/manual').body;
 assert.equal(save.id,'2848');assert.equal(save.applied,false);assert.equal(save.Salary,'$95,000');assert.equal(save.Notes,'My notes');assert.equal(save['Employment Type'],'Full time');assert.match(save.description,/Saved facts/);assert.match(save.description,/Additional verified posting detail/);
 const run=f.calls.find(c=>c.path==='/api/run').body;assert.equal(run.id,'2848');assert.equal(run.version,'v3');assert.equal(run.manual_upload,true);
 assert.equal(f.calls.filter(c=>c.path==='/api/run').length,1);assert.equal(f.nodes['manual-create-resume'].disabled,true);assert.match(f.nodes['manual-status'].textContent,/Creating the tailored resume for job 2848/);
 assert.equal(f.ctx.state.jobs.length,1);assert.equal(f.calls.some(c=>c.path==='/api/applications'),false);
 for(const options of [{created:true},{applied:true},{wrong:true},{blocked:true,short:true},{busy:true}]){
  f=fixture(options);await f.ctx.openManualJob('2848');f.calls.length=0;await f.ctx.createManualResumeFromProfile();
  assert.equal(f.calls.some(c=>c.path==='/api/run'),false,JSON.stringify(options));assert.equal(f.calls.some(c=>c.path==='/api/manual'),false,JSON.stringify(options));
 }
 f=fixture({blocked:true});await f.ctx.openManualJob('2848');f.calls.length=0;await f.ctx.createManualResumeFromProfile();
 assert.equal(f.calls.find(c=>c.path==='/api/manual').body.description,'Saved facts. '.repeat(60));assert.match(f.nodes['manual-status'].textContent,/posting could not be refreshed/);
 assert.doesNotMatch(source,/manual-create-dialog|showModal|openManualResume/);
 console.log('Inline profile resume flow: same ID, posting enrichment, protected fields, completion guard, blocked-posting handling and no popup passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
