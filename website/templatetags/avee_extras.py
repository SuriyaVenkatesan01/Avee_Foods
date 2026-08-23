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


# Artwork already in static/img/icon/ that suits a category whose slug does not
# match a filename. Matched on substring, so "chili-poweder" and "red-chilli"
# both land on spices.png without needing an exact spelling.
CATEGORY_ICON_KEYWORDS = (
    ('chil', 'spices'),
    ('spice', 'spices'),
    ('masala', 'spices'),
    ('powder', 'spices'),
    ('oil', 'oil'),
    ('honey', 'honey'),
    ('ghee', 'ghee'),
    ('nut', 'basket'),
    ('water', 'water'),
)


@register.filter
def category_icon(category):
    """URL of a category's PNG icon, or '' when no artwork fits.

    Tried in order, first hit wins:
      1. static/img/icon/cat-<slug>.png  -- drop a file in, no code change
      2. static/img/icon/<slug>.png      -- matches the icons already shipped
      3. a keyword match from CATEGORY_ICON_KEYWORDS

    Returning '' rather than a URL lets the template fall back to the emoji
    icon field instead of rendering a broken image.

    Deliberately uncached: the lookup touches the filesystem, but caching it
    would mean a newly dropped-in PNG stays invisible until the server is
    restarted, which is a confusing way for this to fail.
    """
    slug = (getattr(category, 'slug', '') or '').lower()
    if not slug:
        return ''

    candidates = [f'cat-{slug}', slug]
    for keyword, icon in CATEGORY_ICON_KEYWORDS:
        if keyword in slug:
            candidates.append(icon)
            break

    for name in candidates:
        path = f'img/icon/{name}.png'
        if finders.find(path):
            return static(path)
    return ''
