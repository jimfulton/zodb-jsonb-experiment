create index object_json_cls_idx on object_json (cls);
create index object_json_docid_idx on object_json
  using hash (((state #>> '{docid}'::text[])::integer));
create index object_json_hex_zoid_idx on object_json
  using hash (lpad(to_hex(zoid), 16, '0'::text));
create index object_json_json_idx on object_json using gin (state);
create index object_json_zoid_idx on object_json using hash (zoid);
create index object_json_content_text_idx on object_json
  using gin (content_text(cls, state);

