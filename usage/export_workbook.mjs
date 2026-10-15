// Regenerate the Excel view from the private SQLite snapshot; never edit it by hand.
import fs from "node:fs/promises";
import path from "node:path";
import { createRequire } from "node:module";

const deps = process.env.CODEX_USAGE_NODE_MODULES;
if (!deps) throw new Error("CODEX_USAGE_NODE_MODULES must point to the bundled Codex node_modules directory");
const requireBundled = createRequire(path.join(deps,"_codex_usage.cjs"));
const { SpreadsheetFile, Workbook } = requireBundled("@oai/artifact-tool");

const input = process.argv[2];
const target = process.argv[3];
if (!input || !target) throw new Error("Usage: node export_workbook.mjs snapshot.json workbook.xlsx");
const rows = JSON.parse(await fs.readFile(input, "utf8"));
const safe = (v) => {
  if (v == null) return "";
  if (typeof v === "string" && /^[=+\-@\t\r]/.test(v)) return "'" + v;
  return v;
};
const sourceLabel = source => source === "vscode" ? "Cursor/Codex" : safe(source);
const fastMode = tier => ["fast", "priority"].includes(tier) ? "Yes" : tier === "default" ? "No" : "Unknown";
const taskFastMode = list => {
  const modes = new Set(list.map(r => fastMode(r.service_tier)));
  const partial = modes.delete("Unknown");
  if (!modes.size) return "Unknown";
  const result = modes.size > 1 ? "Mixed" : [...modes][0];
  return partial ? `${result} (partial)` : result;
};
const workbook = Workbook.create();
const summary = workbook.worksheets.add("Summary");
const tasks = workbook.worksheets.add("Tasks");
const turns = workbook.worksheets.add("Turns");
const groups = new Map();
for (const row of rows) {
  if (!groups.has(row.session_id)) groups.set(row.session_id, []);
  groups.get(row.session_id).push(row);
}
const sessions = [...groups].map(([id, list]) => {
  list.sort((a,b)=>(a.started_utc||"").localeCompare(b.started_utc||""));
  const first = list[0], last = list.at(-1);
  const status = list.some(r=>r.status==="running") ? "in progress" :
                 list.some(r=>r.status==="interrupted") ? "interrupted" : "completed";
  const finished = status !== "in progress";
  const sum = key => list.some(r=>r[key]!=null) ? list.reduce((n,r)=>n+(r[key]||0),0) : null;
  return {id,first,last,finished,status,turns:list.length,description:list.find(r=>r.description)?.description||"",
          duration:list.reduce((n,r)=>n+(r.duration_seconds||0),0),input:sum("input_tokens"),
          output:sum("output_tokens"),total:sum("total_tokens")};
}).sort((a,b)=>(b.first.started_utc||"").localeCompare(a.first.started_utc||""));
summary.showGridLines = false;
tasks.showGridLines = false;
turns.showGridLines = false;
summary.getRange("A1:F1").merge();
summary.getRange("A1").values = [["Codex task usage"]];
summary.getRange("A1:F1").format = {fill:"#16324F", font:{name:"Aptos",bold:true,color:"#FFFFFF",size:16}};
summary.getRange("A3:B9").values = [
  ["Recorded tasks", sessions.length],
  ["Completed tasks", sessions.filter(s=>s.status==="completed").length],
  ["Tasks with token data", sessions.filter(s=>s.total != null).length],
  ["Total observed tokens", rows.reduce((n,r)=>n+(r.total_tokens||0),0)],
  ["Input tokens", rows.reduce((n,r)=>n+(r.input_tokens||0),0)],
  ["Output tokens", rows.reduce((n,r)=>n+(r.output_tokens||0),0)],
  ["Scope", "All local Codex sessions"]
];
summary.getRange("A10:F10").merge();
summary.getRange("A10").values = [["Usage left is the account-wide 7-day meter: last reading before and last reading during each task. Cost is unavailable."]];
summary.getRange("A12:B12").values = [["Mountain date", "Observed tokens"]];
const byDay = new Map();
for (const r of rows) if (r.local_date) byDay.set(r.local_date,(byDay.get(r.local_date)||0)+(r.total_tokens||0));
const days = [...byDay].sort((a,b)=>a[0].localeCompare(b[0])).slice(-30);
if(days.length) summary.getRangeByIndexes(12,0,days.length,2).values = days;
summary.getRange("A12:B12").format = {fill:"#226B82",font:{name:"Aptos",bold:true,color:"#FFFFFF"}};
summary.getRange("A1:A45").format.columnWidth = 22;
summary.getRange("B1:B45").format.columnWidth = 22;
summary.getRange("C1:F45").format.columnWidth = 14;
summary.getRange("A10:F10").format.wrapText = true;
summary.getRange("A10:F10").format.rowHeight = 32;
summary.getRange("B3:B8").setNumberFormat("#,##0");
if(days.length) summary.getRange(`B13:B${12+days.length}`).setNumberFormat("#,##0");
if(days.length >= 2) {
  const chart = summary.charts.add("line",summary.getRange(`A12:B${12+days.length}`));
  chart.title = "Tokens by day";
  chart.hasLegend = false;
  chart.yAxis = {numberFormatCode:"#,##0",numberFormatSourceLinked:false};
  chart.setPosition("D12","M28");
}
const headers = ["Started (Mountain)","Ended (Mountain)","Duration (min)","Status","Task description","Source","Terminal name","Model","Effort","Fast mode","Input tokens","Cached input","Cache write input","Output tokens","Reasoning output","Total tokens","Usage left before (%)","Usage left after (%)","Usage Used %","Before sampled (Mountain)","Window resets (Mountain)","Turn ID","Git branch","Working directory"];
turns.getRangeByIndexes(0,0,1,headers.length).values = [headers];
const local = value => value ? new Intl.DateTimeFormat("en-US",{timeZone:"America/Denver",year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hour12:true}).format(new Date(value)) : "";
const sessionHeaders = ["Created (Mountain)","Last completed (Mountain)","Work duration (min)","Status","Task description","Turns","Usage left before (%)","Usage left after (%)","Usage Used %","Before sampled (Mountain)","After sampled (Mountain)","Source","Model","Effort","Fast Mode","Git branch","Working directory","Input tokens","Output tokens","Total tokens"];
tasks.getRangeByIndexes(0,0,1,sessionHeaders.length).values = [sessionHeaders];
const taskValues = sessions.map(s=>[local(s.first.started_utc),s.finished?local(s.last.ended_utc):"",s.duration?Math.round(s.duration/6)/10:"",s.status,safe(s.description),s.turns,s.first.usage_left_before_percent??"",s.finished?s.last.usage_left_after_percent??"":"","",local(s.first.usage_before_observed_utc),s.finished?local(s.last.usage_after_observed_utc):"",sourceLabel(s.first.source),safe(s.first.model),safe(s.first.effort),taskFastMode(groups.get(s.id)),safe(s.first.git_branch),safe(s.first.working_directory),s.input??"",s.output??"",s.total??""]);
if(taskValues.length) tasks.getRangeByIndexes(1,0,taskValues.length,sessionHeaders.length).values = taskValues;
if(taskValues.length) {
  tasks.getRange("I2").formulas = [['=IF(OR(G2="",H2=""),"",G2-H2)']];
  tasks.getRange(`I2:I${taskValues.length+1}`).fillDown();
}
tasks.getRangeByIndexes(0,0,1,sessionHeaders.length).format = {fill:"#16324F",font:{name:"Aptos",bold:true,color:"#FFFFFF"}};
tasks.freezePanes.freezeRows(1);
const taskLast = Math.max(taskValues.length+1,2);
tasks.getRange(`A1:B${taskLast}`).format.columnWidth = 25;
tasks.getRange(`C1:D${taskLast}`).format.columnWidth = 20;
tasks.getRange(`E1:E${taskLast}`).format.columnWidth = 62;
tasks.getRange(`F1:H${taskLast}`).format.columnWidth = 21;
tasks.getRange(`I1:I${taskLast}`).format.columnWidth = 20;
tasks.getRange(`J1:K${taskLast}`).format.columnWidth = 25;
tasks.getRange(`L1:O${taskLast}`).format.columnWidth = 17;
tasks.getRange(`P1:P${taskLast}`).format.columnWidth = 20;
tasks.getRange(`Q1:Q${taskLast}`).format.columnWidth = 52;
tasks.getRange(`R1:T${taskLast}`).format.columnWidth = 19;
if(taskValues.length) {
  tasks.getRangeByIndexes(1,6,taskValues.length,3).setNumberFormat('0"%"');
  tasks.getRangeByIndexes(1,17,taskValues.length,3).setNumberFormat("#,##0");
}
const values = rows.map(r=>[local(r.started_utc),local(r.ended_utc),r.duration_seconds == null ? "" : Math.round(r.duration_seconds/6)/10,safe(r.status),safe(r.description),sourceLabel(r.source),safe(r.terminal_name),safe(r.model),safe(r.effort),fastMode(r.service_tier),r.input_tokens ?? "",r.cached_input_tokens ?? "",r.cache_write_input_tokens ?? "",r.output_tokens ?? "",r.reasoning_output_tokens ?? "",r.total_tokens ?? "",r.usage_left_before_percent ?? "",r.usage_left_after_percent ?? "","",local(r.usage_before_observed_utc),r.usage_window_resets_at ? local(new Date(r.usage_window_resets_at*1000).toISOString()) : "",safe(r.turn_id),safe(r.git_branch),safe(r.working_directory)]);
if(values.length) turns.getRangeByIndexes(1,0,values.length,headers.length).values = values;
if(values.length) {
  turns.getRange("S2").formulas = [['=IF(OR(Q2="",R2=""),"",Q2-R2)']];
  turns.getRange(`S2:S${values.length+1}`).fillDown();
}
turns.getRangeByIndexes(0,0,1,headers.length).format = {fill:"#226B82",font:{name:"Aptos",bold:true,color:"#FFFFFF"}};
turns.freezePanes.freezeRows(1);
const lastRow = Math.max(values.length+1,2);
turns.getRange(`A1:B${lastRow}`).format.columnWidth = 23;
turns.getRange(`C1:D${lastRow}`).format.columnWidth = 15;
turns.getRange(`E1:E${lastRow}`).format.columnWidth = 62;
turns.getRange(`F1:I${lastRow}`).format.columnWidth = 18;
turns.getRange(`J1:J${lastRow}`).format.columnWidth = 17;
turns.getRange(`K1:P${lastRow}`).format.columnWidth = 17;
turns.getRange(`Q1:R${lastRow}`).format.columnWidth = 24;
turns.getRange(`S1:S${lastRow}`).format.columnWidth = 20;
turns.getRange(`T1:U${lastRow}`).format.columnWidth = 25;
turns.getRange(`V1:V${lastRow}`).format.columnWidth = 39;
turns.getRange(`W1:W${lastRow}`).format.columnWidth = 20;
turns.getRange(`X1:X${lastRow}`).format.columnWidth = 52;
if(values.length) {
  turns.getRangeByIndexes(0,0,values.length+1,headers.length).format.font.name = "Aptos";
  turns.getRangeByIndexes(1,10,values.length,6).setNumberFormat("#,##0");
  turns.getRangeByIndexes(1,16,values.length,2).setNumberFormat('0"%"');
  turns.getRangeByIndexes(1,18,values.length,1).setNumberFormat('0"%"');
}
workbook.recalculate();
await fs.mkdir(path.dirname(target),{recursive:true});
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(target + ".tmp.xlsx");
await fs.rename(target + ".tmp.xlsx",target);
console.log(`Exported ${sessions.length} tasks and ${rows.length} turns to ${target}`);
