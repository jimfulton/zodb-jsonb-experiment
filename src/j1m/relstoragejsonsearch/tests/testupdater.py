import mock
import traceback
from zope.testing.loggingsupport import InstalledHandler
from zope.testing.wait import wait

from . import pgbase

class Tests(pgbase.PGTestBase):

    def test_basic(self):
        with mock.patch("j1m.relstoragejsonsearch.updater.logger") as logger:
            logger.exception.side_effect = pr
            logger.warning.side_effect = pr
            self.store(1, 1, a=1)
            self.store(1, 2, a=2)
            self.store(2, 1, a=1, b=1)
            self.store(2, 2, a=2, b=2)
            self.start_updater()
            wait((lambda : self.last_tid(2)), 9, message=2)
            self.store(3, 2, a=3, b=3)
            wait((lambda : self.last_tid(3)), 9, message=3)
            self.store(4, 2, a=4, b=4)
            wait((lambda : self.last_tid(3)), 9, message=4)
            self.stop_updater()
            self.store(5, 3, n=3)
            self.start_updater()
            wait((lambda : self.last_tid(5)), 9, 5)

            # Make sure data were stored correctly:
            self.assertEqual(self.search("""state @> '{"b": 1}'::jsonb"""),
                             [(1,)])
            self.assertEqual(self.search("""state @> '{"b": 4}'::jsonb"""),
                             [(2,)])
            self.assertEqual(self.search("""state @> '{"n": 3}'::jsonb"""),
                             [(3,)])


    def test_warn_when_no_trigger(self):
        handler = InstalledHandler(__name__.rsplit('.', 2)[0] + '.updater')
        self.start_updater()
        self.store(1, 1, a=1)
        wait((lambda : self.last_tid(1)), 9, message=1)
        self.store(2, 1, a=2)
        wait((lambda : self.last_tid(2)), 9, message=2)
        self.drop_trigger()
        self.store(3, 2, a=3)
        wait((lambda : self.last_tid(3)), 9, message=3)
        self.assertEqual([(r.msg, r.args) for r in handler.records[2:]],
                         [('Missed change %s', (3L,))])
        handler.uninstall()

    def test_catch_up_limit_extra(self):
        handler = InstalledHandler(__name__.rsplit('.', 2)[0] + '.updater')
        self.drop_trigger()
        t=0
        for o in range(800):
            if o % 70 == 0:
                t += 1
            self.store(t, o, a=o, t=t)

        self.start_updater()
        wait((lambda : self.last_tid(5)), 9, message=1)
        self.assertEqual([(r.msg, r.args) for r in handler.records[2:3]],
                         [('Catch up halting after %s updates, tid %s',
                           (350, '5'))])
        wait((lambda : self.last_tid(12)), 9)
        self.assertEqual([(r.msg, r.args) for r in handler.records[3:4]],
                         [('Catch up halting after %s updates, tid %s',
                           (350, '10'))])
        handler.uninstall()

    def test_catch_up_limit_exact(self):
        handler = InstalledHandler(__name__.rsplit('.', 2)[0] + '.updater')
        self.drop_trigger()
        t=0
        for o in range(400):
            if o % 100 == 0:
                t += 1
            self.store(t, o, a=o, t=t)
        self.start_updater()
        wait((lambda : self.last_tid(4)), 9, message=1)
        self.assertEqual([(r.msg, r.args) for r in handler.records[2:3]],
                         [('Catch up halting after %s updates, tid %s',
                           (300, '3'))])
        wait((lambda : self.last_tid(4)), 9, message=2)
        handler.uninstall()

    def test_skip_Uninteresting(self):
        import BTrees.OOBTree
        import ZODB.blob
        self.start_updater()
        self.store_ob(1, 1, BTrees.OOBTree.BTree())
        self.store_ob(2, 2, ZODB.blob.Blob())
        self.wait_tid(2)
        self.ex("select zoid from object_json")
        self.assertEqual(list(self.cursor), [])
        self.store_ob(3, 1, BTrees.OOBTree.BTree())
        self.store_ob(4, 2, ZODB.blob.Blob())
        self.store(5, 3, n=1)
        self.wait_tid(5)
        self.ex("select zoid from object_json")
        self.assertEqual(list(self.cursor), [(3L,)])

def pr(fmt, *args):
    print(fmt % args)
    traceback.print_exc()
