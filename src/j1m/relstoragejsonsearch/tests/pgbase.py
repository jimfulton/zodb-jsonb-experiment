import persistent
import psycopg2
import threading
import unittest
import ZODB.serialize
from zope.testing.wait import wait

from .. import updater

class O(persistent.Persistent):

    def __init__(self, kw):
        self.__dict__.update(kw)

class PGTestBase(unittest.TestCase):

    tables = 'object_state object_json object_json_tid'.split()

    def setUp(self):
        conn = self.conn = psycopg2.connect('')
        conn.autocommit = True
        cursor = self.cursor = conn.cursor()
        ex = self.ex = cursor.execute
        self.cleanup()
        self.create_object_state()

    def create_object_state(self):
        self.ex("create table if not exists object_state"
                " (zoid bigint primary key, tid bigint, state bytea)")

    def cleanup(self):
        for name in self.tables:
            self.ex("drop table if exists " + name + " cascade")
        self.ex("drop sequence if exists zoid_seq cascade")
        self.ex("drop function if exists notify_object_state_changed() cascade")

    def tearDown(self):
        self.cleanup()
        self.stop_updater()
        self.conn.close()

    def store_ob(self, tid, oid, ob):
        writer = ZODB.serialize.ObjectWriter()
        p = updater.bytea_hex(writer.serialize(ob))
        self.ex("insert into object_state values(%s, %s, %s)"
                " on conflict (zoid)"
                " do update set tid=excluded.tid, state=excluded.state",
                (oid, tid, p))

    def store(self, tid, oid, **data):
        self.store_ob(tid, oid, O(data))

    thread = None
    def start_updater(self):
        thread = threading.Thread(
            target=updater.main, args=(['', '-t1', '-m200'],))
        thread.daemon = True
        thread.start()
        self.thread = thread

    def stop_updater(self):
        if self.thread is not None:
            self.ex("notify object_state_changed, 'STOP'")
            self.thread.join(99999)

    def setup_object_json(self):
        updater.setup_object_json(self.cursor)

    def drop_trigger(self):
        self.ex("drop trigger trigger_notify_object_state_changed"
                " on object_state")

    def last_tid(self, expect=None):
        try:
            self.ex("select tid from object_json_tid")
        except Exception as err:
            if 'object_json_tid' not in str(err):
                raise
            tid = 0
        else:
            [[tid]] = self.cursor.fetchall()

        if expect is not None:
            return expect == tid
        else:
            return tid

    def wait_tid(self, tid):
        wait((lambda : self.last_tid(tid)), 9, message="waiting for %s" % tid)


    def search(self, where):
        self.ex("select zoid from object_json where %s" % where)
        return list(self.cursor.fetchall())
