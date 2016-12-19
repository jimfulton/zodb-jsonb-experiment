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
import zlib

from .jsonpickle import record

logger = logging.getLogger(__name__)

unicode_surrogates = re.compile(r'\\ud[89a-f][0-9a-f]{2,2}', flags=re.I)

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('url', help='Postgresql connection url')
parser.add_argument('-t', '--poll-timeout', type=int, default=30,
                    help='Change-poll timeout, in seconds')

updates_sql = """
select zoid, tid, state from object_state where tid > %s order by tid'
"""

insert_sql = """
insert into object_json (zoid, class_name, class_pickle, state)
values %s
on conflict (zoid)
do update set class_name   = excluded.class_name,
              class_pickle = excluded.class_pickle,
              state        = excluded.state
"""

def jsonify(item):
    zoid, p = item
    p = p[:] # Convert read buffer to bytes
    klass, class_pickle_length, state = record(p)
    klass = json.loads(klass)
    class_pickle = b'\\x' + binascii.b2a_hex(p[:class_pickle_length])
    if isinstance(klass, list):
        klass, args = klass
        if isinstance(klass, list):
            class_name = '.'.join(klass)
        else:
            class_name = klass['name']
    else:
        class_name = klass['name']

    # XXX This should be pluggable
    if class_name == 'karl.content.models.adapters._CachedData':
        state = json.loads(state)
        text = zlib.decompress(state['data']['hex'].decode('hex'))
        try:
            text = text.decode(
                state.get('encoding', 'ascii')).replace('\x00', '')
        except UnicodeDecodeError:
            text = ''
        state = json.dumps(dict(text=text))

    # Remove unicode surrogate strings, as postgres utf-8
    # will reject them.
    state = unicode_surrogates.sub(' ', state)

    return zoid, class_name, class_pickle, state

def catch_up(conn, ex, start_tid):
    tid = start_tid
    ex('begin')
    try:
        updates = conn.cursor('object_state_updates')
        updates.itersize = 100
        try:
            updates.execute(
                'select tid, zoid, state from object_state where tid > %s',
                (start_tid,))
        except Exception:
            logger.exception("Getting updates after %s", start_tid)
            ex('rollback')
            return

        while True:
            data = [d[1] for d in zip(range(updates.itersize), updates)]
            if not data:
                break
            tid = data[-1][0]

            # First, try a bulk insert.
            try:
                ex("savepoint s")
                ex(insert_sql %
                   ', '.join(
                       [updates.mogrify('(%s, %s, %s, %s)', jsonify(d[1:]))
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
                        ex(insert_sql % updates.mogrify('(%s, %s, %s, %s)',
                                                        jsonify(d[1:])))
                        ex('release savepoint s')
                    except Exception:
                        ex("rollback to savepoint s")
                        raise
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
        if select.select([conn], (), (), timeout) == ((), (), ()):
            yield None
        else:
            conn.poll()
            while conn.notifies:
                notify = conn.notifies.pop(0)
                yield notify.payload


def main(args=None):
    options = parser.parse_args(args)
    conn = psycopg2.connect(options.url)
    cursor = conn.cursor()
    ex = cursor.execute

    ex("select tid from object_json_tid")
    [[tid]] = cursor.fetchall()

    #import pdb; pdb.set_trace()

    catch_up(conn, ex, tid)
    first = True
    for payload in listener(options.url, options.poll_timeout):
        if payload == 'STOP':
            break
        new_tid = catch_up(conn, ex, tid)
        if new_tid > tid:
            tid = new_tid
            if payload is None and not first:
                # Notify timed out but there were changes.  This
                # expected the first time.
                logger.warning("Missed change %s", tid)
        first = False
