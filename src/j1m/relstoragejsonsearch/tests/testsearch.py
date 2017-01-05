import unittest
from ZODB import utils
import ZODB.config
import relstorage

from . import pgbase

config = """
%import relstorage

<zodb>
  <relstorage>
    <postgresql>
    </postgresql>
  </relstorage>
</zodb>
"""

class Tests(pgbase.PGTestBase):

    tables = pgbase.PGTestBase.tables + """
    blob_chunk commit_lock current_object object_ref object_refs_added
    pack_object pack_state pack_state_tid transaction
    object_json object_json_tid
    """.strip().split()

    def create_object_state(self):
        self.db = db = ZODB.config.databaseFromString(config)
        self.conn = db.open()

    def tearDown(self):
        self.db.close()
        super(Tests, self).tearDown()

    def store(self, index, **data):
        self.conn.root()[index] = o = pgbase.O(data)
        self.conn.transaction_manager.commit()
        return utils.u64(o._p_serial)

    def test_search_iterator(self):
        self.start_updater()
        for i in range(9):
            tid = self.store(i, i=i)
        self.wait_tid(tid)

        from ..search import search_iterator

        with search_iterator(
            self.conn,
            "select zoid, class_pickle "
            "from object_json "
            "where state->>'i' >= %s and state->>'i' <= %s "
            "order by zoid ",
            ('2', '5'),
            ) as it:
            data = [o.i for o in it]

        self.assertEqual(data, [2, 3, 4, 5])

        conn2 = self.db.open()
        with search_iterator(
            conn2,
            "select zoid, class_pickle "
            "from object_json "
            "where state->>'i' >= %s and state->>'i' <= %s "
            "order by zoid ",
            ('2', '5'),
            bufsize=3) as it:
            data = [o.i for o in it]

        self.assertEqual(data, [2, 3, 4, 5])

    def test_search(self):
        self.start_updater()
        for i in range(9):
            tid = self.store(i, i=i)
        self.wait_tid(tid)

        from ..search import search
        data = [
            o.i for o in search(
                self.conn,
                "select zoid, class_pickle "
                "from object_json "
                "where state->>'i' >= %s and state->>'i' <= %s "
                "order by zoid ", '2', '5')
            ]

        self.assertEqual(data, [2, 3, 4, 5])

        conn2 = self.db.open()
        data = [
            o.i for o in search(
                conn2,
                "select zoid, class_pickle "
                "from object_json "
                "where state->>'i' >= %s and state->>'i' <= %s "
                "order by zoid ", '2', '5')
            ]

        self.assertEqual(data, [2, 3, 4, 5])
