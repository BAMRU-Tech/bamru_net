from django import template

register = template.Library()

@register.filter
def rangearray(v):
    """Generate an array, useful in for loops"""
    return range(v)
