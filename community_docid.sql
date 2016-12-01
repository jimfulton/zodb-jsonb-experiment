create or replace function get_community_id(
  class_name_arg varchar,
  state_arg jsonb)
  returns text
as $$
declare
  parent_class_name varchar;
  parent_state jsonb;
  parent_id text;
begin
  if class_name_arg = 'karl.models.community.Community' then
     return state_arg ->> 'docid';
  end if;
  parent_id := state_arg -> '__parent__' -> 'id' ->> 0;
  select cls, state
  from object_json
  where lpad(to_hex(zoid), 16, '0'::text) = parent_id
  into parent_class_name, parent_state;

  if parent_class_name is null then
    return null;
  end if;

  return get_community_id(parent_class_name, parent_state);
end
$$ language plpgsql immutable;
