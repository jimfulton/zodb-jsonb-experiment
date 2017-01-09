Changes
*******

- Implemented a --redo option on the updater to redo old JSON conversions.

- Added a generic update iterator (actually a batch iterator, where
  each batch is a tid, zoid, state iterator) for RelStorage
  non-history-preserving databases.

- Removed some application-specific transformation logic.


0.2.1 (2017-01-07)
==================

- Fixed: package didn't include an sql file needed by the updater.

0.2.0 (2017-01-06)
==================

- Added search_batch function for retrieving a batch from a search
  *and* the total result size.

- You can now supply a state-transformation function.

0.1.0 (2017-01-05)
==================

- The updater now setups up object_json etc if it doesn't exist.

- Fixed: the search API didn't provide a way to supply psycopg2
  statement arguments.
