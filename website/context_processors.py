



"""Values every storefront template needs: store config, cart badge, nav menu."""

from django.conf import settings
from django.db.models import Prefetch

from . import cart as cart_service
from .models import Category, SubCategory


def storefront(request):
    # Only the public site needs this; the dashboard has its own chrome.
    if request.path.startswith('/dashboard/') or request.path.startswith('/admin/'):
        return {'store': settings.STORE}

    summary = cart_service.cart_summary(request)
    return {
        'store': settings.STORE,
        'cart': summary['cart'],
        'cart_count': summary['count'],
        'cart_subtotal': summary['subtotal'],
        # Subcategories come along for the header dropdown -- prefetched into
        # `menu_subcategories` so the menu costs two queries, not one per category
        'nav_categories': Category.objects.filter(is_active=True).prefetch_related(
            Prefetch('subcategories',
                     queryset=SubCategory.objects.filter(is_active=True),
                     to_attr='menu_subcategories'),
        ),
    }
