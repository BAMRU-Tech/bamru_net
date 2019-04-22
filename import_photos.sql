TRUNCATE main_memberphoto CASCADE;

insert into main_memberphoto (id, member_id, name, file, extension, content_type, size, position, created_at, updated_at)
select id, member_id, image_file_name, format('images/%s/original/%s', id, image_file_name), substring(image_file_name, '[^.]+$'), image_content_type, image_file_size, position, created_at, updated_at from photos;

SELECT SETVAL('main_memberphoto_id_seq', (SELECT MAX(id) + 1 FROM main_memberphoto));
