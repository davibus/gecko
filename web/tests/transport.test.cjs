'use strict';
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const zlib=require('node:zlib');

async function main(){
 const notes='Complete notes with unicode: résumé 🦎. '.repeat(50000);
 const snapshot={jobs:[{id:'test-job',fields:{Notes:notes}}]};
 const packed=zlib.deflateSync(JSON.stringify(snapshot));
 const split=Math.ceil(packed.length/3);
 const chunks=[packed.subarray(0,split),packed.subarray(split,split*2),packed.subarray(split*2)];
 let starts=0;
 const requests=[];
 const fetch=async path=>{
  requests.push(path);
  if(path==='/api/jobs'){starts++;return Response.json({ticket:'ticket'},{status:202});}
  if(path==='/cloud/result/ticket')return Response.json({packed:true,chunks:3,status:200,content_type:'application/json',csrf:'session-csrf'});
  const matched=path.match(/^\/cloud\/chunk\/ticket\/(\d)$/);
  if(matched)return new Response(chunks[Number(matched[1])]);
  throw Error('Unexpected request '+path);
 };
 const window={fetch};
 const sandbox={window,Response,Blob,DecompressionStream,URL,location:{assign(){throw Error('Unexpected sign-in redirect');}},
  document:{addEventListener(){}},setTimeout:fn=>setTimeout(fn,0),setInterval(){},console};
 vm.runInNewContext(fs.readFileSync(require('node:path').join(__dirname,'../assets/cloud.js'),'utf8'),sandbox);
 const response=await window.fetch('/api/jobs');
 assert.equal(response.status,200);
 const actual=await response.json();
 assert.equal(actual.jobs[0].fields.Notes,notes);
 assert.equal(actual.token,'session-csrf');
 assert.equal(starts,1,'A request must never be automatically resubmitted');
 assert.equal(requests.filter(path=>path.includes('/cloud/chunk/')).length,3);
 console.log('Browser transport: complete Unicode notes, session token, and single submission passed.');
 const deviceEvents=[];
 const deviceKey='a'.repeat(64);
 const deviceSandbox={
  location:{hash:'#'+deviceKey,replace:path=>deviceEvents.push(['open',path])},
  history:{replaceState:(_state,_title,path)=>deviceEvents.push(['scrub',path])},
  fetch:async(path,options)=>{
   assert.deepEqual(deviceEvents,[['scrub','/connect']],'Remove the key from the address before transmitting it');
   assert.equal(path,'/cloud/connect');assert.equal(JSON.parse(options.body).token,deviceKey);
   deviceEvents.push(['exchange',path]);return Response.json({ok:true});
  },
  document:{getElementById(){throw Error('Unexpected connection error');}}
 };
 await vm.runInNewContext(fs.readFileSync(require('node:path').join(__dirname,'../assets/device.js'),'utf8'),deviceSandbox);
 assert.deepEqual(deviceEvents,[['scrub','/connect'],['exchange','/cloud/connect'],['open','/']]);
 console.log('Automatic device access: private key removed from address before exchange, then dashboard opened.');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
