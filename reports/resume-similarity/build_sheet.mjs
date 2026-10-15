import fs from 'node:fs/promises';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';

const root = 'C:/gecko_main/reports/resume-similarity';
const data = JSON.parse(await fs.readFile(`${root}/workbook-data.json`, 'utf8'));
const book = Workbook.create();
const summary = book.worksheets.add('Overview');
const index = book.worksheets.add('Resume Index');
const closest = book.worksheets.add('Closest Pairs');
const matrix = book.worksheets.add('Difference Matrix');
const method = book.worksheets.add('Method');
const gray = '#E8EAED';
const dark = '#202124';

function header(sheet, address) {
  sheet.getRange(address).format = {
    fill: gray,
    font: { name: 'Arial', size: 10, bold: true, color: dark },
  };
}
function body(sheet, address) {
  sheet.getRange(address).format.font = { name: 'Arial', size: 10, color: dark };
}

summary.getRange('A1').values = [['Gecko Main resume similarity']];
summary.getRange('A1').format.font = { name: 'Arial', size: 16, bold: true, color: dark };
summary.getRange('A3:B12').values = [
  ['Resumes analyzed', data.summary.resume_count],
  ['Pairwise comparisons', data.summary.pair_count],
  ['Identical-text pairs', data.summary.exact_text_duplicate_pairs],
  ['Duplicate groups', data.summary.duplicate_groups],
  ['Resumes in duplicate groups', data.summary.resumes_in_duplicate_groups],
  ['Median wording difference', data.summary.median_difference_pct],
  ['Lowest wording difference', data.summary.min_difference_pct],
  ['Highest wording difference', data.summary.max_difference_pct],
  ['Unreadable files', data.summary.unreadable.length],
  ['Source folder', data.summary.source_folder],
];
summary.getRange('A14:B17').values = [
  ['Modified date', 'Resumes'],
  ...Object.entries(data.summary.resume_dates).sort((a,b)=>b[0].localeCompare(a[0])),
];
summary.getRange('A19:B22').values = [
  ['How to use', ''],
  ['Resume Index', 'Find a resume number and its nearest match.'],
  ['Closest Pairs', 'Review the 250 most similar pairs and section breakdowns.'],
  ['Difference Matrix', 'Look up any two resume numbers; row and column intersection is the difference percentage.'],
];
summary.getRange('A24:B25').values = [
  ['Interpretation', '0% means identical four-word phrases across tailored sections; 100% means none shared.'],
  ['Snapshot', 'Analysis of the local DOCX files. Changes to resumes require a fresh run.'],
];
body(summary, 'A1:B25');
header(summary, 'A14:B14');
header(summary, 'A19:B19');
summary.getRange('A3:A12').format.font = { name:'Arial', size:10, bold:true, color:dark };
summary.getRange('A24:A25').format.font = { name:'Arial', size:10, bold:true, color:dark };
summary.getRange('A:A').format.columnWidth = 29;
summary.getRange('B:B').format.columnWidth = 75;
summary.getRange('B8:B10').setNumberFormat('0.00"%"');

const indexHeaders = ['#','Company','Role','Job ID','Modified (local)','Nearest difference %','Nearest resume #','Average difference %','Exact duplicate peers','DOCX filename'];
index.getRange('A1:J1').values = [indexHeaders];
for (let start=0; start<data.index.length; start+=100) {
  const rows=data.index.slice(start,start+100);
  index.getRangeByIndexes(start+1,0,rows.length,10).values=rows;
}
body(index,'A1:J413');
header(index,'A1:J1');
index.freezePanes.freezeRows(1);
index.getRange('A:A').format.columnWidth=7;
index.getRange('B:B').format.columnWidth=22;
index.getRange('C:C').format.columnWidth=48;
index.getRange('D:D').format.columnWidth=20;
index.getRange('E:E').format.columnWidth=21;
index.getRange('F:I').format.columnWidth=20;
index.getRange('J:J').format.columnWidth=98;
index.getRange('F2:F413').setNumberFormat('0.00"%"');
index.getRange('H2:H413').setNumberFormat('0.00"%"');

closest.getRange('A1:I1').values=[['Resume A #','Resume B #','Difference %','Identical text','Summary %','Strengths %','Results %','Experience %','Tools %']];
closest.getRangeByIndexes(1,0,data.closest.length,9).values=data.closest;
body(closest,`A1:I${data.closest.length+1}`);
header(closest,'A1:I1');
closest.freezePanes.freezeRows(1);
closest.getRange('A:I').format.columnWidth=18;
closest.getRange(`C2:C${data.closest.length+1}`).setNumberFormat('0.00"%"');
closest.getRange(`E2:I${data.closest.length+1}`).setNumberFormat('0.00"%"');

const n=data.matrix.length;
matrix.getRangeByIndexes(0,0,1,n+1).values=[['Resume #',...Array.from({length:n},(_,i)=>i+1)]];
for (let start=0;start<n;start+=20) {
  const rows=data.matrix.slice(start,start+20).map((row,i)=>[start+i+1,...row]);
  matrix.getRangeByIndexes(start+1,0,rows.length,n+1).values=rows;
}
header(matrix,`A1:OW1`);
header(matrix,`A2:A${n+1}`);
matrix.freezePanes.freezeRows(1);
matrix.freezePanes.freezeColumns(1);
matrix.getRange('A:A').format.columnWidth=10;
matrix.getRange(`B1:OW${n+1}`).format.columnWidth=9;
matrix.getRange(`B2:OW${n+1}`).setNumberFormat('0.00"%"');

method.getRange('A1').values=[['How the percentages were calculated']];
method.getRange('A1').format.font={name:'Arial',size:15,bold:true,color:dark};
method.getRange('A3:B11').values=[
  ['Source','Each DOCX in C:\\gecko_main\\output\\resumes, including text in paragraphs and tables.'],
  ['Scope','Professional Summary, Core Strengths, Selected Results, Professional Experience, and Tools & Platforms.'],
  ['Normalization','Lowercase text, ignore punctuation and extra spaces, then form overlapping four-word phrases.'],
  ['Difference percentage','100 × (1 − shared phrases ÷ all distinct phrases in the pair).'],
  ['0%','The two tailored sections have the same set of four-word phrases.'],
  ['100%','The two tailored sections share no four-word phrases.'],
  ['Identical text','All extracted resume body text matches after case, punctuation, and spacing normalization.'],
  ['Section percentages','The same phrase comparison applied separately to each named section.'],
  ['Limit','This measures wording overlap, not quality, job fit, truthfulness, or visual layout.'],
];
body(method,'A1:B11');
method.getRange('A3:A11').format.font={name:'Arial',size:10,bold:true,color:dark};
method.getRange('A:A').format.columnWidth=24;
method.getRange('B:B').format.columnWidth=100;

book.recalculate();
for (const [sheetName,range] of [['Overview','A1:B25'],['Resume Index','A1:J8'],['Closest Pairs','A1:I8'],['Difference Matrix','A1:H8'],['Method','A1:B11']]) {
  const check=await book.inspect({kind:'region',sheetId:sheetName,range,maxChars:1000,tableMaxRows:8,tableMaxCols:10});
  console.log(sheetName,check.ndjson.slice(0,900));
}
const preview=await book.render({sheetName:'Overview',range:'A1:B25',scale:1,format:'png'});
await fs.writeFile(`${root}/overview-preview.png`,new Uint8Array(await preview.arrayBuffer()));
const output=await SpreadsheetFile.exportXlsx(book);
await output.save(`${root}/Gecko-Main-Resume-Similarity.xlsx`);
console.log('EXPORTED',`${root}/Gecko-Main-Resume-Similarity.xlsx`);
