TRUNCATE bnet_member, bnet_address, bnet_email, bnet_phone, bnet_emergencycontact, bnet_role, bnet_otherinfo, bnet_event, bnet_period, bnet_participant, bnet_message, bnet_distribution CASCADE;

insert into bnet_member (id, first_name, last_name, username, typ, dl, ham, v9, is_active, is_staff, is_superuser, is_current_do, sign_in_count, last_sign_in_at, created_at, updated_at, password)
select id, first_name, last_name, user_name, typ, dl, ham, v9, TRUE, admin, developer, current_do, sign_in_count, last_sign_in_at, created_at, updated_at, 'bcrypt$' || password_digest from members where typ is not null;

insert into bnet_address (id, member_id, typ, address1, address2, city, state, zip, position, created_at, updated_at)
select id, member_id, typ, address1, address2, city, state, zip, COALESCE(position, 1), created_at, updated_at from addresses;

insert into bnet_email (id, member_id, typ, pagable, address, position, created_at, updated_at)
select id, member_id, typ, case pagable when '1' then true else false end, address, position, created_at, updated_at from emails;

insert into bnet_phone (id, member_id, typ, pagable, number, sms_email, position, created_at, updated_at)
select id, member_id, typ, case pagable when '1' then true else false end, number, sms_email, position, created_at, updated_at from phones;

insert into bnet_emergencycontact (id, member_id, typ, name, number, position, created_at, updated_at)
select id, member_id, typ, name, number, position, created_at, updated_at from emergency_contacts;

insert into bnet_role (id, member_id, typ, created_at, updated_at)
select id, member_id, typ, created_at, updated_at from roles;

insert into bnet_otherinfo (id, member_id, label, value, position, created_at, updated_at)
select id, member_id, label, value, position, created_at, updated_at from other_infos;

insert into bnet_event (id, typ, title, leaders, description, location, lat, lon, start, finish, all_day, published, created_at, updated_at)
select id, typ, title, leaders, description, location, lat, lon, start, finish, all_day, published, created_at, updated_at from events;

insert into bnet_period (id, event_id, position, start, finish, created_at, updated_at)
select id, event_id, position, start, finish, created_at, updated_at from periods;

insert into bnet_participant (id, period_id, member_id, ahc, ol, comment, en_route_at, return_home_at, signed_in_at, signed_out_at, created_at, updated_at)
select id, period_id, member_id, ahc, ol, comment, en_route_at, return_home_at, signed_in_at, signed_out_at, created_at, updated_at from participants where member_id in (select distinct id from bnet_member);

insert into bnet_message (id, author_id, text, format, linked_rsvp_id, ancestry, period_id, period_format, created_at, updated_at)
select id, author_id, text, format, linked_rsvp_id, ancestry, period_id, period_format, created_at, updated_at from messages where author_id in (select distinct id from bnet_member);

insert into bnet_distribution (id, message_id, member_id, email, phone, read, bounced, read_at, response_seconds, rsvp, rsvp_answer, unauth_rsvp_token, unauth_rsvp_expires_at, created_at, updated_at)
select id, message_id, member_id, email, phone, read, bounced, read_at, response_seconds, rsvp, case rsvp_answer when 'Yes' then true when 'No' then false else null end, unauth_rsvp_token, unauth_rsvp_expires_at, created_at, updated_at from distributions where message_id in (select distinct id from bnet_message);
