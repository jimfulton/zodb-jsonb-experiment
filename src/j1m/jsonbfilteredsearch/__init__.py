
template = """
with recursive
     search_results as ({search}),
     allowed({docid}, id, parent_id, allowed {extra}) as (
         select {docid}, {docid} as id,
                {get_parent_id}({state}),
                {check_access}({state}, array{principals}, '{permission}')
                {extra}
         from search_results
      union all
         select allowed.{docid}, {docs}.{docid} as id,
                {get_parent_id}({docs}.{state}),
                check_access({docs}.{state}, array{principals}, '{permission}')
                {extra}
         from allowed, {docs}
         where allowed.allowed is null and
               allowed.parent_id = {docs}.{docid}
    )
select {docid} {extra} from allowed where allowed
"""

def filteredsearch(
    cursor, search, permission, principals, extra='',
    docid='docid', docs='docs', state='state', get_parent_id='get_parent_id',
    check_access='check_access',
    ):
    principals = repr(list(principals)).replace(',)', ')')
    sql = template.format(
        search=search,
        permission=permission,
        principals=principals,
        extra=extra and ", " + extra,
        docid=docid,
        docs=docs,
        state=state,
        get_parent_id=get_parent_id,
        check_access=check_access,
        )
    if cursor is None:
        print(sql)
    else:
        try:
            cursor.execute(sql)
        except Exception:
            print(sql)
            raise

        return cursor.fetchall()