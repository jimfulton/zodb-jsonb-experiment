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

Postgres 9.2 introduced a JSON data type and Postgres 9.4 introduced
a more efficient JSON data type, `jsonb
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
converted to JSON and loaded into a separate table.

Indexes were added to the tabel to support search. Here's a
description of the table and the indexes created::


           Table "public.object_json"
     Column   |       Type        | Modifiers
  ------------+-------------------+-----------
   zoid       | bigint            | not null
   class_name | character varying |
   state      | jsonb             |
  Indexes:
      "object_json_pkey" PRIMARY KEY, btree (zoid)
      "object_json_community_id_idx" btree (get_community_id(class_name, state))
      "object_json_content_text_idx" gin (content_text(class_name, state))
      "object_json_json_idx" gin (state)


ZODB data records contain two pickles, a class pickle and a state
pickle. The class pickle contains the class name and any arguments
(rarely used) needed to construct uninitialized instances of the
class. To keep things simpler it was decided to store these as 2
separate columns, ``class_name`` and ``state``. The ``class_name``
column only stores the class name.

The ``zoid`` column contains the ZODB object id represented as an
integer.  This is the representation used by RelStorage.

Aside from from the primary-key index, the indexes were application
dependent:

object_json_community_id_idx
  In this application, data are organized by "community", and most
  searches are qualified by a community id.  To get the community id
  for an object, you have to walk up a containment hierienchy until
  you find a community object.  A `PL/pgSQL
  <https://www.postgresql.org/docs/9.4/static/plpgsql.html>`_
  function, `get_community_id <get_community_id.sql>`_ was constructed
  that followed parent pointers in the json data to find community
  ids. An expression indexed used this function to make
  community-id-based searches very fast.

  The function used to create this index is fairly expensive as it may
  make multiple queries to find a community object.  The function is
  normally only used when the index is updated. During search like::

     select zoid from object_json
     where get_community_id(class_name, state) = '123456'

  The expression: ``get_community_id(class_name, state)`` isn't
  actually evaluated, but is used to select the index we created.
  This provides a lot of power when data to ve searched required
  complex computation.

object_json_content_text_idx
  This index is an inverted index supporting full-text search.  It's
  an expresssion index that indexes the text-extraction function,
  `content_text <content_text.sql>`_.  This too is a non-trivial
  computation that extracts text in an object-type specific way, and,
  in some cases, uses queries to get an object's text from a different
  database record.

object_json_json_idx
  This is a generic index that allows a varoety pf general queried
  against the JSON data.  Some example queries:

  - Find all objects that have access control information::

      state ? '__acl__'

  - Find the object with a ``docid`` field with the value ``123456``::

      state @> '{"docid": 123456}'


JSON conversion
---------------

Data were converted to JSON using the new `xpickle
<https://github.com/jimfulton/xpickle>`_, which was created as part of
this experiment [#xmlpicklef]_. Data were converted from a pickle
serialization to a JSON serialization.

A number of `changes
<https://github.com/jimfulton/xpickle/compare/wild>`_ were made in the
course of the experiment that, as of this time, weren't integrated
with the master branch, in part due to some outstanding issues.

Some things to note about the conversion:

- JSON has no notion of class instances.  When storing instances, an
  extra JSON property, ``::`` was added to hold the class name.

- Pickle supports cyclic data structures.  When data participates in a
  cycle, an in-pickle id is generated and assigned to the object's
  serialization. When the object is referenced (after the first
  reference) a reference object is used::

    {"::": "ref", "id": "13"}

  Note in this example that the class is ``ref``.  Normally, classes
  have a module path and a class name.  For classes specific to the
  serialization, we omit a module path, as we did here.

  Pickle doesn't actually detect cycles. It uses references whenever
  an object is referenced multiple times in the same pickle.

  Reference objects are very hard to deal with when using JSON data.
  They break simple JSON queries and they make data extraction
  functions a lot more complicated.

  One of the open changes made to ``xpickle`` for this analysis was to
  disable this feature. Fortunately, none of the database records used
  in this analysis had cycles.  In ZODB databases, object cycles
  typically cross persistent-object boundaries and are rare withing
  database records.

- Pickle supports references between persistent objects (accross
  database records.  These were represented in JSON as
  persistent-reference objects::

    {"::": "persistent", "id": [1, "some_module.some_class"]}

  The persistent reference has a single data field, which is the id.
  ZODB persistent ids consist of an object id and a class identifier.
  The class identifier allows ZODB to construct ghost [#ghost]_
  instances without having to load a database record.

- In this application, objects were arranged hierarchically. Content
  objects have ``__parent__`` properties that referenced their parent
  objects.  The `get_community_id <get_community_id.sql>`_ function
  used these properties to find an object's community object and it's id.

In many cases, we chose to be lossy in favor of making the JSON data
easier to use in Postgres.

The conversion process consistented of the following steps:

#. Data were exported from the RelStorage ``object_state`` table:

   ::

     \copy object_state (zoid, state) to STDOUT

   Here we used the `psql \copy command
   <https://www.postgresql.org/docs/9.4/static/app-psql.html>`_
   [#copy]_ to
   copy the object ids and pickles.

#. A `conversion script <convert.py>`_ was used to convert pickles to
   JSON.

   There were some cases where application-specific adjustments wre
   necessary. For example, some objects stored text documents as blobs
   and cached the text data from these documents in special cache
   objects.  The data in these objects was compressed using zlib and
   needed to be uncompresssed before storing in the database. See
   `convert.py <convert.py>`_.

   For the most part, this is mostly a simple script that converted data
   in pickle format to JSON format. The special handling is in the block
   that start with::

     if c == 'karl.content.models.adapters._CachedData':

#. A ``COPY`` statement was used to bulk-load the converted data::

     create table object_json (
       zoid bigint primary key,
       class_name varchar,
       state jsonb);
     copy object_json (zoid, class_name, state) from STDIN;

#. Indexes were built::

     create index object_json_community_id_idx on object_json
            using btree (get_community_id(class_name, state));
     create index object_json_content_text_idx on object_json
            using gin (content_text(class_name, state));
     create index object_json_json_idx on object_json using gin (state);

Searching
---------

To assess the efficacy of using JSON object representations for
search, we performed a basic search::

    select zoid from object_json
    where content_text(class_name, state)  @@ :text::tsquery and
          get_community_id(class_name, state) = :community_id

That searched for objects containg a text term (``:text`` above) and
with a given community id.  Remember that we had expression indexes
for the text and community id (``:community_id``).

The search performance was comparied to searching a dedicated text
and community_id table::

                         Table "public.pgtextindex"
        Column       |            Type             |      Modifiers
  -------------------+-----------------------------+----------------------
   docid             | integer                     | not null
   community_docid   | character varying(100)      |
   content_type      | character varying(30)       |
   creation_date     | timestamp without time zone |
   modification_date | timestamp without time zone |
   coefficient       | real                        | not null default 1.0
   marker            | character varying[]         |
   text_vector       | tsvector                    |
  Indexes:
      "pgtextindex_pkey" PRIMARY KEY, btree (docid)
      "pgtextindex_community_docid_index" btree (community_docid, content_type, creation_date)
      "pgtextindex_index" gin (text_vector)

Tests searches were run multiple times directly on the database
server. Absolute times aren't really important, but for comparison:

===============  ===========================
Search type      Search time in milliseconds
===============  ===========================
JSON                      3.4
Dedicated table           2.0
===============  ===========================

It's surprizing to see a difference, given that indexes are used in
both cases, still the performance seems pretty reasonable in bothe
cases.

The advantage of using JSON, despite the poorer performance is that it
isn't necessary to maintain and update a separate table. The dedicated
table used here was maintaining by application logic that sometimes
failed. The JSON search results containied data that was missing from
the dedicated table.

In addition, a security-filtered search was performed. When searching
for content in a content-management system, you often want to filter
results to those for which a request's associated principals (user and
their groups) have a needed permission.  The security filtering uses
access-control information stored at some notes in the object
hierarchy [#not-flattened]_.  This required using a recursive query to
find and evaluate the access control lists relevent to a search
result.

A `template <src/j1m/jsonbfilteredsearch/__init__.py>` was used to
generate a filtered search query from a base search query.  The
generated query [#variableified]_::

  with recursive
       search_results as (
         select * from object_json
         where content_text(class_name, state)  @@ :text::tsquery and
               get_community_id(class_name, state) = :community_id
               ),
       allowed(zoid, id, parent_id, allowed ) as (
           select zoid, zoid as id,
                  (state #>> '{"__parent__", "id", 0}')::bigint,
                  jsonb_check_access(
                    state,
                    array[:user, :group, 'system.Everyone'],
                    'edit')
           from search_results
        union all
           select allowed.zoid, object_json.zoid as id,
                  (object_json.state #>> '{"__parent__", "id", 0}')::bigint,
                  jsonb_check_access(
                    object_json.state,
                    array[:user, :group, 'system.Everyone'],
                    'edit')
           from allowed, object_json
           where allowed.allowed is null and
                 object_json.zoid = allowed.parent_id
      )
  select zoid  from allowed where allowed

Some things to note:

- A PL/pgSQL `function was used to check access at each note
  containing access-control information <check_access.sql>`_.

- JSON ``__parent__`` properties were used to traverse upward through
  the object hierarchy.

- In the code above, ``:text``, ``:community_id``, ``:user``, and
  ``:group`` are placeholders.

The filtered search was compared to a `similar filtered search
<https://github.com/jimfulton/acl-filtered-search#recursive-search-representing-acls-as-postgres-arrays>`_
that used dedicated ``parent`` and ``acl`` tables.

Again the absolute values aren't important but fot relative
comparison, the search timese were:

===============  ===========================
Search type      Search time in milliseconds
===============  ===========================
JSON                      32
Dedicated table            6
===============  ===========================

Here, the JSON-based searches were quite a bit slower than searches
using dedicated support tables, even though the JSON approach required
fewer joins and, as a result, Postgres' explain output predicted that
the JSON-based approach would be much faster.

The slowness of the JSON-based approach seems to be due to the fact
that at run time, we're evaluating lots of JSON dynamic expressions.

Despite the difference in performance, it appears that the JSON-based
search is probably fast enough that the advantages of mnot having to
maintian separate tables may justify the added cost.

Using triggers to maintain support tables
_________________________________________

Another alternative to maintaining support tables in the application
would be to maintain them in the database using triggers.  It's
unclear if this would be any more reliable or less of a pain than
maintaining the tables using Python application code.



.. [#xmlpicklef] This was derived from a much older `xmlpickle
   <https://github.com/zopefoundation/zope.xmlpickle>`_ project.

.. [#ghost] In ZODB, ghost objects are objects without state. When a
   ghost object is referenced, it's state is loaded and it becomes a
   non-ghost. Any persistent objects referenced in the state are
   created as ghosts, unless theor already in memory.

.. [#copy] The postgres `copy
   <https://www.postgresql.org/docs/9.4/static/sql-copy.html>`_
   mechanism provides an efficient way to do bulk data export and
   import.

.. [#not-flattened] In this application, we've chosen to store access
   control information only where values are set directly. This makes
   updates inexpensive, but makes search somewhat expensive, because
   we search for access-control information at run time.
   Alternatively, we could have copied data to descendent nodes when
   changes were made, which would have made updates much more
   expensive, but would have made reads much faster.
