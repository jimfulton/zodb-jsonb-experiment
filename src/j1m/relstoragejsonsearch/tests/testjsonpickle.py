##############################################################################
#
# Copyright (c) Zope Foundation and Contributors.
# All Rights Reserved.
#
# This software is subject to the provisions of the Zope Public License,
# Version 2.0 (ZPL).  A copy of the ZPL should accompany this distribution.
# THIS SOFTWARE IS PROVIDED "AS IS" AND ANY AND ALL EXPRESS OR IMPLIED
# WARRANTIES ARE DISCLAIMED, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF TITLE, MERCHANTABILITY, AGAINST INFRINGEMENT, AND FITNESS
# FOR A PARTICULAR PURPOSE.
#
##############################################################################
from cStringIO import StringIO
import datetime
import json
from persistent.mapping import PersistentMapping
import pickle
from pprint import pprint
import unittest
import ZODB
from ZODB.utils import z64, p64, maxtid

from ..jsonpickle import JsonUnpickler

class initful(object):

    def __init__(self, *args):
        self.args = args

    def __reduce__(self):
        return self.__class__, self.args, self.__dict__

class JsonUnpicklerTests(unittest.TestCase):

    def setUp(self):
        self.db = ZODB.DB(None)
        self.conn = self.db.open()
        self.root = self.conn.root

    def tearDown(self):
        self.db.close()

    def commit(self, p=None):
        if p is None:
            self.conn.transaction_manager.commit()
            p, _, _ = self.db.storage.loadBefore(z64, maxtid)
        self.unpickler = JsonUnpickler(StringIO(p))

    def load(self):
        return json.loads(self.unpickler.load())

    def pprint(self):
        pprint(self.load())

    def check(self, expected):
        self.assertEqual(self.load(), expected)

    def test_basics(self):
        root = self.root
        root.numbers = 0, 123456789, 1 << 70, 1234.56789
        root.time = datetime.datetime(2001, 2, 3, 4, 5, 6, 7)
        root.date = datetime.datetime(2001, 2, 3)
        root.delta = datetime.timedelta(1, 2, 3)
        root.name = u'root'
        root.data = b'\xff'
        root.list = [1, 2, 3, root.name, root.numbers]
        root.list.append(root.list)
        root.first = PersistentMapping()
        self.commit()
        self.check({"::": "global",
                    "name": "persistent.mapping.PersistentMapping"})
        self.check(
            {u'data':
              {u'data': {u'::': u'hex', u'hex': u'ff'},
               u'date': u'2001-02-03T00:00:00',
               u'delta': {u'::': u'datetime.timedelta',
                          u'__class_args__': [1, 2, 3]},
               u'first': {u'::': u'persistent',
                          u'id': [1, u'persistent.mapping.PersistentMapping']},
               u'list': {u'::': u'shared',
                         u'id': u'12',
                         u'value': [1,
                                    2,
                                    3,
                                    u'root',
                                    {u'::': u'shared',
                                     u'id': u'13',
                                     u'value': [0,
                                                123456789,
                                                1180591620717411303424L,
                                                1234.56789]},
                                    {u'::': u'ref', u'id': u'12'}]},
               u'name': u'root',
               u'numbers': {u'::': u'ref', u'id': u'13'},
               u'time': u'2001-02-03T04:05:06.000007'}}
            )

    def test_non_ascii_zoid(self):
        root = self.root
        for i in range(200):
            self.conn.add(PersistentMapping())
        root.x = PersistentMapping()
        self.commit()
        _ = self.load()
        _ = self.load()

    def test_put_append(self):
        root = self.root
        self.root.x = self.root.y = [1]
        self.commit()
        _ = self.load()
        _ = self.load()

    def test_put_setitem(self):
        root = self.root
        self.root.x = self.root.y = dict(x=1)
        self.commit()
        _ = self.load()
        _ = self.load()

    def test_put_persistent_id(self):
        self.commit(
            'cBTrees.OOBTree\nOOBTree\nq\x01.((((U\x07100x100q\x02(U\x08'
            '\x00\x00\x00\x00\x00\x92s\x11q\x03ccontent.models.files\n'
            'Thumbnail\nq\x04tq\x05QU\x0550x50q\x06(U\x08\x00\x00\x00'
            '\x00\x00\x9cV_q\x07h\x04tq\x08QU\x0675x100q\t(U\x08\x00'
            '\x00\x00\x00\x00\x92s\x0eq\nh\x04tq\x0bQU\x0585x85q\x0c'
            '(U\x08\x00\x00\x00\x00\x00\x9cV]q\rh\x04tq\x0eQttttq\x0f.')

        _ = self.load()
        _ = self.load()

