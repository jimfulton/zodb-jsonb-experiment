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
