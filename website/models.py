import random
import string
from decimal import Decimal

from django.conf import settings
from django.core.validators import (
    FileExtensionValidator, MinValueValidator, RegexValidator,
)
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

# ---------------------------------------------------------------------------
# Shared validators / helpers
# ---------------------------------------------------------------------------

phone_validator = RegexValidator(
    regex=r'^[6-9]\d{9}$',
    message='Enter a valid 10 digit Indian mobile number.',
)

pincode_validator = RegexValidator(
    regex=r'^\d{6}$',
    message='Enter a valid 6 digit PIN code.',
)


def unique_slug(model, value, instance=None, field='slug', fallback=''):
    
    base = slugify(value)[:180] or slugify(fallback)[:180] or 'item'
    slug = base
    counter = 2
    queryset = model.objects.all()
    if instance is not None and instance.pk:
        queryset = queryset.exclude(pk=instance.pk)
    while queryset.filter(**{field: slug}).exists():
        slug = f'{base}-{counter}'
        counter += 1
    return slug


PRODUCT_DETAILS_TEMPLATE = {
    "highlights": [
        "Cold pressed in a wooden chekku",
        "Zero preservatives, zero refining",
    ],
    "specifications": {
        "Extraction": "Wooden cold press (chekku)",
        "Shelf life": "6 months from packing",
        "Packing": "Food grade PET bottle",
    },
    "ingredients": ["100% groundnut"],
    "nutrition": {
        "basis": "Per 100 g",
        "values": {
            "Energy": "900 kcal",
            "Total Fat": "100 g",
            "Saturated Fat": "18 g",
            "Protein": "0 g",
        },
    },
    "usage": ["Everyday cooking", "Deep frying", "Seasoning"],
    "storage": "Store in a cool, dry place away from direct sunlight.",
    "certifications": ["FSSAI Licensed", "Lab tested every batch"],
    "sourcing": {
        "farmer": "Ramasamy, Thoothukudi",
        "region": "Thoothukudi, Tamil Nadu",
        "harvest": "Rain-fed groundnut, harvested Feb 2026",
    },
    "faq": [
        {
            "q": "Why does the oil look cloudy?",
            "a": "Cold pressed oil is only filtered, never refined. Sediment is natural.",
        }
    ],
}


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

class Category(models.Model):
    """A sellable product family. Add rows here to launch a new range."""

    MEASURE_VOLUME = 'volume'
    MEASURE_WEIGHT = 'weight'
    MEASURE_COUNT = 'count'
    MEASURE_CHOICES = [
        (MEASURE_VOLUME, 'Sold by volume (ml / L)'),
        (MEASURE_WEIGHT, 'Sold by weight (g / kg)'),
        (MEASURE_COUNT, 'Sold by count (piece / pack)'),
    ]

    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    icon = models.CharField(
        max_length=8, blank=True,
        help_text='A single emoji shown next to the category name, e.g. 🫒',
    )
    tagline = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to='categories/', blank=True, null=True)
    measure_type = models.CharField(
        max_length=10, choices=MEASURE_CHOICES, default=MEASURE_WEIGHT,
        help_text='Decides which pack units the variant form offers.',
    )
    display_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_order', 'name']
        verbose_name_plural = 'Categories'

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.slug = unique_slug(Category, self.slug or self.name, self, fallback=self.name)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        """The filtered listing -- the standalone category page was retired.

        Every menu, breadcrumb and pill picks this up at once, and the old
        /category/<slug>/ URL still 301s to the same place for links that
        were already out in the world.
        """
        return f"{reverse('website:food_products')}?category={self.slug}"

    @property
    def label(self):
        return f'{self.icon} {self.name}'.strip()

    @property
    def active_products(self):
        return self.products.filter(is_active=True)

    @property
    def active_subcategories(self):
        return self.subcategories.filter(is_active=True)

    @property
    def unit_choices(self):
        """Pack units that make sense for this category."""
        return {
            self.MEASURE_VOLUME: ['ml', 'l'],
            self.MEASURE_WEIGHT: ['g', 'kg'],
            self.MEASURE_COUNT: ['piece', 'pack'],
        }[self.measure_type]


class SubCategory(models.Model):
    """The middle level: Oils -> Groundnut Oil, Coconut Oil, Sesame Oil...

    Products hang off a subcategory; the pack sizes (250 ml, 1 L, 5 L) still
    live on ProductVariant below the product.
    """

    category = models.ForeignKey(
        Category, on_delete=models.CASCADE, related_name='subcategories',
    )
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, blank=True)
    image = models.ImageField(upload_to='subcategories/', blank=True, null=True)
    display_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_order', 'name']
        verbose_name_plural = 'Subcategories'
        # The slug only has to be unique inside its own category, so two
        # categories can both have a "Regular" without clashing
        unique_together = [('category', 'slug'), ('category', 'name')]

    def __str__(self):
        return f'{self.category.name} / {self.name}'

    def save(self, *args, **kwargs):
        base = (slugify(self.slug or self.name)[:130]
                or slugify(self.name)[:130] or 'item')
        slug, counter = base, 2
        siblings = SubCategory.objects.filter(category=self.category)
        if self.pk:
            siblings = siblings.exclude(pk=self.pk)
        while siblings.filter(slug=slug).exists():
            slug = f'{base}-{counter}'
            counter += 1
        self.slug = slug
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('website:subcategory_detail', args=[self.category.slug, self.slug])

    @property
    def active_products(self):
        return self.products.filter(is_active=True)


class FoodProduct(models.Model):
    """A product family. Actual prices live on its variants."""

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, related_name='products',
        null=True, blank=True,
    )
    subcategory = models.ForeignKey(
        SubCategory, on_delete=models.SET_NULL, related_name='products',
        null=True, blank=True,
        help_text='Must belong to the category chosen above.',
    )
    short_description = models.CharField(
        max_length=250, blank=True,
        help_text='One line shown on cards and search results.',
    )
    description = models.TextField(help_text='Long form description.')
    details = models.JSONField(
        default=dict, blank=True,
        help_text='Structured product copy. See PRODUCT_DETAILS_TEMPLATE.',
    )
    price = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00'),
        help_text='Fallback price. The lowest active variant price wins.',
    )
    image = models.ImageField(upload_to='products/')
    stock_managed = models.BooleanField(
        default=True, help_text='Uncheck to keep selling when stock hits zero.',
    )
    is_active = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)
    display_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_order', '-created_at']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.slug = unique_slug(
            FoodProduct, self.slug or self.name, self, fallback=self.name)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('website:product_detail', args=[self.slug])

    # -- pricing ----------------------------------------------------------
    @property
    def active_variants(self):
        return self.variants.filter(is_active=True)

    @property
    def default_variant(self):
        """Cheapest in-stock variant, else cheapest variant."""
        variants = list(self.active_variants)
        if not variants:
            return None
        in_stock = [v for v in variants if v.in_stock]
        pool = in_stock or variants
        return min(pool, key=lambda v: v.price)

    @property
    def display_price(self):
        variant = self.default_variant
        return variant.price if variant else self.price

    @property
    def price_range(self):
        prices = [v.price for v in self.active_variants]
        if not prices:
            return None
        low, high = min(prices), max(prices)
        return None if low == high else (low, high)

    @property
    def pack_labels(self):
        return [v.label for v in self.active_variants]

    @property
    def in_stock(self):
        return any(v.in_stock for v in self.active_variants)

    # -- `details` accessors used by templates ----------------------------
    @property
    def highlights(self):
        return self.details.get('highlights') or []

    @property
    def specifications(self):
        return self.details.get('specifications') or {}

    @property
    def ingredients(self):
        return self.details.get('ingredients') or []

    @property
    def nutrition(self):
        return self.details.get('nutrition') or {}

    @property
    def usage(self):
        return self.details.get('usage') or []

    @property
    def certifications(self):
        return self.details.get('certifications') or []

    @property
    def storage(self):
        return self.details.get('storage') or ''

    @property
    def sourcing(self):
        return self.details.get('sourcing') or {}

    @property
    def faq(self):
        return self.details.get('faq') or []


class ProductImage(models.Model):
    """Extra gallery shots for a product detail page."""

    product = models.ForeignKey(
        FoodProduct, on_delete=models.CASCADE, related_name='images',
    )
    image = models.ImageField(upload_to='products/')
    alt_text = models.CharField(max_length=200, blank=True)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['display_order', 'id']

    def __str__(self):
        return f'{self.product.name} image {self.pk}'


class ProductVariant(models.Model):
    """One sellable pack: 500 ml oil, 1 kg cashew, 250 g cashew powder."""

    UNIT_CHOICES = [
        ('ml', 'ml'),
        ('l', 'L'),
        ('g', 'g'),
        ('kg', 'kg'),
        ('piece', 'piece'),
        ('pack', 'pack'),
    ]
    # Everything normalised to the base unit so "1 L" and "1000 ml" sort together
    UNIT_FACTOR = {
        'ml': Decimal('1'), 'l': Decimal('1000'),
        'g': Decimal('1'), 'kg': Decimal('1000'),
        'piece': Decimal('1'), 'pack': Decimal('1'),
    }

    product = models.ForeignKey(
        FoodProduct, on_delete=models.CASCADE, related_name='variants',
    )
    pack_size = models.DecimalField(
        max_digits=8, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))],
    )
    unit = models.CharField(max_length=10, choices=UNIT_CHOICES, default='ml')
    label = models.CharField(
        max_length=60, blank=True,
        help_text='Leave blank to auto-generate, e.g. "500 ml".',
    )
    sku = models.CharField(max_length=40, unique=True, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    mrp = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text='Strike-through price. Leave blank if there is no discount.',
    )
    stock = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['display_order', 'pack_size']
        unique_together = [('product', 'pack_size', 'unit')]

    def __str__(self):
        return f'{self.product.name} - {self.label}'

    def save(self, *args, **kwargs):
        if not self.label:
            self.label = self.auto_label
        if not self.sku:
            self.sku = self.build_sku()
        super().save(*args, **kwargs)

    @staticmethod
    def format_size(value):
        """Trim trailing zeros without ever falling into 2.5E+2 notation.

        Decimal('250.00').normalize() is Decimal('2.5E+2'), which would put
        "2.5E+2 ml" on the label, so whole numbers are quantized instead.
        """
        value = Decimal(value or 0)
        if value == value.to_integral_value():
            return str(value.quantize(Decimal(1)))
        return str(value.normalize())

    @property
    def auto_label(self):
        return f'{self.format_size(self.pack_size)} {self.get_unit_display()}'

    def build_sku(self):
        prefix = ''.join(c for c in self.product.name.upper() if c.isalpha())[:4] or 'AVEE'
        suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
        size = self.format_size(self.pack_size).replace('.', '')
        return f'AF-{prefix}-{size}{self.unit.upper()}-{suffix}'

    @property
    def base_quantity(self):
        """Pack size in the base unit (ml or g) -- used for per-unit pricing."""
        return self.pack_size * self.UNIT_FACTOR[self.unit]

    @property
    def unit_rate(self):
        """Price per litre / per kg, so customers can compare packs."""
        base = self.base_quantity
        if not base or self.unit in ('piece', 'pack'):
            return None
        rate = (self.price / base) * 1000
        return rate.quantize(Decimal('0.01'))

    @property
    def unit_rate_label(self):
        return '/L' if self.unit in ('ml', 'l') else '/kg'

    @property
    def in_stock(self):
        return (not self.product.stock_managed) or self.stock > 0

    @property
    def discount_percent(self):
        if self.mrp and self.mrp > self.price:
            return int(round((self.mrp - self.price) / self.mrp * 100))
        return 0

    @property
    def savings(self):
        if self.mrp and self.mrp > self.price:
            return self.mrp - self.price
        return Decimal('0.00')


class Combo(models.Model):
    name = models.CharField(max_length=200)
    description = models.TextField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    image = models.ImageField(upload_to='combos/')
    products = models.ManyToManyField(FoodProduct, blank=True)
    discount_percent = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name


class GalleryImage(models.Model):
    title = models.CharField(max_length=200)
    image = models.ImageField(upload_to='gallery/')
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title


class HomeBanner(models.Model):
    """A photo or video shown directly under the header on the home page.

    Whatever is ticked Active appears, in display order. One item shows on its
    own; several become a slideshow -- images hold for `duration_seconds`, a
    video holds until it finishes playing.
    """

    TYPE_IMAGE = 'image'
    TYPE_VIDEO = 'video'
    TYPE_CHOICES = [
        (TYPE_IMAGE, 'Photo'),
        (TYPE_VIDEO, 'Video'),
    ]

    IMAGE_EXTENSIONS = ['jpg', 'jpeg', 'png', 'webp', 'gif', 'avif']
    VIDEO_EXTENSIONS = ['mp4', 'webm', 'ogg', 'mov', 'm4v']

    media_type = models.CharField(max_length=5, choices=TYPE_CHOICES, default=TYPE_IMAGE)
    file = models.FileField(
        upload_to='home_banner/',
        validators=[FileExtensionValidator(IMAGE_EXTENSIONS + VIDEO_EXTENSIONS)],
    )
    title = models.CharField(max_length=150, blank=True)
    subtitle = models.CharField(max_length=250, blank=True)
    button_text = models.CharField(max_length=60, blank=True)
    button_url = models.CharField(
        max_length=250, blank=True,
        help_text='Where the button goes, e.g. /products/',
    )
    duration_seconds = models.PositiveIntegerField(
        default=5,
        validators=[MinValueValidator(1)],
        help_text='Photos only — how long this slide stays on screen.',
    )
    display_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(
        default=True, help_text='Only ticked items appear on the home page.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_order', 'id']
        verbose_name = 'Home banner'
        verbose_name_plural = 'Home banners'

    def __str__(self):
        return f'{self.get_media_type_display()}: {self.title or self.file.name}'

    @property
    def is_video(self):
        return self.media_type == self.TYPE_VIDEO

    @property
    def has_overlay(self):
        return bool(self.title or self.subtitle or (self.button_text and self.button_url))

    @property
    def mime_type(self):
        """So <source type="..."> is right for mp4, webm and friends."""
        extension = self.file.name.rsplit('.', 1)[-1].lower() if '.' in self.file.name else ''
        return {
            'mp4': 'video/mp4', 'm4v': 'video/mp4', 'mov': 'video/mp4',
            'webm': 'video/webm', 'ogg': 'video/ogg',
        }.get(extension, 'video/mp4')

    @classmethod
    def live(cls):
        return cls.objects.filter(is_active=True)


# ---------------------------------------------------------------------------
# Farm -> home journey
# ---------------------------------------------------------------------------

class ProcessStage(models.Model):
    """One step of the "farmer to your kitchen" story.

    A stage with no category is global and shows on every page. Attaching a
    category (Oils, Cashews) gives that range its own journey, which then
    replaces the global one on those product pages.
    """

    title = models.CharField(max_length=120)
    subtitle = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=8, blank=True, help_text='Emoji, e.g. 🌾')
    image = models.ImageField(upload_to='process/', blank=True, null=True)
    category = models.ForeignKey(
        Category, on_delete=models.CASCADE, related_name='process_stages',
        null=True, blank=True,
        help_text='Leave empty for a stage that applies to every product.',
    )
    duration = models.CharField(
        max_length=60, blank=True, help_text='e.g. "Day 1" or "24 hours".',
    )
    display_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['display_order', 'id']

    def __str__(self):
        scope = self.category.name if self.category else 'All products'
        return f'{self.display_order}. {self.title} ({scope})'

    @classmethod
    def for_category(cls, category=None):
        """Category-specific stages when they exist, else the global journey."""
        if category is not None:
            specific = cls.objects.filter(is_active=True, category=category)
            if specific.exists():
                return specific
        return cls.objects.filter(is_active=True, category__isnull=True)


# ---------------------------------------------------------------------------
# Cart
# ---------------------------------------------------------------------------

class Cart(models.Model):
    session_key = models.CharField(max_length=60, db_index=True, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='carts',
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'Cart #{self.pk} ({self.total_quantity} items)'

    @property
    def line_items(self):
        return self.items.select_related('variant__product__category')

    @property
    def total_quantity(self):
        return sum(item.quantity for item in self.items.all())

    @property
    def subtotal(self):
        return sum((item.line_total for item in self.line_items), Decimal('0.00'))

    @property
    def total_savings(self):
        return sum(
            (item.variant.savings * item.quantity for item in self.line_items),
            Decimal('0.00'),
        )

    @property
    def shipping_fee(self):
        cfg = settings.STORE
        if self.subtotal >= cfg['free_shipping_above'] or self.subtotal <= 0:
            return Decimal('0.00')
        return cfg['shipping_fee']

    @property
    def amount_for_free_shipping(self):
        remaining = settings.STORE['free_shipping_above'] - self.subtotal
        return remaining if remaining > 0 else Decimal('0.00')

    @property
    def total(self):
        return self.subtotal + self.shipping_fee

    @property
    def has_out_of_stock(self):
        return any(not item.is_available for item in self.line_items)


class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name='items')
    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['added_at']
        unique_together = [('cart', 'variant')]

    def __str__(self):
        return f'{self.quantity} x {self.variant}'

    @property
    def line_total(self):
        return self.variant.price * self.quantity

    @property
    def is_available(self):
        variant = self.variant
        if not variant.is_active or not variant.product.is_active:
            return False
        if variant.product.stock_managed:
            return variant.stock >= self.quantity
        return True


# ---------------------------------------------------------------------------
# Orders, payment and tracking
# ---------------------------------------------------------------------------

class Order(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_CONFIRMED = 'confirmed'
    STATUS_PACKED = 'packed'
    STATUS_SHIPPED = 'shipped'
    STATUS_OUT_FOR_DELIVERY = 'out_for_delivery'
    STATUS_DELIVERED = 'delivered'
    STATUS_CANCELLED = 'cancelled'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Order Placed'),
        (STATUS_CONFIRMED, 'Confirmed'),
        (STATUS_PACKED, 'Packed'),
        (STATUS_SHIPPED, 'Shipped'),
        (STATUS_OUT_FOR_DELIVERY, 'Out for Delivery'),
        (STATUS_DELIVERED, 'Delivered'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]
    # The happy path, in order -- drives the tracking progress bar.
    STATUS_FLOW = [
        STATUS_PENDING, STATUS_CONFIRMED, STATUS_PACKED,
        STATUS_SHIPPED, STATUS_OUT_FOR_DELIVERY, STATUS_DELIVERED,
    ]
    STATUS_ICONS = {
        STATUS_PENDING: '📝',
        STATUS_CONFIRMED: '✅',
        STATUS_PACKED: '📦',
        STATUS_SHIPPED: '🚚',
        STATUS_OUT_FOR_DELIVERY: '🛵',
        STATUS_DELIVERED: '🏠',
        STATUS_CANCELLED: '❌',
    }

    PAYMENT_COD = 'cod'
    PAYMENT_UPI = 'upi'
    PAYMENT_METHOD_CHOICES = [
        (PAYMENT_COD, 'Cash on Delivery'),
        (PAYMENT_UPI, 'UPI / GPay / PhonePe'),
    ]

    PAY_PENDING = 'pending'
    PAY_AWAITING = 'awaiting_verification'
    PAY_PAID = 'paid'
    PAY_FAILED = 'failed'
    PAY_REFUNDED = 'refunded'
    PAYMENT_STATUS_CHOICES = [
        (PAY_PENDING, 'Pending'),
        (PAY_AWAITING, 'Awaiting Verification'),
        (PAY_PAID, 'Paid'),
        (PAY_FAILED, 'Failed'),
        (PAY_REFUNDED, 'Refunded'),
    ]

    order_number = models.CharField(max_length=20, unique=True, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='orders',
    )
    session_key = models.CharField(max_length=60, blank=True, db_index=True)

    # -- customer ---------------------------------------------------------
    full_name = models.CharField(max_length=120)
    phone = models.CharField(max_length=10, validators=[phone_validator])
    alt_phone = models.CharField(max_length=10, blank=True, validators=[phone_validator])
    email = models.EmailField(blank=True)

    # -- delivery address -------------------------------------------------
    address_line1 = models.CharField('House / Flat / Street', max_length=200)
    address_line2 = models.CharField('Area / Locality', max_length=200, blank=True)
    landmark = models.CharField(max_length=150, blank=True)
    city = models.CharField('City / Town / Village', max_length=100)
    district = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, default='Tamil Nadu')
    pincode = models.CharField(max_length=6, validators=[pincode_validator])
    delivery_notes = models.TextField(blank=True)

    # -- money ------------------------------------------------------------
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    shipping_fee = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    total = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))

    # -- payment ----------------------------------------------------------
    payment_method = models.CharField(
        max_length=10, choices=PAYMENT_METHOD_CHOICES, default=PAYMENT_UPI,
    )
    payment_status = models.CharField(
        max_length=25, choices=PAYMENT_STATUS_CHOICES, default=PAY_PENDING,
    )
    payment_reference = models.CharField(
        max_length=80, blank=True, help_text='UPI transaction / UTR number.',
    )
    paid_at = models.DateTimeField(null=True, blank=True)

    # -- fulfilment / tracking -------------------------------------------
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    courier_name = models.CharField(max_length=100, blank=True)
    tracking_number = models.CharField(max_length=80, blank=True)
    tracking_url = models.URLField(blank=True)
    expected_delivery = models.DateField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    cancelled_reason = models.CharField(max_length=250, blank=True)
    internal_notes = models.TextField(blank=True)

    placed_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-placed_at']

    def __str__(self):
        return f'{self.order_number} - {self.full_name}'

    def save(self, *args, **kwargs):
        if not self.order_number:
            self.order_number = self.generate_order_number()
        super().save(*args, **kwargs)

    ORDER_ID_LENGTH = 6
    ORDER_ID_ALPHABET = string.ascii_uppercase + string.digits

    @staticmethod
    def generate_order_number():
        """A short random code the customer can read out, e.g. AX3QE1.

        Random rather than sequential so the code gives nothing away about how
        many orders the store has taken, and short enough to type on a phone.
        """
        while True:
            number = ''.join(random.choices(
                Order.ORDER_ID_ALPHABET, k=Order.ORDER_ID_LENGTH))
            if not Order.objects.filter(order_number=number).exists():
                return number

    def get_absolute_url(self):
        return reverse('website:order_detail', args=[self.order_number])

    # -- tracking helpers -------------------------------------------------
    @property
    def is_cancelled(self):
        return self.status == self.STATUS_CANCELLED

    @property
    def status_icon(self):
        return self.STATUS_ICONS.get(self.status, '📦')

    @property
    def status_index(self):
        try:
            return self.STATUS_FLOW.index(self.status)
        except ValueError:
            return -1

    @property
    def progress_percent(self):
        if self.is_cancelled:
            return 100
        idx = self.status_index
        if idx < 0:
            return 0
        return int(idx / (len(self.STATUS_FLOW) - 1) * 100)

    @property
    def timeline(self):
        """Every step of the flow with a done/current/pending marker."""
        current = self.status_index
        steps = []
        events = {e.status: e for e in self.events.all()}
        for i, status in enumerate(self.STATUS_FLOW):
            event = events.get(status)
            steps.append({
                'status': status,
                'label': dict(self.STATUS_CHOICES)[status],
                'icon': self.STATUS_ICONS[status],
                'done': current >= i and not self.is_cancelled,
                'current': current == i and not self.is_cancelled,
                'at': event.created_at if event else None,
                'note': event.note if event else '',
            })
        return steps

    @property
    def can_cancel(self):
        return self.status in (self.STATUS_PENDING, self.STATUS_CONFIRMED)

    @property
    def total_quantity(self):
        return sum(item.quantity for item in self.items.all())

    @property
    def is_paid(self):
        return self.payment_status == self.PAY_PAID

    def log_event(self, status, note='', location='', user=None):
        """Record a tracking event and move the order to that status."""
        self.status = status
        if status == self.STATUS_DELIVERED:
            self.delivered_at = timezone.now()
            if self.payment_method == self.PAYMENT_COD:
                self.payment_status = self.PAY_PAID
                self.paid_at = timezone.now()
        self.save()
        return OrderEvent.objects.create(
            order=self, status=status, note=note, location=location,
            created_by=user if user and user.is_authenticated else None,
        )


class OrderItem(models.Model):
    """A frozen snapshot -- prices and names must not change after checkout."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    variant = models.ForeignKey(
        ProductVariant, on_delete=models.SET_NULL, null=True, blank=True,
    )
    product = models.ForeignKey(
        FoodProduct, on_delete=models.SET_NULL, null=True, blank=True,
    )
    product_name = models.CharField(max_length=200)
    variant_label = models.CharField(max_length=60)
    sku = models.CharField(max_length=40, blank=True)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField(default=1)
    line_total = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f'{self.quantity} x {self.product_name} ({self.variant_label})'

    @property
    def image_url(self):
        if self.product and self.product.image:
            return self.product.image.url
        return ''


class OrderEvent(models.Model):
    """Tracking timeline entry shown to the customer."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='events')
    status = models.CharField(max_length=20, choices=Order.STATUS_CHOICES)
    note = models.CharField(max_length=250, blank=True)
    location = models.CharField(max_length=120, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'{self.order.order_number}: {self.get_status_display()}'

    @property
    def icon(self):
        return Order.STATUS_ICONS.get(self.status, '📦')


class Payment(models.Model):
    """Every payment attempt against an order.

    UPI is collected manually: the customer pays to the store VPA and submits
    the UTR, which the dashboard verifies. Swapping in a gateway later means
    filling `gateway_payment_id` from the webhook and calling `mark_paid()`.
    """

    STATUS_INITIATED = 'initiated'
    STATUS_SUBMITTED = 'submitted'
    STATUS_VERIFIED = 'verified'
    STATUS_REJECTED = 'rejected'
    STATUS_CHOICES = [
        (STATUS_INITIATED, 'Initiated'),
        (STATUS_SUBMITTED, 'Submitted by customer'),
        (STATUS_VERIFIED, 'Verified'),
        (STATUS_REJECTED, 'Rejected'),
    ]

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='payments')
    method = models.CharField(max_length=10, choices=Order.PAYMENT_METHOD_CHOICES)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    reference = models.CharField(
        max_length=80, blank=True, help_text='UPI UTR / transaction id.',
    )
    payer_upi = models.CharField(max_length=80, blank=True)
    screenshot = models.ImageField(upload_to='payments/', blank=True, null=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_INITIATED)
    gateway_payment_id = models.CharField(max_length=120, blank=True)
    note = models.CharField(max_length=250, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.order.order_number} - ₹{self.amount} ({self.get_status_display()})'

    def mark_paid(self, user=None):
        self.status = self.STATUS_VERIFIED
        self.verified_at = timezone.now()
        self.verified_by = user if user and user.is_authenticated else None
        self.save()
        order = self.order
        order.payment_status = Order.PAY_PAID
        order.paid_at = self.verified_at
        order.payment_reference = self.reference or order.payment_reference
        order.save()
