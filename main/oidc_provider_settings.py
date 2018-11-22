def userinfo(claims, user):
    # Populate claims dict.
    claims['preferred_username'] = '{0}.{1}'.format(user.first_name, user.last_name)
    claims['name'] = user.full_name
    claims['given_name'] = user.first_name
    claims['family_name'] = user.last_name
    claims['email'] = user.display_email

    return claims
