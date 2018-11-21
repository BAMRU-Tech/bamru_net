TRUNCATE main_member, main_address, main_email, main_phone, main_emergencycontact, main_role, main_otherinfo, main_unavailable, main_cert, main_event, main_period, main_participant, main_message, main_distribution, main_rsvptemplate, main_doavailable CASCADE;

insert into main_member (id, first_name, last_name, username, status, dl, ham, v9, is_active, is_staff, is_superuser, is_current_do, sign_in_count, last_sign_in_at, created_at, updated_at, password)
select id, first_name, last_name, replace(user_name,'_',' '), typ, dl, ham, v9, TRUE, admin, developer, current_do, sign_in_count, last_sign_in_at, created_at, updated_at, 'bcrypt$' || password_digest from members where typ is not null;

insert into main_address (id, member_id, type, address1, address2, city, state, zip, position, created_at, updated_at)
select id, member_id, typ, address1, address2, city, state, zip, COALESCE(position, 1), created_at, updated_at from addresses;

insert into main_email (id, member_id, type, pagable, address, position, created_at, updated_at)
select id, member_id, typ, case pagable when '1' then true else false end, address, position, created_at, updated_at from emails;

insert into main_phone (id, member_id, type, pagable, number, sms_email, position, created_at, updated_at)
select id, member_id, typ, case pagable when '1' then true else false end, number, sms_email, position, created_at, updated_at from phones;

insert into main_emergencycontact (id, member_id, type, name, number, position, created_at, updated_at)
select id, member_id, typ, name, number, position, created_at, updated_at from emergency_contacts;

insert into main_role (id, member_id, role, created_at, updated_at)
select id, member_id, typ, created_at, updated_at from roles;

insert into main_otherinfo (id, member_id, label, value, position, created_at, updated_at)
select id, member_id, label, value, position, created_at, updated_at from other_infos;

insert into main_unavailable (id, member_id, start_on, end_on, comment, created_at, updated_at)
select id, member_id, start_on, end_on, comment, created_at, updated_at from avail_ops;

insert into main_cert (id, member_id, type, expiration, description, comment, link, position, cert_file, cert_file_name, cert_content_type, cert_file_size, cert_updated_at, created_at, updated_at, ninety_day_notice_sent_at, thirty_day_notice_sent_at, expired_notice_sent_at)
select id, member_id, typ, expiration, description, comment, link, position, cert_file, cert_file_name, cert_content_type, cert_file_size, cert_updated_at, created_at, updated_at, ninety_day_notice_sent_at, thirty_day_notice_sent_at, expired_notice_sent_at from certs;


insert into main_event (id, type, title, leaders, description, location, lat, lon, start_on, finish_on, all_day, published, created_at, updated_at)
select id, typ, title, leaders, description, location, lat, lon, start, finish, all_day, published, created_at, updated_at from events;

insert into main_period (id, event_id, position, start_on, finish_on, created_at, updated_at)
select id, event_id, position, start, finish, created_at, updated_at from periods;

insert into main_participant (id, period_id, member_id, ahc, ol, comment, en_route_at, return_home_at, signed_in_at, signed_out_at, created_at, updated_at)
select id, period_id, member_id, ahc, ol, comment, en_route_at, return_home_at, signed_in_at, signed_out_at, created_at, updated_at from participants where member_id in (select distinct id from main_member);

insert into main_message (id, author_id, text, format, linked_rsvp_id, ancestry, period_id, period_format, created_at, updated_at)
select id, author_id, text, format, linked_rsvp_id, ancestry, period_id, period_format, created_at, updated_at from messages where author_id in (select distinct id from main_member);

insert into main_distribution (id, message_id, member_id, send_email, send_sms, read, bounced, read_at, response_seconds, rsvp, rsvp_answer, unauth_rsvp_token, unauth_rsvp_expires_at, created_at, updated_at)
select id, message_id, member_id, email, phone, read, bounced, read_at, response_seconds, rsvp, case rsvp_answer when 'Yes' then true when 'No' then false else null end, unauth_rsvp_token, unauth_rsvp_expires_at, created_at, updated_at from distributions where message_id in (select distinct id from main_message);

insert into main_rsvptemplate (id, name, prompt, yes_prompt, no_prompt, position, created_at, updated_at)
select id, name, prompt, yes_prompt, no_prompt, position, created_at, updated_at from rsvp_templates;

insert into main_doavailable (id, member_id, year, quarter, week, available, assigned, comment, created_at, updated_at)
select id, member_id, year, quarter, week, case typ when 'available' then true else false end, false, comment, created_at, updated_at from avail_dos where member_id in (select distinct id from main_member);

update main_doavailable set assigned = true
from do_assignments where
main_doavailable.member_id = do_assignments.primary_id and
main_doavailable.year = do_assignments.year and
main_doavailable.quarter = do_assignments.quarter and
main_doavailable.week = do_assignments.week;
