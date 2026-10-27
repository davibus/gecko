import gzip
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'job-scout'),str(Path(__file__).resolve().parent)]
import retained_artifacts as r
from archive_retained_artifacts import archive_file
from check_git_artifacts import disallowed
import check_git_artifacts as guard


class RetainedArtifactTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.source=self.root/'reports/source-test.json'
        self.source.parent.mkdir();self.source.write_bytes(b'[{"source":"test","metadata":{"credit":"preserve"}}]\r\n')
        self.archive=self.root/'external';self.archive.mkdir()
        for target,value in [('ROOT',self.root),('MANIFEST',self.root/'manifest.json')]:
            p=patch.object(r,target,value);p.start();self.addCleanup(p.stop)
        p=patch.dict('os.environ',{'GECKO_ARCHIVE_ROOT':str(self.archive)});p.start();self.addCleanup(p.stop)
        self.item=archive_file(self.source,self.archive/'objects',archive_root=self.archive,purpose='test evidence')
        r.MANIFEST.write_text(json.dumps({'artifacts':{'reports/source-test.json':self.item}}))

    def test_exact_restoration_and_json_without_original(self):
        data=self.source.read_bytes();self.source.unlink()
        self.assertTrue(r.available(self.source))
        with r.artifact_path(self.source) as path:self.assertEqual(path.read_bytes(),data)
        self.assertEqual(r.read_json(self.source)[0]['metadata']['credit'],'preserve')

    def test_missing_or_corrupt_archive_fails_closed_without_fresh_retrieval(self):
        self.source.unlink();archive=r.archive_path(self.item)
        archive.write_bytes(b'corrupt')
        with self.assertRaisesRegex(RuntimeError,'checksum'):r.read_json(self.source)
        archive.unlink()
        self.assertTrue(r.available(self.source))
        with self.assertRaises(FileNotFoundError):r.read_json(self.source)

    def test_existing_destination_is_never_overwritten(self):
        path=self.root/'keep.sqlite3';path.write_bytes(b'keep')
        with self.assertRaises(FileExistsError):r.restore(self.item,path)
        self.assertEqual(path.read_bytes(),b'keep')

    def test_archive_root_escape_is_blocked(self):
        with self.assertRaises(ValueError):r.archive_path({'archive':'../outside.gz'})

    def test_runtime_git_guard(self):
        for path in ['job-scout/data/jobs.sqlite3','job-scout/data/firecrawl_discovery.sqlite-wal',
                     'reports/discovery/run/source-test.json','reports/discovery/run/additional-source-rows.json']:
            self.assertTrue(disallowed(path),path)
        self.assertFalse(disallowed('job-scout/preferences/retained-artifacts.json'))
        self.assertFalse(disallowed('scripts/normal.py'))

    def test_staged_blob_limit_checks_exact_boundary_in_one_batch(self):
        entry=b'100644 '+b'a'*40+b' 0\tscripts/example.txt\0'
        with patch.object(guard.subprocess,'check_output',side_effect=[entry,str(guard.LIMIT)+'\n']):
            self.assertEqual(guard.check_staged(),[])
        with patch.object(guard.subprocess,'check_output',side_effect=[entry,str(guard.LIMIT+1)+'\n']):
            self.assertIn('100 MiB',guard.check_staged()[0])

    def test_cleanup_cli_refuses_live_database_paths(self):
        import archive_retained_artifacts as archive
        import database_maintenance as maintenance
        plan=self.archive/'plan.json'
        plan.write_text(json.dumps([{'path':'job-scout/data/jobs.sqlite3','sha256':'unused','purpose':'invalid'}]))
        with patch.object(archive,'ROOT',self.root),patch.object(maintenance,'BACKUPS',self.archive):
            with self.assertRaisesRegex(ValueError,'historical report'):archive.execute(plan,delete=True)


if __name__=='__main__':unittest.main()
