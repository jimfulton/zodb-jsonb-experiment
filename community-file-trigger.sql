delete from object_json where zoid in (800000000, 800000001);
drop trigger if exists force_index_of_community_file_trigger on object_json;
drop index if exists object_json_cached_data_id_idx;

insert into object_json values(
  800000000,
  'karl.content.models.files.CommunityFile',
  '{"title": "testtitle",
    "_extracted_data":
      {"::": "persistent",
       "id": [800000001, "karl.content.models.adapters._CachedData"]
       }
    }');

insert into object_json values(
  800000001,
  'karl.content.models.adapters._CachedData',
  '{"text": "testcacheddata"}');

select * from object_json
where content_text(class_name, state) @@ 'testcacheddata'::tsquery;

update object_json set state = state || '{"b": 1}'::jsonb
where zoid = 800000001;

select * from object_json
where content_text(class_name, state) @@ 'testcacheddata'::tsquery;

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

create index object_json_cached_data_id_idx
  on object_json (cached_data_id(class_name, state));

create or replace function force_index_of_community_file() returns trigger
as $$
  begin
    if NEW.class_name = 'karl.content.models.adapters._CachedData' then
      update object_json
        set state = state || json_build_object('_cached_data_updated_at',
                                               current_timestamp::text)::jsonb
        where cached_data_id(class_name, state) = NEW.zoid;
    end if;
    return NEW;
  end;
$$ language plpgsql;

create trigger force_index_of_community_file_trigger
    after insert or update on object_json for each row
    execute procedure force_index_of_community_file();

update object_json set state = state || '{"b": 2}'::jsonb
where zoid = 800000001;

select * from object_json
where content_text(class_name, state) @@ 'testcacheddata'::tsquery;

delete from object_json where zoid in (800000000, 800000001);
