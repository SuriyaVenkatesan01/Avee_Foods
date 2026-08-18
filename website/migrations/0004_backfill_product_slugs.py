"""Fill in slugs for products that existed before the slug field was added.

This only repairs existing rows -- it creates no categories, variants or
process stages. All catalog content is entered manually from the dashboard.
"""

from django.db import migrations
from django.utils.text import slugify


def backfill_slugs(apps, schema_editor):
    FoodProduct = apps.get_model('website', 'FoodProduct')
    for product in FoodProduct.objects.filter(slug=''):
        base = slugify(product.name) or f'product-{product.pk}'
        slug, counter = base, 2
        while FoodProduct.objects.filter(slug=slug).exclude(pk=product.pk).exists():
            slug = f'{base}-{counter}'
            counter += 1
        product.slug = slug
        product.save(update_fields=['slug'])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('website', '0003_foodproduct_category'),
    ]

    operations = [
        migrations.RunPython(backfill_slugs, noop),
    ]
