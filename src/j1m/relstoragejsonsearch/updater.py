"""Long-running process that updates database json representation
"""

import argparse
import binascii
import contextlib
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
    help='''State-transformation function (module:expr)

A function that is called with zoid, class_name, and state and returns
a new state.
''')


updates_sql = """
select tid, zoid, state from object_state where tid > %s order by tid
"""

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

def catch_up(conn, ex, start_tid, limit, xform):
    tid = ltid = start_tid
    ex('begin')
    try:
        updates = conn.cursor('object_state_updates')
        updates.itersize = 100
        try:
            updates.execute(updates_sql, (start_tid,))
        except Exception:
            logger.exception("Getting updates after %s", start_tid)
            ex('rollback')
            return

        n = 0
        looping = True
        while looping:
            data = [d[1] for d in zip(range(updates.itersize), updates)]
            if not data:
                break
            tid = data[-1][0]
            if tid != ltid:
                if n > limit:
                    # Need to be careful to stop on tid boundary
                    tid = ltid
                    data = [d for d in data if d[0] == ltid]
                    logger.info("Catch up halting after %s updates, tid %s",
                                n + len(data), str(ltid))
                    if data:
                        looping = False
                    else:
                        break
                else:
                    ltid = tid

            data = [j for j in (jsonify(d, xform) for d in data) if j]
            if not data:
                continue

            # First, try a bulk insert.
            try:
                ex("savepoint s")
                ex(insert_sql %
                   ', '.join(
                       [updates.mogrify('(%s, %s, %s, %s)', d[1:])
                        for d in data])
                   )
                ex('release savepoint s')
                n += len(data)
            except Exception:
                # Dang, fall back to individual insert so we can log
                # individual errors:
                ex("rollback to savepoint s")
                for d in data:
                    try:
                        ex("savepoint s")
                        ex(insert_sql % updates.mogrify('(%s, %s, %s, %s)',
                                                        d[1:]))
                        ex('release savepoint s')
                        n += 1
                    except Exception:
                        ex("rollback to savepoint s")
                        logger.exception("Failed tid=%s, zoid=%s",
                                         *d[:2])
    finally:
        try:
            updates.close()
        except Exception:
            pass

    if tid > start_tid:
        ex("update object_json_tid set tid=%s", (tid,))

    ex('commit')

    return tid

def listener(url, timeout=30):
    conn = psycopg2.connect(url)
    conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
    curs = conn.cursor()
    curs.execute("LISTEN object_state_changed")

    while 1:
        if select.select([conn], (), (), timeout) == ([], [], []):
            yield None
        else:
            conn.poll()
            while conn.notifies:
                notify = conn.notifies.pop(0)
                yield notify.payload

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

    logger.info("Starting updater")

    conn = psycopg2.connect(options.url)
    cursor = conn.cursor()
    ex = cursor.execute

    ex("select from information_schema.tables"
       " where table_schema = 'public' AND table_name = 'object_json'")
    if not list(cursor):
        setup_object_json(cursor)

    ex("select tid from object_json_tid")
    [[tid]] = cursor.fetchall()
    logger.info("Initial tid " + str(tid))


    tid = catch_up(conn, ex, tid, options.transaction_size_limit, xform)
    first = True
    for payload in listener(options.url, options.poll_timeout):
        if payload == 'STOP':
            break
        new_tid = catch_up(conn, ex, tid, options.transaction_size_limit, xform)
        if new_tid > tid:
            tid = new_tid
            if payload is None and not first:
                # Notify timed out but there were changes.  This
                # expected the first time.
                logger.warning("Missed change %s", tid)
        first = False

def default_transformation(zoid, class_name, state):
    # XXX This function will be a noop.

    if class_name == 'karl.content.models.adapters._CachedData':
        state = json.loads(state)
        text = zlib.decompress(state['data']['hex'].decode('hex'))
        try:
            text = text.decode(
                state.get('encoding', 'ascii')).replace('\x00', '')
        except UnicodeDecodeError:
            text = ''

        state = dict(text=text)

    return state
