create or replace function cached_data_id(class_name varchar, state jsonb)
  returns bigint as $$
begin
  if class_name = 'karl.content.models.files.CommunityFile' then
    return (state #>> '{"_extracted_data", "id", 0}')::bigint;
  else
    return null;
  end if;
end
$$ language plpgsql immutable;
