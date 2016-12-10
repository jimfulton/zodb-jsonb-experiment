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
