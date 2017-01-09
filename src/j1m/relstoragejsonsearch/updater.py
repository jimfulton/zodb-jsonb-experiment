from __future__ import print_function
"""Updates database json representation
"""

import argparse
import binascii
import contextlib
import itertools
import json
import logging
import psycopg2
import Queue
import re
import select
from cStringIO import StringIO
import zlib

from .jsonpickle import JsonUnpickler

logger = logging.getLogger(__name__)

unicode_surrogates = re.compile(r'\\ud[89a-f][0-9a-f]{2,2}', flags=re.I)

def global_object(name):
    mod, expr = name.split(':')
    return eval(expr, __import__(mod, {}, {}, ['*']).__dict__)

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('url', help='Postgresql connection url')
parser.add_argument('-t', '--poll-timeout', type=int, default=30,
                    help='Change-poll timeout, in seconds')
parser.add_argument('-m', '--transaction-size-limit', type=int, default=100000,
                    help='Transaction size limit (aproximate)')
parser.add_argument(
    '-l', '--logging-configuration', default='info',
    help='Logging configuration file path, or a logging level name')

parser.add_argument(
    '-x', '--transformation', type=global_object,
    help='''\
State-transformation function (module:expr)

A function that is called with zoid, class_name, and state and returns
a new state.
''')

parser.add_argument(
    '--redo', action='store_true',
    help="""\
Redo updates

Rather than processing records written before the current tid (in
object_json_tid), process records writen up through the current tid
and stop.

This is used to update records after changes to data
transformations. It should be run *after* restarting the regulsr
updater.
""")

insert_sql = """
insert into object_json (zoid, class_name, class_pickle, state)
values %s
on conflict (zoid)
do update set class_name   = excluded.class_name,
              class_pickle = excluded.class_pickle,
              state        = excluded.state
"""

skip_class = re.compile('BTrees[.]|ZODB.blob').match

def bytea_hex(bytes):
    return b'\\x' + binascii.b2a_hex(bytes)

def jsonify(item, xform):
    tid, zoid, p = item
    p = p[:] # Convert read buffer to bytes


    f = StringIO(p)
    unpickler = JsonUnpickler(f)
    klass = unpickler.load()
    klass = json.loads(klass)
    if isinstance(klass, list):
        klass, args = klass
        if isinstance(klass, list):
            class_name = '.'.join(klass)
        else:
            class_name = klass['name']
    else:
        class_name = klass['name']

    if skip_class(class_name):
        return None

    class_pickle_length = f.tell()
    class_pickle = bytea_hex(p[:class_pickle_length])

    state = unpickler.load()
    xstate = xform(zoid, class_name, state)
    if xstate is not state:
        state = xstate
        if not isinstance(state, bytes):
            state = json.dumps(state)

    # Remove unicode surrogate strings, as postgres utf-8
    # will reject them.
    state = unicode_surrogates.sub(' ', state)

    return tid, zoid, class_name, class_pickle, state

def non_empty_generator(gen):
    try:
        first = next(gen)
    except StopIteration:
        return None
    def it():
        yield first
        for v in gen:
            yield v
    return it()

class Updates:

    def __init__(self, conn, start_tid=-1, end_tid=None,
                 limit=100000, poll_timeout=30, iterator_size=100):
        self.conn = conn
        self.cursor = conn.cursor()
        self.ex = self.cursor.execute
        self.tid = start_tid
        self.follow = end_tid is None
        self.end_tid = end_tid or 1<<62
        self.poll_timeout = poll_timeout
        self.limit = limit
        self.iterator_size = iterator_size

    def _batch(self):
        tid = self.tid
        self.ex('begin')
        try:
            updates = self.conn.cursor('object_state_updates')
            updates.itersize = self.iterator_size
            try:
                updates.execute("""\
                select tid, zoid, state from object_state
                where tid > %s and tid <= %s order by tid
                """, (tid, self.end_tid))
            except Exception:
                logger.exception("Getting updates after %s", tid)
                self.ex('rollback')
                raise

            n = 0
            for row in updates:
                if row[0] != tid:
                    if n >= self.limit:
                        break
                    tid = self.tid = row[0]
                yield row
                n += 1
        finally:
            try:
                updates.close()
            except Exception:
                pass

    def _listen(self):
        conn = psycopg2.connect(self.conn.dsn)
        try:
            conn.set_isolation_level(
                psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
            curs = conn.cursor()
            curs.execute("LISTEN object_state_changed")
            timeout = self.poll_timeout

            while True:
                if select.select([conn], (), (), timeout) == ([], [], []):
                    yield None
                else:
                    conn.poll()
                    if conn.notifies:
                        if any(n.payload == 'STOP' for n in conn.notifies):
                            return # for tests
                        # yield the last
                        yield conn.notifies[-1].payload
        finally:
            conn.close()

    def __iter__(self):
        # Catch up:
        while True:
            batch = non_empty_generator(self._batch())
            if batch is None:
                break # caught up
            else:
                yield batch

        if self.follow:
            for payload in self._listen():
                batch = non_empty_generator(self._batch())
                if batch is not None:
                    yield batch

def update_object_json(batch, ex, mogrify, xform):
    tid = None
    while True:
        data = list(itertools.islice(batch, 0, 100))
        if not data:
            break
        tid = data[-1][0]

        # Convert, filtering out null conversions (uninteresting classes)
        data = [j for j in (jsonify(d, xform) for d in data) if j]
        if not data: # all of the data was uninteresting
            continue # but wait, there's more

        # First, try a bulk insert, which is faster.
        try:
            ex("savepoint s")
            ex(insert_sql %
               ', '.join(
                   [updates.mogrify('(%s, %s, %s, %s)', d[1:])
                    for d in data])
               )
            ex('release savepoint s')
        except Exception:
            # Dang, fall back to individual insert so we can log
            # individual errors:
            ex("rollback to savepoint s")
            for d in data:
                try:
                    ex("savepoint s")
                    ex(insert_sql % mogrify('(%s, %s, %s, %s)', d[1:]))
                    ex('release savepoint s')
                except Exception:
                    ex("rollback to savepoint s")
                    logger.exception("Failed tid=%s, zoid=%s",
                                     *d[:2])


    if tid is not None:
        ex('update object_json_tid set tid=%s', (tid,))
    ex('commit')


logging_levels = 'DEBUG INFO WARNING ERROR CRITICAL'.split()

def setup_object_json(cursor):
    import os
    ex = cursor.execute
    with open(os.path.join(os.path.dirname(__file__), 'object_json.sql')) as f:
        ex(f.read())
        ex('commit')

def main(args=None):
    options = parser.parse_args(args)

    if options.logging_configuration.upper() in logging_levels:
        logging.basicConfig(level=options.logging_configuration.upper())
    else:
        with open(options.logging_configuration) as f:
            from ZConfig import configureLoggers
            configureLoggers(f.read())

    xform = options.transformation
    if xform is None:
        xform = default_transformation


    conn = psycopg2.connect(options.url)
    cursor = conn.cursor()
    ex = cursor.execute
    mogrify = cursor.mogrify

    ex("select from information_schema.tables"
       " where table_schema = 'public' AND table_name = 'object_json'")
    if not list(cursor):
        setup_object_json(cursor)

    ex("select tid from object_json_tid")
    [[tid]] = cursor.fetchall()

    if options.redo:
        start_tid = -1
        end_tid = tid
        logger.info("Redoing through", tid)
    else:
        logger.info("Starting updater at %s", tid)
        start_tid = tid
        end_tid = None

    for batch in Updates(conn, start_tid, end_tid,
                         limit=options.transaction_size_limit,
                         poll_timeout=options.poll_timeout,
                         ):
        update_object_json(batch, ex, mogrify, xform)

def default_transformation(zoid, class_name, state):
    return state


if __name__ == '__main__':
    main()
