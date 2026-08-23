"""Sitemaps so Google can find every product, category and combo.

Only public, indexable pages belong here -- cart, checkout and anything
under /order/ or /track/ is private and is excluded from robots.txt too.
"""

from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from .models import Combo, FoodProduct


class StaticViewSitemap(Sitemap):
    changefreq = 'weekly'

    PAGES = {
        'website:home': 1.0,
        'website:food_products': 0.9,
        'website:combos': 0.7,
        'website:about': 0.5,
        'website:gallery': 0.4,
    }

    def items(self):
        return list(self.PAGES)

    def location(self, item):
        return reverse(item)

    def priority(self, item):
        return self.PAGES[item]


class ProductSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.9
    limit = 2000

    def items(self):
        return (FoodProduct.objects.filter(is_active=True)
                .order_by('-updated_at'))

    def lastmod(self, obj):
        return obj.updated_at


class ComboSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.6

    def items(self):
        return Combo.objects.filter(is_active=True).order_by('id')

    def lastmod(self, obj):
        return obj.updated_at

    def location(self, obj):
        return reverse('website:combo_detail', args=[obj.pk])


SITEMAPS = {
    'static': StaticViewSitemap,
    'products': ProductSitemap,
    'combos': ComboSitemap,
}
