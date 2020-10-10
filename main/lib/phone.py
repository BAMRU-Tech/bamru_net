import phonenumbers
from django.core.exceptions import ValidationError

def format_e164(number):
    """Format a phone number like +11234567890."""
    return phonenumbers.format_number(
        phonenumbers.parse(number, 'US'),
        phonenumbers.PhoneNumberFormat.E164)

def format_display(number):
    """Format a phone number like 123-456-7890."""
    us_format = phonenumbers.NumberFormat(
        pattern="(\\d{3})(\\d{3})(\\d{4})",
        format="\\1-\\2-\\3")
    try:
        return phonenumbers.format_by_pattern(
            phonenumbers.parse(number, 'US'),
            phonenumbers.PhoneNumberFormat.NATIONAL,
            [us_format])
    except phonenumbers.NumberParseException:
        return number

def validate_phone(value):
    """Validator for phone number fields in models."""
    try:
        p = phonenumbers.parse(value, 'US')
    except phonenumbers.NumberParseException:
        raise ValidationError('{} is not a parsable phone number'.format(value))
    if not phonenumbers.is_possible_number(p):
        raise ValidationError('{} is not a valid phone number'.format(value))
