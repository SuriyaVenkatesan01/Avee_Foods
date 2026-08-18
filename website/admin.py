from django.contrib import admin
from django.utils.html import format_html

from .models import (
    Cart, CartItem, Category, Combo, FoodProduct, GalleryImage, HomeBanner,
    Order, OrderEvent, OrderItem, Payment, ProcessStage, ProductImage,
    ProductVariant, SubCategory,
)


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 1
    fields = ('pack_size', 'unit', 'label', 'price', 'mrp', 'stock', 'sku', 'is_active', 'display_order')
    readonly_fields = ('sku',)


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('label', 'slug', 'measure_type', 'product_count', 'display_order', 'is_active')
    list_filter = ('measure_type', 'is_active')
    list_editable = ('display_order', 'is_active')
    search_fields = ('name', 'description')
    prepopulated_fields = {'slug': ('name',)}

    @admin.display(description='Products')
    def product_count(self, obj):
        return obj.products.count()


@admin.register(SubCategory)
class SubCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'product_count', 'display_order', 'is_active')
    list_filter = ('category', 'is_active')
    list_editable = ('display_order', 'is_active')
    search_fields = ('name', 'category__name')

    @admin.display(description='Products')
    def product_count(self, obj):
        return obj.products.count()


@admin.register(FoodProduct)
class FoodProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'subcategory', 'variant_count', 'display_price',
                    'is_active', 'is_featured')
    list_filter = ('category', 'subcategory', 'is_active', 'is_featured', 'created_at')
    list_editable = ('is_active', 'is_featured')
    search_fields = ('name', 'description', 'short_description')
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ('created_at', 'updated_at')
    inlines = [ProductVariantInline, ProductImageInline]

    @admin.display(description='Packs')
    def variant_count(self, obj):
        return obj.variants.count()


@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    list_display = ('sku', 'product', 'label', 'price', 'mrp', 'stock', 'is_active')
    list_filter = ('unit', 'is_active', 'product__category')
    list_editable = ('price', 'stock', 'is_active')
    search_fields = ('sku', 'product__name', 'label')


@admin.register(ProcessStage)
class ProcessStageAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'duration', 'display_order', 'is_active')
    list_filter = ('category', 'is_active')
    list_editable = ('display_order', 'is_active')
    search_fields = ('title', 'description')


@admin.register(Combo)
class ComboAdmin(admin.ModelAdmin):
    list_display = ('name', 'price', 'discount_percent', 'is_active', 'created_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('name', 'description')
    readonly_fields = ('created_at', 'updated_at')
    filter_horizontal = ('products',)


@admin.register(HomeBanner)
class HomeBannerAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'media_type', 'duration_seconds', 'display_order', 'is_active')
    list_filter = ('media_type', 'is_active')
    list_editable = ('display_order', 'is_active')
    search_fields = ('title', 'subtitle')


@admin.register(GalleryImage)
class GalleryImageAdmin(admin.ModelAdmin):
    list_display = ('title', 'created_at')
    search_fields = ('title', 'description')
    readonly_fields = ('created_at',)


class CartItemInline(admin.TabularInline):
    model = CartItem
    extra = 0


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'session_key', 'total_quantity', 'subtotal', 'updated_at')
    inlines = [CartItemInline]


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ('product_name', 'variant_label', 'sku', 'unit_price', 'quantity', 'line_total')
    can_delete = False


class OrderEventInline(admin.TabularInline):
    model = OrderEvent
    extra = 0
    readonly_fields = ('created_at',)


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    readonly_fields = ('created_at',)


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        'order_number', 'full_name', 'phone', 'total',
        'payment_method', 'payment_badge', 'status', 'placed_at',
    )
    list_filter = ('status', 'payment_status', 'payment_method', 'placed_at', 'state')
    search_fields = ('order_number', 'full_name', 'phone', 'email', 'pincode', 'tracking_number')
    readonly_fields = ('order_number', 'placed_at', 'updated_at', 'subtotal', 'shipping_fee', 'total')
    date_hierarchy = 'placed_at'
    inlines = [OrderItemInline, PaymentInline, OrderEventInline]
    fieldsets = (
        ('Order', {'fields': ('order_number', 'status', 'user', 'placed_at', 'updated_at')}),
        ('Customer', {'fields': ('full_name', 'phone', 'alt_phone', 'email')}),
        ('Delivery address', {
            'fields': ('address_line1', 'address_line2', 'landmark', 'city',
                       'district', 'state', 'pincode', 'delivery_notes'),
        }),
        ('Amounts', {'fields': ('subtotal', 'shipping_fee', 'discount', 'total')}),
        ('Payment', {'fields': ('payment_method', 'payment_status', 'payment_reference', 'paid_at')}),
        ('Shipment tracking', {
            'fields': ('courier_name', 'tracking_number', 'tracking_url',
                       'expected_delivery', 'delivered_at'),
        }),
        ('Internal', {'fields': ('cancelled_reason', 'internal_notes')}),
    )

    @admin.display(description='Payment')
    def payment_badge(self, obj):
        colors = {
            Order.PAY_PAID: '#27ae60',
            Order.PAY_AWAITING: '#f39c12',
            Order.PAY_PENDING: '#7f8c8d',
            Order.PAY_FAILED: '#e74c3c',
            Order.PAY_REFUNDED: '#8e44ad',
        }
        return format_html(
            '<b style="color:{}">{}</b>',
            colors.get(obj.payment_status, '#333'), obj.get_payment_status_display(),
        )


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('order', 'method', 'amount', 'reference', 'status', 'created_at', 'verified_at')
    list_filter = ('status', 'method', 'created_at')
    search_fields = ('order__order_number', 'reference', 'payer_upi')
