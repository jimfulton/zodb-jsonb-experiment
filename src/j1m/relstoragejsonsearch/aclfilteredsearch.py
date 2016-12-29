
template = """
with recursive
   search_results as ({search}),
   allowed({docid}, id, parent_id, allowed {extrav}) as (
       select {docid}, {docid} as id,
              {get_parent_id}({state}),
              {check_access}({state}, array{principals}, '{permission}')
              {extrav}
       from search_results
    union all
       select allowed.{docid}, {docs}.{docid} as id,
              {get_parent_id}({docs}.{state}),
              {check_access}({docs}.{state}, array{principals}, '{permission}')
              {extra}
       from allowed, {docs}
       where allowed.allowed is null and
             allowed.parent_id = {parent_expr}
  )
select {docid} {extra} from allowed where allowed
"""

def filteredsearch(
    search, permission, principals, extra='',
    docid='docid', docs='docs', state='state', get_parent_id='get_parent_id',
    check_access='check_access', parent_expr=None, cursor=None,
    ):
    principals = repr(list(principals)).replace(',)', ')')
    if extra:
        extrav = ',' + extra
        extra = extrav.replace(',', ',allowed.')
    else:
        extrav = ''

    sql = template.format(
        search=search,
        permission=permission,
        principals=principals,
        extra=extra,
        extrav=extrav,
        docid=docid,
        docs=docs,
        state=state,
        get_parent_id=get_parent_id,
        check_access=check_access,
        parent_expr=
        parent_expr or "{docs}.{docid}".format(docs=docs, docid=docid),
        )
    if cursor is None:
        return sql
    else:
        try:
            cursor.execute(sql)
        except Exception:
            print(sql)
            raise

        return cursor.fetchall()
