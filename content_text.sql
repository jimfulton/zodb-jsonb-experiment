create or replace function content_text(class_name varchar, state_ jsonb)
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
      coalesce(state_ #>> '{"__name__"}', '')
      || ' ' || coalesce(state_ #>> '{"firstname"}', '')
      || ' ' || coalesce(state_ #>> '{"lastname"}', '')
      || ' ' || coalesce(state_ #>> '{"email"}', '')
      || ' ' || coalesce(state_ #>> '{"phone"}', '')
      || ' ' || coalesce(state_ #>> '{"extension"}', '')
      || ' ' || coalesce(state_ #>> '{"department"}', '')
      || ' ' || coalesce(state_ #>> '{"position"}', '')
      || ' ' || coalesce(state_ #>> '{"organization"}', '')
      || ' ' || coalesce(state_ #>> '{"location"}', '')
      || ' ' || coalesce(state_ #>> '{"country"}', '')
      || ' ' || coalesce(state_ #>> '{"website"}', '')
      || ' ' || coalesce(state_ #>> '{"languages"}', '')
      || ' ' || coalesce(state_ #>> '{"office"}', '')
      || ' ' || coalesce(state_ #>> '{"room_no"}', '')
      || ' ' || coalesce(state_ #>> '{"biography"}', '');
  elseif class_name = 'karl.content.models.files.CommunityFile' then
    hoid := state_ #>> '{"_extracted_data", "id", 0}';
    if hoid is not null then
      select cls, state
      from object_json where lpad(to_hex(zoid), 16, '0'::text) = hoid
      into class_name, state_;
      if class_name != 'karl.content.models.adapters._CachedData' then
        raise 'bad data in CommunityFile % %', hoid, class_name;
      end if;
      return content_text(class_name, state_);
    end if;
    text := '';
  else
    text := coalesce(state_ #>> '{"text"}', '');
  end if;

  textv := to_tsvector(text);

  if state_ ? 'title' then
    textv := textv
      || setweight(to_tsvector(state_ #>> '{"title"}'), 'A')
      || setweight(to_tsvector(coalesce(state_ #>> '{"description"}', '')), 'B');
  else
    textv := textv
      || setweight(to_tsvector(coalesce(state_ #>> '{"description"}', '')), 'A');
  end if;

  return textv;
end
$$ language plpgsql immutable;
