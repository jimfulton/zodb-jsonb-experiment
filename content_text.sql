
create or replace function content_text(class_name varchar, state jsonb)
  returns tsvector as $$
declare
  title varchar;
  description varchar;
  text varchar;
  textv tsvector;
  hoid varchar;
  r object_json%ROWTYPE;
begin
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
  elseif class_name = 'karl.content.interfaces.ICommunityFile' then
    hoid := state #>> '{"_extracted_data", "id", 1}';
    if hoid is not null then
      select cls, state
      from object_json where lpad(to_hex(zoid), 16, '0'::text) = hoid
      into class_name, state;
      if class_name != 'karl.content.models.adapters._CachedData' then
        raise 'bad data in CommunityFile % %', hoid, class_name;
      end if;
      return content_text(class_name, state);
    end if;
    text := '';
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
