Changes
*******

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
