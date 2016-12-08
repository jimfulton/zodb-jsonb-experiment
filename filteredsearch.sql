
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

\timing

\echo base search

select count(*) from (
  select zoid from object_json
  where content_text(class_name, state)  @@ :text::tsquery and
        get_community_id(class_name, state) = :community_id
  ) _;

select count(*) from (
  select zoid from object_json
  where content_text(class_name, state)  @@ :text::tsquery and
        get_community_id(class_name, state) = :community_id
  ) _;

select count(*) from (
  select zoid from object_json
  where content_text(class_name, state)  @@ :text::tsquery and
        get_community_id(class_name, state) = :community_id
  ) _;

explain analyze select count(*) from (
  select zoid from object_json
  where content_text(class_name, state)  @@ :text::tsquery and
        get_community_id(class_name, state) = :community_id
  ) _;

----------------------------------------------------------------------

\echo filtered search

select count(*) from (
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
                    array[:user,
                          :group,
                          'system.Everyone'],
                    'edit')
           from search_results
        union all
           select allowed.zoid, object_json.zoid as id,
                  (object_json.state #>> '{"__parent__", "id", 0}')::bigint,
                  jsonb_check_access(
                    object_json.state,
                    array[:user,
                          :group,
                          'system.Everyone'],
                    'edit')
           from allowed, object_json
           where allowed.allowed is null and
                 object_json.zoid = allowed.parent_id
                
      )
  select zoid  from allowed where allowed
  ) _;

select count(*) from (
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
                    array[:user,
                          :group,
                          'system.Everyone'],
                    'edit')
           from search_results
        union all
           select allowed.zoid, object_json.zoid as id,
                  (object_json.state #>> '{"__parent__", "id", 0}')::bigint,
                  jsonb_check_access(
                    object_json.state,
                    array[:user,
                          :group,
                          'system.Everyone'],
                    'edit')
           from allowed, object_json
           where allowed.allowed is null and
                 object_json.zoid = allowed.parent_id
                
      )
  select zoid  from allowed where allowed
  ) _;

select count(*) from (
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
                    array[:user,
                          :group,
                          'system.Everyone'],
                    'edit')
           from search_results
        union all
           select allowed.zoid, object_json.zoid as id,
                  (object_json.state #>> '{"__parent__", "id", 0}')::bigint,
                  jsonb_check_access(
                    object_json.state,
                    array[:user,
                          :group,
                          'system.Everyone'],
                    'edit')
           from allowed, object_json
           where allowed.allowed is null and
                 object_json.zoid = allowed.parent_id
                
      )
  select zoid  from allowed where allowed
  ) _;

explain analyze select count(*) from (
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
                    array[:user,
                          :group,
                          'system.Everyone'],
                    'edit')
           from search_results
        union all
           select allowed.zoid, object_json.zoid as id,
                  (object_json.state #>> '{"__parent__", "id", 0}')::bigint,
                  jsonb_check_access(
                    object_json.state,
                    array[:user,
                          :group,
                          'system.Everyone'],
                    'edit')
           from allowed, object_json
           where allowed.allowed is null and
                 object_json.zoid = allowed.parent_id
                
      )
  select zoid  from allowed where allowed
  ) _;
