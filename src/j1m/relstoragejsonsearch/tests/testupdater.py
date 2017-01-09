import json
import mock
import traceback
from zope.testing.loggingsupport import InstalledHandler

from . import pgbase

class Tests(pgbase.PGTestBase):

    def test_non_empty_generator(self):
        from ..updater import non_empty_generator
        self.assertEqual(non_empty_generator(iter(())), None)
        self.assertEqual(list(non_empty_generator(iter((1, 2, 3)))), [1, 2, 3])

    def test_update_iterator(self):
        t = 0
        for i in range(99):
            if i%7 == 0:
                t += 1
            self.store(t, i)
        from ..updater import Updates
        import psycopg2
        conn = psycopg2.connect(self.conn.dsn)
        self.assertEqual(
            [[int(r[1]) for r in b]
             for b in Updates(conn, end_tid=99, limit=20)
             ],
            [list(range(0, 21)),
             list(range(21, 42)),
             list(range(42, 63)),
             list(range(63, 84)),
             list(range(84, 99)),
             ])

    def test_basic(self):
        with mock.patch("j1m.relstoragejsonsearch.updater.logger") as logger:
            logger.exception.side_effect = pr
            logger.warning.side_effect = pr
            self.store(1, 1, a=1)
            self.store(1, 2, a=2)
            self.store(2, 1, a=1, b=1)
            self.store(2, 2, a=2, b=2)
            self.start_updater()
            self.wait_tid(2)
            self.store(3, 2, a=3, b=3)
            self.wait_tid(3)
            self.store(4, 2, a=4, b=4)
            self.wait_tid(4)
            self.stop_updater()
            self.store(5, 3, n=3)
            self.start_updater()
            self.wait_tid(5)

            # Make sure data were stored correctly:
            self.assertEqual(self.search("""state @> '{"b":
            1}'::jsonb"""), [(1,)])
            self.assertEqual(self.search("""state @> '{"b":
            4}'::jsonb"""), [(2,)])
            self.assertEqual(self.search("""state @> '{"n":
            3}'::jsonb"""), [(3,)])

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

    def test_custom_transformations(self):
        # We can supply a trandformation function that transforms data
        # after it has been converted to json.
        self.start_updater(
            '-xj1m.relstoragejsonsearch.tests.testupdater:custom')
        self.store(1, 1, a=1)
        self.wait_tid(1)
        self.ex("select state from object_json")
        [[state]] = self.cursor
        self.assertEqual(
            state,
            {u'A': 1,
             u'class_name': u'j1m.relstoragejsonsearch.tests.pgbase.O',
             u'zoid': 1})

    def test_redo(self):
        # If you change a transformation, you'll want to redo the
        # updates you made before.  If you use the redo option, then
        # instead of updating data writen after the tid stored in
        # object_json_tid, the updater will update the data stored
        # before, and then stop.
        self.start_updater()
        self.store(1, 1, a=1)
        self.store(2, 2, a=2)
        self.wait_tid(2)
        self.stop_updater()
        self.ex("update object_json_tid set tid=1")
        from ..updater import main
        main(['', '-xj1m.relstoragejsonsearch.tests.testupdater:custom',
              '--redo'])
        self.ex("select state from object_json order by zoid")
        self.assertEqual(
            list(self.cursor),
            [({u'A': 1,
               u'class_name': u'j1m.relstoragejsonsearch.tests.pgbase.O',
               u'zoid': 1},),
             ({u'a': 2},)])

def custom(zoid, class_name, state):
    state = json.loads(state)
    state = {
        k.upper(): v
        for k, v in state.items()
        }
    state['class_name'] = class_name
    state['zoid'] = zoid
    return state

def pr(fmt, *args):
    print(fmt % args)
    traceback.print_exc()
