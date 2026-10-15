from pathlib import Path
import shutil
p=Path('/home/dcall/.openclaw/workspace-gecko/AGENTS.md')
s=p.read_text();shutil.copy2(p,p.with_name('AGENTS.md.batch-instructions-backup-20261012T190351.md'))
s=s.replace('Ask Dave for missing required details; never infer employer-specific application\nhistory from a blank Applied cell.', 'Record missing required details as pending and continue to the next approved job;\nnever infer employer-specific application history from a blank Applied cell.')
old='Prepare only the selected approved job. The answer bank does not authorize\nsubmission, CAPTCHA completion, messages, or unrelated tracker changes. Show\ncompleted applications for review, and record Applied only after confirmed\nsubmission or explicit employer confirmation of a previous application.'
new='Process only the job IDs Dave explicitly requests. Dave has authorized automatic\nsubmission of complete, verified applications unless he requests review first.\nFor batches, follow the continue-while-away instructions in the answer bank:\npreserve any job needing human attention as pending and immediately process the\nnext approved ID. Collect pending fields and actions into one list for Dave to\nresolve when he returns. Never guess required answers or bypass human challenges.\nUse each job\'s matching tailored resume, verify employer receipt, and update only\nits Applied cell with readback. Keep completed and pending jobs separate to prevent\nduplicate submissions when resuming. No unrelated tracker changes or messages.'
assert old in s;s=s.replace(old,new);p.write_text(s)
assert 'immediately process the' in p.read_text()
print('OpenClaw agent instructions updated and verified.')
