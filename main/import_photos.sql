INSERT INTO main_photofile (id, created_at, updated_at, position, file, member_id)
    SELECT id, created_at, updated_at, position, CONCAT('images/', id, '/original/', image_file_name), member_id
    FROM photos;
SELECT SETVAL('main_photofile_id_seq', (SELECT MAX(id) + 1 FROM main_photofile));
