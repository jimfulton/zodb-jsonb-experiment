from pprint import pprint
import json
import psycopg2
import unittest

from ..aclfilteredsearch import filteredsearch

check_access = """
create or replace function check_access(
  state jsonb,
  principals varchar[],
  permission varchar)
  returns bool as $$
declare
  acl jsonb;
  want text[] := array[permission, '*'];
begin
  acl := state -> '__acl__';
  if acl is null then
    return null;
  end if;

  for i in 0 .. (jsonb_array_length(acl) - 1)
  loop
    if acl -> i ->> 1 = any(principals) and acl -> i -> 2 ?| want then
       return acl -> i ->> 0 = 'Allow';
    end if;
  end loop;
  return null;
end
$$ language plpgsql;
"""

get_parent_id = """
create or replace function get_parent_id(state jsonb) returns int as $$
begin
  return (state -> '__parent__' -> 'id' ->> 1)::int;
end
$$ language plpgsql;
"""

class Tests(unittest.TestCase):

    def setUp(self):
        conn = self.conn = psycopg2.connect('')
        cursor = self.cursor = conn.cursor()
        ex = self.ex = cursor.execute
        ex("create temp table docs (zoid int, state jsonb)")
        ex(check_access)
        ex(get_parent_id)

        docs = self.docs = dict()

        def newdoc(docid, parent_docid):
            docs[docid] = doc = dict(__parent__ = dict(id = ['', parent_docid]))
            ex("insert into docs values(%s, '%s')"
               % (docid, json.dumps(doc)))

        for i in range(1, 4):
            newdoc(i, 0)
            for j in range(1, 4):
                j += i*10
                newdoc(j, i)
                for k in range(1, 4):
                    k += j*10
                    newdoc(k, j)
                    for l in range(1, 4):
                        l += k*10
                        newdoc(l, k)
                        for m in range(1, 4):
                            m += l*10
                            newdoc(m, l)

    def acl(self, docid, acl):
        acl = [('Allow', 'decoy', 'decoy')] + acl
        for i, ace in enumerate(acl):
            if isinstance(ace[2], str):
                acl[i] = ace[0], ace[1], (ace[2], )

        doc = self.docs[docid]
        doc['__acl__'] = acl
        self.ex("update docs set state='%s' where zoid=%s"
                % (json.dumps(doc), docid))

    def search(self, permission, *principals):
        search = "select * from docs"
        return sorted(filteredsearch(
            search, permission, principals,
            docid='zoid', cursor=self.cursor))

    def tearDown(self):
        self.conn.close()

    def test_no_aces(self):
        self.assertEqual(self.search("read", "bob"), [])

    def test_basic(self):
        self.acl(111, [('Allow', "bob", "read")])
        self.acl(112, [('Allow', "sally", "edit")])

        expect = [(111,), (1111,), (1112,), (1113,), (11111,),
                  (11112,), (11113,), (11121,), (11122,), (11123,),
                  (11131,), (11132,), (11133,)]
        self.assertEqual(self.search("read", "bob"), expect)

    def test_true_before_false(self):
        self.acl(111, [('Allow', "bob", "read"), ('Deny', "bob", "read")])
        expect = [(111,), (1111,), (1112,), (1113,), (11111,),
                  (11112,), (11113,), (11121,), (11122,), (11123,),
                  (11131,), (11132,), (11133,)]
        self.assertEqual(self.search("read", "bob"), expect)

    def test_false_before_true(self):
        self.acl(111, [('Deny', "bob", "read"), ('Allow', "bob", "read")])
        self.acl(11,  [('Deny', "bob", "read"), ('Allow', "bob", "read")])
        self.assertEqual(self.search("read", "bob"), [])

    def test_no_acquire(self):
        self.acl(11, [('Allow', "bob", "read"), ('Deny', "bob", "read")])
        self.acl(111, [('Deny', "bob", "read"), ('Allow', "bob", "read")])
        expect = [(11,), (112,), (113,), (1121,), (1122,), (1123,),
                  (1131,), (1132,), (1133,), (11211,), (11212,),
                  (11213,), (11221,), (11222,), (11223,), (11231,),
                  (11232,), (11233,), (11311,), (11312,), (11313,),
                  (11321,), (11322,), (11323,), (11331,), (11332,),
                  (11333,)]
        self.assertEqual(self.search("read", "bob"), expect)

    def test_extra_noise(self):
        self.acl(11, [('Allow', "bob", "read"),
                      ('Allow', "all", "read"),
                      ('Allow', "sally", "read"),
                      ('Deny', "bob", "read")])
        self.acl(111, [('Deny', "bob", "read"), ('Allow', "bob", "read")])
        expect = [(11,), (112,), (113,), (1121,), (1122,), (1123,),
                  (1131,), (1132,), (1133,), (11211,), (11212,),
                  (11213,), (11221,), (11222,), (11223,), (11231,),
                  (11232,), (11233,), (11311,), (11312,), (11313,),
                  (11321,), (11322,), (11323,), (11331,), (11332,),
                  (11333,)]
        self.assertEqual(self.search("read", "bob", "all"), expect)

    def test_all_permissions(self):
        self.acl(111, [('Allow', "bob", "*")])
        expect = [(111,), (1111,), (1112,), (1113,), (11111,),
                  (11112,), (11113,), (11121,), (11122,),
                  (11123,), (11131,), (11132,), (11133,)]
        self.assertEqual(self.search("read", "bob"), expect)

    def test_sql_retrieval(self):
        sql = filteredsearch("select * from docs", 'read', ('bob', 'all'))
        self.assertEqual(sql.strip().split(), expected_filtered_query)

expected_filtered_query = '''
with recursive
     search_results as (select * from docs),
     allowed(docid, id, parent_id, allowed ) as (
         select docid, docid as id,
                get_parent_id(state),
                check_access(state, array['bob', 'all'], 'read')
         from search_results
      union all
         select allowed.docid, docs.docid as id,
                get_parent_id(docs.state),
                check_access(docs.state, array['bob', 'all'], 'read')
         from allowed, docs
         where allowed.allowed is null and
               allowed.parent_id = docs.docid
    )
select docid  from allowed where allowed
'''.strip().split()


def path(docid):
    if docid:
        return path(docid // 10) + (str(docid) + '/')
    else:
        return '/'

def test_suite():
    return unittest.makeSuite(Tests)

if __name__ == '__main__':
    unittest.main(defaultTest='test_suite')

