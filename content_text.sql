create or replace function content_text(class_name varchar, state jsonb)
  returns tsvector as $$
declare
  text varchar;
  textv tsvector;
  hoid bigint;
begin
  if state is null then return null; end if;
  if class_name = 'karl.models.profile.Profile' then
    text :=
      coalesce(state #>> '{"__name__"}', '')
      || ' ' || coalesce(state #>> '{"firstname"}', '')
      || ' ' || coalesce(state #>> '{"lastname"}', '')
      || ' ' || coalesce(state #>> '{"email"}', '')
      || ' ' || coalesce(state #>> '{"phone"}', '')
      || ' ' || coalesce(state #>> '{"extension"}', '')
      || ' ' || coalesce(state #>> '{"department"}', '')
      || ' ' || coalesce(state #>> '{"position"}', '')
      || ' ' || coalesce(state #>> '{"organization"}', '')
      || ' ' || coalesce(state #>> '{"location"}', '')
      || ' ' || coalesce(state #>> '{"country"}', '')
      || ' ' || coalesce(state #>> '{"website"}', '')
      || ' ' || coalesce(state #>> '{"languages"}', '')
      || ' ' || coalesce(state #>> '{"office"}', '')
      || ' ' || coalesce(state #>> '{"room_no"}', '')
      || ' ' || coalesce(state #>> '{"biography"}', '');
  elseif class_name = 'karl.content.models.files.CommunityFile' then
    hoid := (state #>> '{"_extracted_data", "id", 0}')::bigint;
    if hoid is not null then
      select object_json.class_name, object_json.state
      from object_json where zoid = hoid
      into class_name, state;
      if class_name != 'karl.content.models.adapters._CachedData' then
        raise 'bad data in CommunityFile % %', hoid, class_name;
      end if;
      text := coalesce(state #>> '{"text"}', '');
    else
      text := '';
    end if;
  elseif class_name = 'karl.content.models.adapters._CachedData' then
    return null;
  else
    text := coalesce(state #>> '{"text"}', '');
  end if;

  textv := to_tsvector(text);

  if state ? 'title' then
    textv := textv
      || setweight(to_tsvector(state #>> '{"title"}'), 'A')
      || setweight(to_tsvector(coalesce(state #>> '{"description"}', '')), 'B');
  else
    textv := textv
      || setweight(to_tsvector(coalesce(state #>> '{"description"}', '')), 'A');
  end if;

  return textv;
end
$$ language plpgsql immutable;
