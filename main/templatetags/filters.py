from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from main.lib.charts import hours_tenths, hours_text

register = template.Library()
register.filter('hours', hours_text)
register.filter('hours_tenths', hours_tenths)

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
def last_word_below(text):
    """Text with its last word on a line of its own: a heading two lines at most, for a narrow column."""
    rest, _, last = text.rpartition(' ')
    return format_html('{}<br>{}', rest, last) if rest else text

@register.filter
def member_full(member):
  if member is None:
    return '[None]'
  return mark_safe('<a href="{}">{}</a>'.format(
    member.get_absolute_url(), member.full_name))
