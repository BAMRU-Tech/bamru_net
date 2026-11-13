from django import template
from django.utils.safestring import mark_safe

register = template.Library()

@register.filter
def define(val=None):
  return val

@register.filter
def rangearray(v):
    """Generate an array, useful in for loops"""
    return range(v)

@register.filter
def lookup(d, key):
    return d[key]

@register.filter
def member_full(member):
  if member is None:
    return '[None]'
  return mark_safe('<a href="{}">{}</a>'.format(
    member.get_absolute_url(), member.full_name))
