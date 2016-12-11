======================
ZODB jsonb experiment
======================

.. contents::

Introduction
============

`RelStorage <http://relstorage.readthedocs.io/en/latest/>`_ provides a
relational-database backed storage for `ZODB <http://www.zodb.org>`_.
It's especially useful when there is either a requirement to or
existing infrastructure for storing data in an `RDBMS
<https://en.wikipedia.org/wiki/Relational_database_management_system>`_.

RelStorage stores data in `Python pickle format
<file:///Users/jim/s/python/python-3.5.2-docs-html/library/pickle.html#module-pickle>`_,
making it impractical to use or even view in the hosting RDBMS.

As is typical in ZODB applications, indexing is provided via BTrees
stored in the RDBMS or using an external indexing facility.  The
search capabilities of the RDBMS aren't leveraged directly.

Postgres 9.2 introduced a JSON data type and Postgres 9.4 introduced
a more efficient JSON data type, `jsonb
<https://www.postgresql.org/docs/9.6/static/datatype-json.html>`_.
JSON is similar in many ways to pickles, and pickle data can be
represented as JSON. Like pickle, JSON is dynamic in nature, providing
much more flexibility than traditional RDBMS tables.  If ZODB data
were stored in JSON format, then they could be viewed and, more
importantly, searched in Postgres directly.

JSON can't replace pickle for data storage, because its type system is
less expressive than Python's.  Conversion from pickle to JSON is
lossy from a type perspective. It could be made less lossy through the
addition of additional JSON data, but doing so would likely render the
JSON too difficult to leverage.

Proof of concept
================

A proof-of-concept experiment was carried out to explore the utility of
storing data as JSON to make it more available in Postgres, while
still supporting use in ZODB.

Test application
----------------

The application used to test the approach is a content-management
system build with `Pyramid
<http://docs.pylonsproject.org/projects/pyramid/en/latest/>`_.  This
is an application that has been in production for some time.  Analysis
was performed against a snapshot of the application's database.

Some points of interest about the application:

- The database (snapshot) has 7.3 million objects.

  - 6.3 million (86%) of the objects are BTree (or BTree component) objects,
    used primarily for indexing.

  - .55 million objects (7.5%) are content objects

  - Remaining objects are various support objects, such as blobs.

  Postgres-level indexes have the potential to reduce database size
  substantially.

- Content objects are arranged hierarchically. Collections (folders)
  are used to support traversal from ancestors to descendents. Parent
  references (``__parent__`` attributes) support traversal from
  descendents to ancestors.

  Near the top of the object hierarchy are ``Community`` objects and
  data are typically accessed by community.

  A access control mechanism allows access control lists (ACLs) to be defined
  at various places in the hierarchy. Access to a particular content
  objects is granted based on ACLs stored on the object and its ancestors.

- Most content is self contained, with relevant data, such as text to
  be searched, residing in content objects directly.

  An exception is ``CommunityFile`` objects that represent files uploaded
  into the system. The files are stored in ZODB blobs and the text
  content of the files is cached in separate ``_CachedData`` objects.

Timing data
-----------

Timing data given here should be mainly interpreted in relative
terms, and perhaps as rough indications of possible performance.
Times could vary widely depending on deployment consideration like
network speeds, disk and CPU speeds, memory, and so on.  Even on the single
system used here, times varied widely from run to run even when runs
were performed a few seconds apart.

Database schema
---------------

For this experiment, Pickle data in a RelStorage table were
converted to JSON and loaded into a separate table.

Indexes were added to the table to support search. Here's a
description of the table and the indexes created::

           Table "public.object_json"
     Column   |       Type        | Modifiers 
  ------------+-------------------+-----------
   zoid       | bigint            | not null
   class_name | character varying | 
   state      | jsonb             | 
  Indexes:
      "object_json_pkey" PRIMARY KEY, btree (zoid)
      "object_json_cached_data_id_idx" btree (cached_data_id(class_name, state))
      "object_json_community_id_idx" btree (get_community_id(class_name, state))
      "object_json_content_text_idx" gin (content_text(class_name, state))
      "object_json_json_idx" gin (state)
  Triggers:
      force_index_of_community_file_trigger
        AFTER INSERT OR UPDATE ON object_json FOR EACH ROW
        EXECUTE PROCEDURE force_index_of_community_file()

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
  for an object, you have to walk up a containment hierarchy until
  you find a community object.  A `PL/pgSQL
  <https://www.postgresql.org/docs/9.4/static/plpgsql.html>`_
  function, `get_community_id <get_community_id.sql>`_ was constructed
  that followed parent pointers in the json data to find community
  ids. An expression indexed used this function to make
  community-id-based searches very fast.

  The function used to create this index is fairly expensive as it may
  make multiple queries to find a community object.  The function is
  normally only used when the index is updated. During a search like::

     select zoid from object_json
     where get_community_id(class_name, state) = '123456'

  The expression: ``get_community_id(class_name, state)`` isn't
  actually evaluated, but is used to select the index.  This provides
  a lot of power when data to be searched require complex computation.

object_json_content_text_idx
  This index is an inverted index supporting full-text search.  It's
  an expression index that indexes the text-extraction function,
  `content_text <content_text.sql>`_.  This too is a non-trivial
  computation that extracts text in an object-type specific way, and,
  in some cases, uses queries to get an object's text from a different
  database record.

object_json_json_idx
  This is a `generic JSON index
  <https://www.postgresql.org/docs/9.4/static/datatype-json.html>`_
  that allows a variety of general queries against the JSON data.
  Some example queries supported by the index:

  - Find all objects that have access control information::

      state ? '__acl__'

  - Find the object with a ``docid`` field with the value ``123456``::

      state @> '{"docid": 123456}'

object_json_cached_data_id_idx
  This index supports search for ``CommunityFile`` objects that reference
  particular ``_CachedData`` objects.  It's an expression index that used a
  `cached_data_id function <cached_data_id.sql>`_ to extract
  ``_CachedData`` object ids.

  See `Cross-object indexing`_ below.

A `trigger
<https://www.postgresql.org/docs/9.4/static/plpgsql-trigger.html>`_
is used to deal with the fact that text for ``CommunityFile`` objects
is stored in associated ``_CachedData`` objects.  See `Cross-object
indexing`_ below.

Cross-object indexing
---------------------

There were 2 important cases where data needed to index an object
required accessing other objects:

- The community id for an object is derived from an ancestor and
  required inspecting all of the ancestors up to the ``Community``
  ancestor.

- ``CommunityFile`` objects store their text in separate
  ``_CachedData`` objects.

In both of these cases, we have to traverse objects to get the data we
need. Because I used expression indexes, we do this traversal when
indexes are build and the traversal is cached for us.

Consider the ``CommunityFile`` case, for example. When we add or
update a ``CommunityFile``, the text index is updated.  If the
associated ``_CachedData`` object is added or updated later, its data
won't be reflected in the index. At the application level, these
objects are typically added or updated at the same time, in the same
transaction. When ZODB and RelStorage commits these changes, it may do
so in any order [#undefined-order]_, because order isn't considered to
be important.  If we're unlucky, the ``CommunityFile`` will be updated
before its ``_CachedData``.

To address this issue, I used a `database trigger function
<force_index_of_community_file.sql>`_ to force reindexing of
``CommunityFile`` objects whenever ``_CachedData`` objects were added
or updated.  It leveraged an expression index,
``object_json_cached_data_id_idx``, to quickly find ``CommunityFile``
objects to reindex.

The content hierarchy is typically static, and descendents are
typically added in later transactions than their ancestors.  However,
bulk loading or creation of hierarchies could cause the same problem
and require a trigger to make sure that objects were indexed properly
if any of their ancestors were created/updated late(r).


JSON conversion
---------------

Because conversion from pickle to JSON is lossy, the JSON data
augments rather than replaces the pickle data.

Data were converted to JSON using the new `xpickle
<https://github.com/jimfulton/xpickle>`_ package, which was created as part of
this experiment [#xmlpicklef]_. Data were converted from a pickle
serialization to a JSON serialization.

A number of `changes
<https://github.com/jimfulton/xpickle/compare/wild>`_ were made in the
course of the experiment that, as of this time, aren't integrated
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
  functions much more complicated.

  One of the open changes made to ``xpickle`` for this analysis was to
  disable this feature. Fortunately, none of the database records used
  in this analysis had cycles.  In ZODB databases, object cycles
  typically cross persistent-object boundaries and are rare within
  database records.

- Pickle supports references between persistent objects (across
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

The conversion process consisted of the following steps:

#. Data were exported from the RelStorage ``object_state`` table:

   ::

     \copy object_state (zoid, state) to STDOUT

   Here I used the `psql \\copy
   <https://www.postgresql.org/docs/9.4/static/app-psql.html>`_ command
   [#postgrescopy]_ to
   copy the object ids and pickles.

#. A `conversion script <convert.py>`_ was used to convert pickles to
   JSON.

   There were some cases where application-specific adjustments are
   necessary. For example, some objects stored text documents as blobs
   and cached the text data from these documents in special cache
   objects.  The data in these objects was compressed using zlib and
   needed to be uncompressed before storing in the database. See
   `convert.py <convert.py>`_.

   For the most part, this is mostly a simple script that converted data
   in pickle format to JSON format. The special handling is in the block
   that start with::

     if c == 'karl.content.models.adapters._CachedData':

   The conversion took about .3 milliseconds per object.

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
     create index object_json_cached_data_id_idx on object_json
            (cached_data_id(class_name, state));

Searching
---------

To assess the efficacy of using JSON object representations for
search, I performed a basic search::

    select zoid from object_json
    where content_text(class_name, state)  @@ :text::tsquery and
          get_community_id(class_name, state) = :community_id

that searched for objects containing a text term (``:text`` above) and
with a given community id.  Remember that we had expression indexes
for the text and community id (``:community_id``).

The search performance was compared to searching a dedicated text
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
server.

===============  ===========================
Search type      Search time in milliseconds
===============  ===========================
JSON                      3.4
Dedicated table           2.0
===============  ===========================

It's surprising to see a difference, given that indexes are used in
both cases, still the performance seems pretty reasonable in both
cases.

The advantage of using JSON, despite the poorer performance is that it
isn't necessary to maintain and update a separate table. The dedicated
table used here was maintaining by application logic that sometimes
failed. The JSON search results contained data that was missing from
the dedicated table.

In addition, a security-filtered search was performed. When searching
for content in a content-management system, you often want to filter
results to those for which a request's associated principals (user and
their groups) have a needed permission.  The security filtering uses
access-control information stored at some nodes in the object
hierarchy [#not-flattened]_.  This required using a recursive query to
find and evaluate the access control lists relevant to a search
result.

A `template <src/j1m/jsonbfilteredsearch/__init__.py>`_ was used to
generate a filtered search query from a base search query.  The
generated query was::

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

Again the absolute values aren't important but for relative
comparison, the search times were:

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
search is probably fast enough that the advantages of not having to
maintain separate tables may justify the added cost.

Using triggers to maintain support tables
_________________________________________

Another alternative to maintaining support tables in the application
would be to maintain them in the database using triggers.

Insert performance
------------------

The database design used here used several indexes and a trigger and
requires calling non-trivial stored procedures on update.  To assess
the impact of this, I copied 1000 content records::

  create temp table tdata as
  select zoid + 900000000 as zoid, class_name, state
  from object_json
  where state ? '__parent__' and state ? 'docid' limit 1000;

I added an offset to the object ids to make them unique.  I then
inserted these rows back into the object_json table::

  delete from object_json where zoid >= 900000000;
  insert into object_json select * from tdata;

I did this several times.  The shortest insert time was 140
milliseconds, .14 milliseconds per record.  I used a bulk insert
to assess the index impact without transaction or application
overhead.

I performed a similar analysis on the ``object_state`` table to get a
baseline for comparison::

  create temp table zoids as select zoid from tdata;
  create temp table pdata as
  select zoid+900000000, tid, state_size, state
  from object_state p
  join toids using (zoid);

And I inserted::

  delete from object_state where zoid >= 900000000;
  insert into object_state select * from pdata;

I tried this several times, and it took at least 800 milliseconds (.8
milliseconds/record). This was very surprising.  The ``object_state``
used by RelStorage::

     Table "public.object_state"
     Column   |  Type  | Modifiers 
  ------------+--------+-----------
   zoid       | bigint | not null
   tid        | bigint | not null
   state_size | bigint | not null
   state      | bytea  | 
  Indexes:
      "object_state_pkey" PRIMARY KEY, btree (zoid)
      "object_state_tid" btree (tid)
  Check constraints:
      "object_state_state_size_check" CHECK (state_size >= 0)
      "object_state_tid_check" CHECK (tid > 0)
  Referenced by:
      TABLE "blob_chunk" CONSTRAINT "blob_chunk_fk"
      FOREIGN KEY (zoid) REFERENCES object_state(zoid) ON DELETE CASCADE

has fewer and simpler indexes than object_json.  I decided to
make a copy of the table::

  create temp table object_statec as select * from object_state;

I added the same indexes and check constraints, and then tried the data
inserts.  For the copy of the database the insert times were a few
milliseconds, or a few microseconds (effectively 0) per record.

The only other difference in configuration is the referencing foreign
key constraint that could cause referencing blob chunk records to be
deleted on deletion of a state record.  It was impractical to set this
up for the copy and it seems unlikely that this would slow inserts.

I suspect that the times for the original table were affected by
fragmentation of some sort.  I tried to do a full `vacuum
<https://www.postgresql.org/docs/9.4/static/sql-vacuum.html>`_ of the
original table. This seemed to take too long (and use too few
computing resources), so I impatiently stopped it and did a regular
vacuum overnight. After the vacuum, the minimum insert time fell to
about 100ms (100 microseconds/record).  I may try again to do a full
vacuum later.  Note that the database copy should be roughly
equivalent to the full vacuum.

It appears that update overhead of the new indexes is acceptable.  The
update times are on the same order of magnitude as the existing update
times. Of course, this performance test provides only a rough
guess at what the impact might be in production.

In addition to updating indexes, pickle data must be converted to
JSON. The observed cost of this is fairly low, about .3 milliseconds per
record, and perhaps more importantly, the cost would be borne by
clients, not the database server and would therefore not affect
scalability.

It's reasonable to expect that if JSON-based indexing removed the need
for application-level indexing using BTrees, the overall load of
updates will be reduced, as we'll no-longer need to manage as many
BTrees and the database size will be reduced substantially.

Asynchronous updates
____________________

If synchronous updates of JSON indexes turned out to be too
burdensome, it would be straightforward to provide asynchronous and
nearly real-time indexing using a combination of database triggers and
Postgres' notification system. (Such a system could also be used to
update external indexes.)

Conclusion
==========

Postgres' capability to index, leveraging expression indexes and
search JSON data is compelling, as is the ability to see object data
and perform generic searches using SQL.

Search and update performance is good and likely to be much better
than with existing catalog-based search, especially considering:

- Much of the work is done in C rather than Python.

- Search leverages Postgres' query optimization, which is far more
  sophisticated than that used by Python catalogs.

- Using Postgres indexes allows us to manage much fewer objects in the
  database.

Some downsides:

- We loose a lot of the flexibility of indexing in Python:

  - Object-oriented dispatch for data extraction.

  - Ability to express data extraction in Python. In comparison to
    Python, PL/pgSQL is pretty awful.  Postgres does support for
    Python stored procedures.

- We could end up with a fair bit of indexing logic in stored
  procedures, which provides an extra maintenance burden. In the long
  term, however, this logic would likely replace existing logic in
  Python and might be a wash.


.. [#undefined-order] To be more precise, the order is
   undefined. There may actually be a predictable order, but that
   order is an implementation detail that is subject to change.

.. [#xmlpicklef] This was derived from a much older `xmlpickle
   <https://github.com/zopefoundation/zope.xmlpickle>`_ project.

.. [#ghost] In ZODB, ghost objects are objects without state. When a
   ghost object is referenced, it's state is loaded and it becomes a
   non-ghost. Any persistent objects referenced in the state are
   created as ghosts, unless their already in memory.

.. [#postgrescopy] The Postgres `copy
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
