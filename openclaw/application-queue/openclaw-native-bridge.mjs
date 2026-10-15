import {n as request} from '/home/dcall/.openclaw/tools/node-v24.21.0/lib/node_modules/openclaw/dist/browser-cli-shared-uLQrGI9S.mjs';
import net from 'node:net';
import fs from 'node:fs';
const socket='/tmp/openclaw/gecko-batch-1311-1407.sock';
if(fs.existsSync(socket))throw Error('Existing bridge socket; do not duplicate');
const server=net.createServer(client=>{let buffer='';client.on('data',async data=>{buffer+=data.toString();const nl=buffer.indexOf('\n');if(nl<0)return;client.pause();try{const p=JSON.parse(buffer.slice(0,nl));if(!['GET','POST','DELETE'].includes(p.method)||!/^\/(tabs(?:\/[^?]+)?|snapshot|act|hooks\/file-chooser)$/.test(p.path))throw Error('Unsupported browser route');const result=await request({json:true,browserProfile:'openclaw'},p,{timeoutMs:60000});client.end(JSON.stringify({ok:true,result})+'\n');}catch(e){client.end(JSON.stringify({ok:false,error:String(e)})+'\n');}});});
server.listen(socket,()=>{fs.chmodSync(socket,0o600);process.stdout.write('OPENCLAW_NATIVE_BROWSER_BRIDGE_READY\n');});
