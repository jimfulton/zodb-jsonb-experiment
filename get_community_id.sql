create or replace function get_community_id(
  class_name varchar,
  state jsonb)
  returns text
as $$
declare
  parent_class_name varchar;
  parent_state jsonb;
  parent_id bigint;
begin
  if state is null then return null; end if;
  if class_name = 'karl.models.community.Community' then
     return state ->> 'docid';
  end if;
  parent_id := (state -> '__parent__' -> 'id' ->> 0)::bigint;
  if parent_id is null then return null; end if;
  select object_json.class_name, object_json.state
  from object_json
  where zoid = parent_id
  into parent_class_name, parent_state;

  if parent_class_name is null then
    return null;
  end if;

  return get_community_id(parent_class_name, parent_state);
end
$$ language plpgsql immutable;
