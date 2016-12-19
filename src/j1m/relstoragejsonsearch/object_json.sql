create table object_json (
  zoid bigint primary key,
  class_name text,
  class_pickle bytea,
  state jsonb);
create index object_json_json_idx on object_json using gin (state);

create table object_json_tid (id int, tid bigint);
insert into object_json_tid values (0, 0);

create function notify_object_state_changed() returns trigger
as $$
begin
  perform pg_notify('object_state_changed', NEW.tid::text);
  return NEW;
end;
$$ language plpgsql;

create trigger trigger_notify_object_state_changed
  after insert or update on object_state for each row
  execute procedure notify_object_state_changed();
