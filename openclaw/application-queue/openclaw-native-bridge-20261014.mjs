import {n as request} from '/home/dcall/.openclaw/tools/node-v24.21.0/lib/node_modules/openclaw/dist/browser-cli-shared-uLQrGI9S.mjs';
import net from 'node:net';
import fs from 'node:fs';
const socket='/home/dcall/.openclaw/gecko-browser-bridge.sock';
if(fs.existsSync(socket))throw Error('Existing bridge socket; do not duplicate');
let queue=Promise.resolve();
const server=net.createServer(client=>{let buffer='',processed=false;client.on('error',()=>{});client.on('data',data=>{if(processed)return;buffer+=data.toString();const nl=buffer.indexOf('\n');if(nl<0)return;processed=true;client.pause();const task=async()=>{try{const p=JSON.parse(buffer.slice(0,nl));if(!['GET','POST','DELETE'].includes(p.method)||!/^\/(tabs(?:\/[^?]+)?|snapshot|act|hooks\/file-chooser)$/.test(p.path))throw Error('Unsupported browser route');const result=await request({json:true,browserProfile:'openclaw'},p,{timeoutMs:60000});if(!client.destroyed)client.end(JSON.stringify({ok:true,result})+'\n');}catch(e){if(!client.destroyed)client.end(JSON.stringify({ok:false,error:String(e)})+'\n');}};queue=queue.then(task,task);});});
server.listen(socket,()=>{fs.chmodSync(socket,0o600);process.stdout.write('OPENCLAW_NATIVE_BROWSER_BRIDGE_READY\n');});
server.on('error',e=>{process.stderr.write(String(e)+'\n');process.exitCode=1;});
