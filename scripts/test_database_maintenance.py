import json
from contextlib import closing
import io
from datetime import datetime, timedelta
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'job-scout'))
import database_maintenance as m


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name)/'backups'; self.db=Path(self.tmp.name)/'live.sqlite3'
        with closing(sqlite3.connect(self.db)) as con, con:
            con.executescript('CREATE TABLE jobs(id INTEGER PRIMARY KEY, description TEXT); INSERT INTO jobs VALUES(1,"keep");'
                              'CREATE TABLE workspace_events(id INTEGER PRIMARY KEY, at TEXT,dataset TEXT,slot INTEGER,action TEXT,before_json TEXT,after_json TEXT);')
        self.now=datetime(2026,10,1,8,tzinfo=ZoneInfo('America/Denver'))

    def backup(self, **kwargs):
        return m.backup_database(self.db,folder=self.folder,now=kwargs.pop('now',self.now),**kwargs)

    def test_restore_dedup_and_daily_changed_only(self):
        original=m.sha256(self.db)
        self.assertTrue(self.backup()['restore_test'])
        self.assertEqual(m.sha256(self.db),original)
        self.assertEqual(self.backup()['status'],'already-backed-up-today')
        self.assertEqual(self.backup(now=self.now+timedelta(days=1))['status'],'unchanged')
        with closing(sqlite3.connect(self.db)) as con, con:con.execute('UPDATE jobs SET description="changed"')
        self.assertEqual(self.backup(now=self.now+timedelta(days=1))['status'],'verified')
        self.assertEqual(len(m.load_catalog(self.folder)),2)

    def test_failed_compression_or_restoration_never_rotates_good_backup(self):
        self.backup(); catalog=(self.folder/'catalog.json').read_bytes()
        with patch.object(m.gzip,'open',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.backup(force=True)
        self.assertEqual((self.folder/'catalog.json').read_bytes(),catalog)
        for point in m.load_catalog(self.folder):self.assertTrue(m.verify_point(self.folder,point))
        with patch.object(m,'verify_point',side_effect=RuntimeError('bad restore')):
            with self.assertRaises(RuntimeError):self.backup(force=True)
        self.assertEqual((self.folder/'catalog.json').read_bytes(),catalog)

    def test_retention_seven_days_four_weeks_union(self):
        points=[]
        for i in range(45):
            day=self.now+timedelta(days=i)
            points.append(dict(file=str(i),at=day.isoformat(),day=day.date().isoformat(),week=day.strftime('%G-W%V'),kind='daily'))
        selected=m.select_retained(points)
        self.assertTrue(set(str(i) for i in range(38,45)) <= {p['file'] for p in selected})
        self.assertEqual(len({p['week'] for p in selected}),4)
        self.assertLessEqual(len(selected),11)

    def test_lock_blocks_overlapping_worker(self):
        with m.backup_lock(self.folder):
            with self.assertRaisesRegex(RuntimeError,'worker'):self.backup()

    def test_schema_migration_stops_before_ddl_when_recovery_fails(self):
        from storage import JobStore
        before=m.sha256(self.db)
        with patch.object(m,'backup_database',side_effect=RuntimeError('recovery unavailable')) as backup:
            with self.assertRaisesRegex(RuntimeError,'recovery unavailable'):JobStore(self.db)
        self.assertTrue(backup.call_args.kwargs['force'])
        self.assertEqual(m.sha256(self.db),before)

    def test_actual_rotation_and_corrupt_retained_point_preserve_files(self):
        for i in range(12):
            with closing(sqlite3.connect(self.db)) as con,con:
                con.execute('UPDATE jobs SET description=?',(str(i),))
            self.backup(now=self.now+timedelta(days=i*3))
        points=m.load_catalog(self.folder)
        self.assertLessEqual(len(points),11)
        self.assertEqual(len(list(self.folder.glob('*.sqlite3.gz'))),len(points))
        protected={p['file'] for p in points}
        with (self.folder/points[-1]['file']).open('ab') as out:out.write(b'corrupt')
        with self.assertRaisesRegex(RuntimeError,'checksum'):m.rotate(self.folder,points)
        self.assertTrue(all((self.folder/name).exists() for name in protected))

    def test_archive_verified_before_prune_and_protected_records_survive(self):
        from maintain_database import archive_history
        self.folder.mkdir()
        with closing(sqlite3.connect(self.db)) as con,con:
            con.execute("INSERT INTO workspace_events VALUES(1,'now','Job List',1,'update',NULL,'private old row')")
            con.execute("INSERT INTO workspace_events VALUES(2,'now','Job List',1,'resume-completion',NULL,'keep evidence')")
        original_open=m.gzip.open
        def corrupt_read(path,mode,*args,**kwargs):
            return io.BytesIO(b'[]\n') if mode=='rb' else original_open(path,mode,*args,**kwargs)
        with patch.object(m.gzip,'open',side_effect=corrupt_read):
            with self.assertRaisesRegex(RuntimeError,'verification'):archive_history(self.db,self.folder)
        with closing(sqlite3.connect(self.db)) as con:
            self.assertEqual(con.execute('SELECT count(*) FROM workspace_events').fetchone()[0],2)
        # The failed archive is preserved; use a separate output directory to retry.
        good=self.folder/'verified';good.mkdir()
        receipt=archive_history(self.db,good)
        self.assertEqual(receipt['rows'],1)
        with closing(sqlite3.connect(self.db)) as con:
            self.assertEqual(con.execute('SELECT action,after_json FROM workspace_events').fetchall(),[('resume-completion','keep evidence')])
            self.assertEqual(con.execute('SELECT description FROM jobs').fetchone()[0],'keep')

    def test_history_is_bounded_metadata_and_transactional(self):
        with closing(sqlite3.connect(self.db)) as con, con:
            for i in range(m.LOG_LIMIT+20):
                m.log_event(con,'now','Other',1,'update',before={'description':'old secret'},after={'description':'new secret'})
            self.assertEqual(con.execute('SELECT count(*) FROM workspace_events').fetchone()[0],m.LOG_LIMIT)
            self.assertNotIn('secret',str(con.execute('SELECT before_json,after_json FROM workspace_events').fetchall()))
            con.commit()
            con.execute("CREATE TRIGGER fail_log BEFORE INSERT ON workspace_events BEGIN SELECT RAISE(ABORT,'failure'); END")
            con.commit()
            with self.assertRaises(sqlite3.IntegrityError), con:
                con.execute('UPDATE jobs SET description="lost"')
                m.log_event(con,'now','Other',1,'update')
            self.assertEqual(con.execute('SELECT description FROM jobs').fetchone()[0],'keep')


if __name__=='__main__':unittest.main()
