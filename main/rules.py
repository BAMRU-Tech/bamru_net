import rules

import logging
logger = logging.getLogger(__name__)

# Predicates are only used in this file

@rules.predicate
def is_member_self(user, member): # only for Member
    return member == user

@rules.predicate
def is_owner(user, obj):  # For models with a member field
    if not user.is_authenticated:
        return False
    if obj is None: # If non-object permission, we accept it
        return True
    if not hasattr(obj, 'member'):
        return False
    return obj.member == user

@rules.predicate
def can_add_member(user):
    return (user.is_authenticated and
            user.role_set.filter(role__in=['RO',]).exists())

@rules.predicate
def is_member_editor(user):
    return (user.is_authenticated and
            user.role_set.filter(role__in=['SEC', 'OO', 'RO',]).exists())

@rules.predicate
def is_cert_editor(user):
    return (user.is_authenticated and
            user.role_set.filter(role__in=['SEC', 'OO',]).exists())

@rules.predicate
def is_do_planner(user):
    return (user.is_authenticated and
            user.role_set.filter(role__in=['DOS',]).exists())


# Permissions are used in views and templates. Follow the Django
# naming scheme where possible: add_X, view_X, change_X, delete_X

rules.add_perm('main', rules.is_authenticated)

rules.add_perm('main.add_member', can_add_member)
rules.add_perm('main.view_member', rules.is_authenticated)
rules.add_perm('main.change_member', is_member_self | is_member_editor)
rules.add_perm('main.change_certs_for_member', is_member_self | is_cert_editor)

# Message models - anyone can send, backend does receive
rules.add_perm('main.add_message', rules.is_authenticated)
for model in ['message', 'inboundsms',]:
    rules.add_perm('main.view_%s' % model, rules.is_authenticated)

# Plan the DO calendar
rules.add_perm('main.add_doavailable', rules.is_authenticated)
rules.add_perm('main.view_doavailable', rules.is_authenticated)
rules.add_perm('main.change_doavailable', is_owner | is_do_planner)
rules.add_perm('main.change_assigned_for_doavailable', is_do_planner)

# Need owner to create. These need CreatePermModelSerializer
for model in ['memberphoto', ]:
    rules.add_perm('main.add_%s' % model, is_owner)
    rules.add_perm('main.view_%s' % model, rules.is_authenticated)
    rules.add_perm('main.change_%s' % model, is_owner)
    rules.add_perm('main.delete_%s' % model, is_owner)

rules.add_perm('main.add_cert', is_owner | is_cert_editor)
rules.add_perm('main.view_cert', rules.is_authenticated)
rules.add_perm('main.change_cert', is_owner | is_cert_editor)
rules.add_perm('main.delete_cert', is_owner | is_cert_editor)


# Simple owner models
for model in ['unavailable', ]:
    rules.add_perm('main.add_%s' % model, rules.is_authenticated)
    rules.add_perm('main.view_%s' % model, rules.is_authenticated)
    rules.add_perm('main.change_%s' % model, is_owner)
    rules.add_perm('main.delete_%s' % model, is_owner)

# Models with open permission
for model in ['event', 'period', 'participant', ]:
    rules.add_perm('main.add_%s' % model, rules.is_authenticated)
    rules.add_perm('main.view_%s' % model, rules.is_authenticated)
    rules.add_perm('main.change_%s' % model, rules.is_authenticated)
    rules.add_perm('main.delete_%s' % model, rules.is_authenticated)
