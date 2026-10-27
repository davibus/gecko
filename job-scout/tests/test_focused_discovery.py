import threading
import unittest
from focused_discovery import run_round, reconcile_pending


class FocusedDiscoveryTests(unittest.TestCase):
    def execute(self, items, review, publish=None, start=17, target=20, **extra):
        ids=list(range(start));events=[];writes=[];owner=threading.get_ident()
        def writer(candidate, result):
            self.assertEqual(threading.get_ident(),owner)
            writes.append(candidate)
            if publish:return publish(candidate,result)
            ids.append(start+len(writes));return {'verified':True}
        run_round(items,target=target,confirmed=lambda:ids,identity=lambda e:str(e).lower(),
                  known=lambda e:str(e).lower()=='known',review=review,publish=writer,
                  checkpoint=lambda *args:events.append(args),**extra)
        return ids,events,writes

    def test_duplicates_precede_any_retrieval_validation_or_review(self):
        calls=[]
        ids,events,writes=self.execute(['known','A','a','B'],lambda e:calls.append(e) or {'accepted':True})
        self.assertCountEqual(calls,['A','B'])
        self.assertEqual(len(ids),19)

    def test_three_independent_reviews_serial_publication_and_exact_target(self):
        barrier=threading.Barrier(3);active=0;maximum=0;lock=threading.Lock();calls=[]
        def review(item):
            nonlocal active,maximum
            with lock:active+=1;maximum=max(maximum,active);calls.append(item)
            barrier.wait(timeout=3)
            with lock:active-=1
            return {'accepted':True}
        ids,events,writes=self.execute(list(range(10)),review)
        self.assertEqual(maximum,3)
        self.assertEqual(len(calls),3)
        self.assertEqual(len(writes),3)
        self.assertEqual(len(ids),20)

    def test_target_already_met_starts_no_work(self):
        self.execute([1],lambda e:self.fail('Unnecessary request'),start=20)

    def test_single_remaining_slot_does_not_start_extra_paid_requests(self):
        calls=[]
        ids,events,writes=self.execute(range(10),lambda e:calls.append(e) or {'accepted':True},start=19)
        self.assertEqual(calls,[0]);self.assertEqual(len(ids),20)

    def test_rejections_refill_and_errors_preserve_pending_work(self):
        def review(item):
            if item==0:raise ValueError('provider unavailable')
            return {'accepted':item>1}
        ids,events,writes=self.execute(range(5),review,start=19)
        self.assertEqual(len(ids),20)
        self.assertTrue(any(stage=='pending' for _,stage,_ in events))

    def test_unverified_publication_is_not_counted(self):
        with self.assertRaisesRegex(RuntimeError,'readback unconfirmed'):
            self.execute([1],lambda e:{'accepted':True},publish=lambda e,r:{'verified':False})

    def test_cooperative_stop_preserves_completed_review_without_publication(self):
        stopped=threading.Event()
        def review(item):stopped.set();return {'accepted':True}
        ids,events,writes=self.execute([1,2,3],review,start=19,stopped=stopped.is_set)
        self.assertEqual(len(ids),19);self.assertFalse(writes)
        self.assertTrue(any(stage=='reviewed' for _,stage,_ in events))

    def test_invalid_concurrency_rejected(self):
        with self.assertRaises(ValueError):self.execute([],lambda e:{},max_workers=4)

    def test_pending_success_is_reconciled_before_sizing_new_work(self):
        ids=list(range(17));calls=[]
        reconcile_pending([{'id':17},{'id':17},{'id':99}],confirmed=lambda:ids,
                          verify=lambda p:{'verified':p['id']==17},
                          record=lambda p,r:ids.append(p['id']))
        self.assertEqual(len(ids),18)
        def publish(item,result):ids.append(100+item);return {'verified':True}
        run_round(range(10),target=20,confirmed=lambda:ids,identity=str,known=lambda e:False,
                  review=lambda e:calls.append(e) or {'accepted':True},publish=publish,
                  checkpoint=lambda *args:None)
        self.assertEqual(len(calls),2);self.assertEqual(len(ids),20)

    def test_supported_url_alias_is_deduplicated_before_review(self):
        from normalize import posting_identity
        urls=['https://boards.greenhouse.io/acme/jobs/123?utm_source=a',
              'https://job-boards.greenhouse.io/acme/jobs/123']
        calls=[]
        run_round(urls,target=20,confirmed=lambda:[],identity=posting_identity,known=lambda e:False,
                  review=lambda e:calls.append(e) or {'accepted':False},publish=lambda *args:self.fail('Unexpected write'),
                  checkpoint=lambda *args:None)
        self.assertEqual(len(calls),1)
