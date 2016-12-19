import mock
import os
import persistent
import psycopg2
import sys
import threading
import traceback
import unittest
import ZODB.serialize
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
        if not setup:
            self.ex("notify object_state_changed, 'STOP'")
        self.ex("drop table if exists object_state cascade")
        self.ex("drop table if exists object_json cascade")
        self.ex("drop table if exists object_json_tid cascade")
        self.ex("drop function if exists notify_object_state_changed() cascade")
        if not setup:
            self.thread.join(99999)

    def store(self, tid, oid, **data):
        writer = ZODB.serialize.ObjectWriter()
        p = writer.serialize(O(data))
        self.ex("insert into object_state values(%s, %s, %s)"
                " on conflict (zoid)"
                " do update set tid=excluded.tid, state=excluded.state",
                (oid, tid, p))

    def start_updater(self):
        thread = threading.Thread(target=updater.main, args=(['', '-t1'],))
        thread.daemon = True
        thread.start()
        self.thread = thread

    def last_tid(self, expect=None):
        self.ex("select tid from object_json_tid")
        [[tid]] = self.cursor.fetchall()
        if expect is not None:
            return expect == tid
        else:
            return tid

    def test_basic(self):
        with mock.patch("j1m.relstoragejsonsearch.updater.logger") as logger:
            logger.exception.side_effect = pr
            logger.warning.side_effect = pr
            self.store(1, 1, a=1)
            self.store(1, 2, a=2)
            self.store(2, 1, a=1, b=1)
            self.store(2, 2, a=2, b=2)
            self.start_updater()
            wait((lambda : self.last_tid(2)), 9, 2)
            self.store(3, 2, a=3, b=3)
            wait((lambda : self.last_tid(3)), 9, 3)
            self.store(4, 2, a=4, b=4)
            wait((lambda : self.last_tid(3)), 9, 4)


def pr(fmt, *args):
    print(fmt % args)
    traceback.print_exc()

