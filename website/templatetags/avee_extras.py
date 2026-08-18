"""Template helpers for the storefront."""

from decimal import Decimal, InvalidOperation

from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static

register = template.Library()


@register.filter
def inr(value):
    """Format a number with Indian digit grouping: 125000 -> 1,25,000.00"""
    try:
        amount = Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        return value

    negative = amount < 0
    whole, _, fraction = f'{abs(amount):.2f}'.partition('.')

    # Last three digits stay together, everything before is grouped in twos
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ','.join(parts + [tail])

    return f'{"-" if negative else ""}{whole}.{fraction}'


@register.filter
def multiply(value, factor):
    try:
        return Decimal(str(value)) * Decimal(str(factor))
    except (InvalidOperation, TypeError, ValueError):
        return ''


@register.filter
def get_item(mapping, key):
    """Look up a dict key that isn't a valid template variable name."""
    if hasattr(mapping, 'get'):
        return mapping.get(key, '')
    return ''


@register.filter
def category_icon(category):
    """URL of a category's PNG icon, or '' when no artwork has been added.

    Name the file after the category slug -- static/img/icon/cat-<slug>.png --
    and it appears on its own, no code change needed for a new category.
    Returning '' rather than a URL lets the template fall back to the emoji
    icon field instead of rendering a broken image.

    Deliberately uncached: the lookup touches the filesystem, but caching it
    would mean a newly dropped-in PNG stays invisible until the server is
    restarted, which is a confusing way for this to fail.
    """
    slug = getattr(category, 'slug', '') or ''
    if not slug:
        return ''
    path = f'img/icon/cat-{slug}.png'
    return static(path) if finders.find(path) else ''
