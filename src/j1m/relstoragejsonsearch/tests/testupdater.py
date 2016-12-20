import mock
import os
import persistent
import psycopg2
import sys
import threading
import traceback
import unittest
import ZODB.serialize
from zope.testing.loggingsupport import InstalledHandler
from zope.testing.wait import wait

from .. import updater

class O(persistent.Persistent):

    def __init__(self, kw):
        self.__dict__.update(kw)

class Tests(unittest.TestCase):

    def setUp(self):
        conn = self.conn = psycopg2.connect('')
        conn.autocommit = True
        cursor = self.cursor = conn.cursor()
        ex = self.ex = cursor.execute
        self.tearDown(True)
        ex("create table object_state"
           " (zoid bigint primary key, tid bigint, state bytea)")
        with open(os.path.join(os.path.dirname(__file__),
                               '..', 'object_json.sql')) as f:
            ex(f.read())

    def tearDown(self, setup=False):
        self.ex("drop table if exists object_state cascade")
        self.ex("drop table if exists object_json cascade")
        self.ex("drop table if exists object_json_tid cascade")
        self.ex("drop function if exists notify_object_state_changed() cascade")
        if not setup:
            self.stop_updater()

    def store(self, tid, oid, **data):
        writer = ZODB.serialize.ObjectWriter()
        p = updater.bytea_hex(writer.serialize(O(data)))
        self.ex("insert into object_state values(%s, %s, %s)"
                " on conflict (zoid)"
                " do update set tid=excluded.tid, state=excluded.state",
                (oid, tid, p))

    def start_updater(self):
        thread = threading.Thread(
            target=updater.main, args=(['', '-t1', '-m200'],))
        thread.daemon = True
        thread.start()
        self.thread = thread

    def stop_updater(self):
        self.ex("notify object_state_changed, 'STOP'")
        self.thread.join(99999)

    def drop_trigger(self):
        self.ex("drop trigger trigger_notify_object_state_changed"
                " on object_state")

    def last_tid(self, expect=None):
        self.ex("select tid from object_json_tid")
        [[tid]] = self.cursor.fetchall()
        if expect is not None:
            return expect == tid
        else:
            return tid

    def search(self, where):
        self.ex("select zoid from object_json where %s" % where)
        return list(self.cursor.fetchall())

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
        self.assertEqual([(r.msg, r.args) for r in handler.records],
                         [('Missed change %s', (3L,))])
        handler.uninstall()

    def test_catch_up_limit_extra(self):
        handler = InstalledHandler(__name__.rsplit('.', 2)[0] + '.updater')
        self.drop_trigger()
        t=0
        for o in range(400):
            if o % 70 == 0:
                t += 1
            self.store(t, o, a=o, t=t)
        self.start_updater()
        wait((lambda : self.last_tid(5)), 9, message=1)
        self.assertEqual([(r.msg, r.args) for r in handler.records[:1]],
                         [('Catch up halting after %s updates, tid %s',
                           (350, '5'))])
        wait((lambda : self.last_tid(6)), 9)
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
        self.assertEqual([(r.msg, r.args) for r in handler.records[:1]],
                         [('Catch up halting after %s updates, tid %s',
                           (300, '3'))])
        wait((lambda : self.last_tid(4)), 9, message=2)
        handler.uninstall()

def pr(fmt, *args):
    print(fmt % args)
    traceback.print_exc()
