======================
ZODB jsonb experiment
======================

.. contents::

Introduction
============

`RelStorage <http://relstorage.readthedocs.io/en/latest/>`_ provides a
relational-database backed storage for `ZODB <http://www.zodb.org>`_.
It's especially useful when there is either a requirement to or
exsisting infrastructure for storing data in an `RDBMS
<https://en.wikipedia.org/wiki/Relational_database_management_system>`_.

RelStorage stores data in `Python pickle format
<file:///Users/jim/s/python/python-3.5.2-docs-html/library/pickle.html#module-pickle>`_,
making it impractical to use or even view in the RDBMS.

As is typical in ZODB applications, indexing is provided via BTrees
stored in the RDBMS or using an internal indexing facility.  The
search capabilities of the RDBMS aren't leveraged directly.

Postgres 9.2 introduced a JSON data type and `Postgres 9.4 introduced
a more efficient JSON data type, jsonb
<https://www.postgresql.org/docs/9.6/static/datatype-json.html>`_.
JSON is similar in many ways to pickles, and pickle data can be
represented as JSON. Like pickle, JSON is dynamic in nature, providing
much more flexability than traditional RDBMS tables.  If ZODB data
were stored in JSON format, then they could be viewed and, more
importantly, searched in Postgres directly.

JSON can't replace pickle for data storage, because its type system is
less expressive than Python's.  Conversion from pickle to JSON is
lossy from a type perspective. It could be made less lossy through the
addition of additional JSON data, but doing so would likely render the
JSON too difficult to leverage.

Proof of concept
================

A proof-of-concept experiment was carried out to exlore the utility of
storing data as JSON to make it more available in Postgres, while
still supporting use in ZODB.

Because, as noted in the previous section, conversion from pickle to
JSON is lossy, the JSON data augments rather than replaces the pickle data.

Database schema
---------------

For this short experiment, Pickle data in a RelStorage table were
converted to JSON and loaded into a separate table.  Indexes were
added to the tabel to support search. Here's a description of the
table and the indexes created::

         Table "public.object_json"
   Column |       Type        | Modifiers
  --------+-------------------+-----------
   zoid   | bigint            |
   cls    | character varying |
   state  | jsonb             |
  Indexes:
      "object_json_cls_idx" btree (cls)
      "object_json_content_text_idx" gin (content_text(cls, state))
      "object_json_docid_idx" hash (((state #>> '{docid}'::text[])::integer))
      "object_json_hex_zoid_idx" hash (lpad(to_hex(zoid), 16, '0'::text))
      "object_json_json_idx" gin (state)
      "object_json_zoid_idx" hash (zoid)

ZODB data records contain two pickles, a class pickle and a state
pickle. The class pickle contains the class name and any arguments
(rarely used) needed to construct uninitialized instances if the
class. To keep things simpler it was decided to store these as 2
separate columns, ``cls`` and ``state``. The ``cls`` column only
stores the class name.

The ``zoid`` column contains the ZODB object id represented as an
integer.  This is the representation used by RelStorage.

JSON conversion
---------------

Data were converted to JSON using the new `xpickle
<https://github.com/jimfulton/xpickle>`_, which was created as part of
this experiment [#xmlpicklef]_. Data were converted from a pickle
serialization to a JSON serialization.

Some things to note about the conversion:

- JSON has no notion of class instances.  When storing instances, an
  extra JSON property, ``::`` was added to hold the class name.

  Other accomidations were made for less frequent situations where
  pickled classes has initialization arguments or non-dictionary
  state. See the `xpickle source
  <https://github.com/jimfulton/xpickle/blob/master/src/j1m/xpickle/jsonpickle.py>`_
  for details.

- Pickle supports cyclic data structures.  When data participates in a
  cycle, an in-pickle id is generated and assigned to the object's
  serialization. When the object is referenced (after the first
  reference) a reference object is used::

    {"::": "ref", "id": "13"}

  Note in this example that the class is ``ref``.  Normally, classes
  have a module path and a class name.  For classes specific to the
  serialization, we omit a module path, as we did here.

- Pickle supports references between persistent objects (accross
  database records.  These were represented in JSON as
  persistent-reference objects::

    {"::": "persistent",
     "id": ["0000000000000001",
            "persistent.mapping.PersistentMapping"]}

  The persistent reference has a single data field, which is the id.
  ZODB persistent ids consist of an object id and a class identifier.
  The class identifier allows ZODB to construct ghost [#ghost]_
  instances without having to load a database record.

In many cases, we chose to be lossy if favor of making the JSON data
easier to use in Postgres.

There were some cases where application-specific adjustments wre
necessary. For example, some objects stored text documents as blobs
and cached the text data from these documents in special cache
objects.  The data in these objects was compressed using zlib and
needed to be uncompresssed before storing in the database.  Here's the
conversion script that was used::

  import binascii
  import json
  import zlib
  from j1m.xpickle.jsonpickle import record

  outp = open('data.json', 'w')
  i = 0
  for line in open('data.pickles'):
      zoid, p = line.strip().split('\t')
      p = binascii.a2b_hex(p[3:])
      c, j = record(p)
      c = json.loads(c)['name']
      if c == 'karl.content.models.adapters._CachedData':
          state = json.loads(j)
          text = zlib.decompress(state['data']['hex'].decode('hex'))
          try:
              text = text.decode(
                  state.get('encoding', 'ascii')).replace('\x00', '')
          except UnicodeDecodeError:
              text = ''
          j = json.dumps(dict(text=text))

      j = j.replace('\\', '\\\\') # postgres issue
      outp.write('\t'.join((zoid, c, j)) + '\n')
      i += 1

  outp.close()

For the most part, this is mostly a simple script that converted data
in pickle format to JSON format. The special handling is in the block
that start on line 13.

Indexes
-------

In Postgres, indexes can be defined against expressions, which allows
indexing against data that isn't stored. This provides a lot of
flexibility, which was leveraged here.  Let's look at some interesting
examples.

Text indexing
_____________

In this application, text extraction was type-specific.  Most objects
has text in ``text``, ``title``, and ``description`` columns.  For
``Profile`` objects, text came from a variety of small fields.  For
``CommunityFile`` objects, text had to be loaded from separate
``_CachedData`` objects. A `PL/pgSQL
<https://www.postgresql.org/docs/9.6/static/plpgsql.html>`_ function
performed the text extraction::

  create or replace function content_text(class_name varchar, state jsonb)
    returns tsvector as $$
  declare
    title varchar;
    description varchar;
    text varchar;
    textv tsvector;
    hoid varchar;
    r object_json%ROWTYPE;
  begin
    if class_name = 'karl.models.profile.Profile' then
      text :=
        coalesce(state #>> '{"__name__"}', '')
        || ' ' || coalesce(state #>> '{"firstname"}', '')
        || ' ' || coalesce(state #>> '{"lastname"}', '')
        || ' ' || coalesce(state #>> '{"email"}', '')
        || ' ' || coalesce(state #>> '{"phone"}', '')
        || ' ' || coalesce(state #>> '{"extension"}', '')
        || ' ' || coalesce(state #>> '{"department"}', '')
        || ' ' || coalesce(state #>> '{"position"}', '')
        || ' ' || coalesce(state #>> '{"organization"}', '')
        || ' ' || coalesce(state #>> '{"location"}', '')
        || ' ' || coalesce(state #>> '{"country"}', '')
        || ' ' || coalesce(state #>> '{"website"}', '')
        || ' ' || coalesce(state #>> '{"languages"}', '')
        || ' ' || coalesce(state #>> '{"office"}', '')
        || ' ' || coalesce(state #>> '{"room_no"}', '')
        || ' ' || coalesce(state #>> '{"biography"}', '');
    elseif class_name = 'karl.content.interfaces.ICommunityFile' then
      hoid := state #>> '{"_extracted_data", "id", 1}';
      if hoid is not null then
        select cls, state
        from object_json where lpad(to_hex(zoid), 16, '0'::text) = hoid
        into class_name, state;
        if class_name != 'karl.content.models.adapters._CachedData' then
          raise 'bad data in CommunityFile % %', hoid, class_name;
        end if;
        return content_text(class_name, state);
      end if;
      text := '';
    else
      text := coalesce(state #>> '{"text"}', '');
    end if;

    textv := to_tsvector(text);

    if state ? 'title' then
      textv := textv
        || setweight(to_tsvector(state #>> '{"title"}'), 'A')
        || setweight(to_tsvector(coalesce(state #>> '{"description"}', '')), 'B');
    else
      textv := textv
        || setweight(to_tsvector(coalesce(state #>> '{"description"}', '')), 'A');
    end if;

    return textv;
  end
  $$ language plpgsql immutable;

Note that to access data, `Postgres JSON path expressions
<https://www.postgresql.org/docs/9.6/static/functions-json.html>`_
were used.  In the case of ``CommunityFile`` objects, queries were
used to get the text data from ``_CachedData`` objects.

An inverted text index (``gin``) was then used to index expressions
against this function::

  create index object_json_content_text_idx on object_json
  using gin (content_text(cls, state));

To perform text search, we search against the index::

  select zoid, (state #>> '{"docid"}')::int from object_json
  where content_text(cls, state) @@ to_tsquery('some text')

Note that the function is only invoked when indexing.  At search time,
the expression effectively names the index to use.

Parent traversal
________________



.. [#xmlpicklef] This was derived from a much older `xmlpickle
   <https://github.com/zopefoundation/zope.xmlpickle>`_ project.

.. [#ghost] In ZODB, ghost objects are objects without state. When a
   ghost object is referenced, it's state is loaded and it becomes a
   non-ghost. Any persistent objects referenced in the state are
   created as ghosts, unless theor already in memory.
