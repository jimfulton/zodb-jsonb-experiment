"""Search API.

It's assumed that the API is used with an object stored in a
RelStorage with a Postgres back end.
"""
import contextlib
import relstorage.storage
import time
import ZODB.Connection
from ZODB.utils import p64

# Monkey patches, ook
def _ex_cursor(self, name=None):
    if self._stale_error is not None:
        raise self._stale_error

    with self._lock:
        self._before_load()
        return self._load_conn.cursor(name)

relstorage.storage.RelStorage.ex_cursor = _ex_cursor

def _ex_get(self, oid, class_pickle):
    """Return the persistent object with oid 'oid'."""
    if self.opened is None:
        raise ConnectionStateError("The database connection is closed")

    obj = self._cache.get(oid, None)
    if obj is not None:
        return obj
    obj = self._added.get(oid, None)
    if obj is not None:
        return obj
    obj = self._pre_cache.get(oid, None)
    if obj is not None:
        return obj

    # if class_pickle is None:
    #     p, _ = self._storage.load(oid)
    # else:
    #     p = class_pickle
    obj = self._reader.getGhost(class_pickle) # New code

    # Avoid infiniate loop if obj tries to load its state before
    # it is added to the cache and it's state refers to it.
    # (This will typically be the case for non-ghostifyable objects,
    # like persistent caches.)
    self._pre_cache[oid] = obj
    self._cache.new_ghost(oid, obj)
    self._pre_cache.pop(oid)
    return obj

ZODB.Connection.Connection.ex_get = _ex_get

def _result_iterator(conn, cursor, bufsize):
    get = conn.ex_get
    buf = []
    first = True
    it = iter(cursor)
    while True:
        if len(buf) < bufsize:
            fetch = []
            for r in it:
                if first:
                    indexes = {d[0]: index
                               for (index, d) in enumerate(cursor.description)}
                    zoid_index = indexes['zoid']
                    class_pickle_index = indexes['class_pickle']
                    first = False
                ob = get(p64(r[zoid_index]), r[class_pickle_index])
                buf.append(ob)
                fetch.append(ob)
                if len(fetch) >= bufsize:
                    break

            if fetch:
                conn.prefetch(fetch)

        if buf:
            yield buf.pop(0)
        else:
            break

def _try_to_close_cursor(cursor):
    try:
        cursor.close()
    except Exception:
        pass

@contextlib.contextmanager
def search_iterator(conn, query, args, bufsize=20):
    cursor = conn._storage.ex_cursor(str(time.time()))
    cursor.execute(query, args)
    try:
        yield _result_iterator(conn, cursor, bufsize)
    except Exception:
        _try_to_close_cursor(cursor)
        raise
    else:
        _try_to_close_cursor(cursor)

def search(conn, query, *args):
    cursor = conn._storage.ex_cursor()
    cursor.execute(query, args)
    try:
        first = True
        result = []
        get = conn.ex_get
        for r in cursor:
            if first:
                indexes = {d[0]: index
                           for (index, d) in enumerate(cursor.description)}
                zoid_index = indexes['zoid']
                class_pickle_index = indexes['class_pickle']
                first = False
            ob = get(p64(r[zoid_index]), r[class_pickle_index])
            result.append(ob)
        return result
    finally:
        _try_to_close_cursor(cursor)
