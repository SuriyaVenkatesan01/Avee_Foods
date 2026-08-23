import re
from datetime import datetime, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Min, Prefetch, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import cart as cart_service
from .models import (
    CartItem, Category, Combo, FoodProduct, GalleryImage, HomeBanner, Order,
    Payment, ProcessStage, ProductVariant, SubCategory,
)
from .utils import (
    build_order_from_cart, generate_otp, hash_otp, mask_email, owns_order,
    reduce_stock, remember_order, restore_stock, send_order_confirmation,
    send_tracking_otp, upi_payment_uri, upi_qr_svg,
)

INDIAN_STATES = [
    'Andhra Pradesh', 'Arunachal Pradesh', 'Assam', 'Bihar', 'Chhattisgarh',
    'Delhi', 'Goa', 'Gujarat', 'Haryana', 'Himachal Pradesh', 'Jharkhand',
    'Karnataka', 'Kerala', 'Madhya Pradesh', 'Maharashtra', 'Manipur',
    'Meghalaya', 'Mizoram', 'Nagaland', 'Odisha', 'Puducherry', 'Punjab',
    'Rajasthan', 'Sikkim', 'Tamil Nadu', 'Telangana', 'Tripura',
    'Uttar Pradesh', 'Uttarakhand', 'West Bengal',
]

PHONE_RE = re.compile(r'^[6-9]\d{9}$')
PINCODE_RE = re.compile(r'^\d{6}$')
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$')


def _product_queryset():
    """Products with everything the cards and detail pages read, in one query."""
    return (
        FoodProduct.objects.filter(is_active=True)
        .select_related('category', 'subcategory')
        .prefetch_related(
            Prefetch('variants', queryset=ProductVariant.objects.filter(is_active=True)),
        )
    )


def _category_queryset():
    """Active categories with their active subcategories, for menus and pills."""
    return (
        Category.objects.filter(is_active=True)
        .prefetch_related(
            Prefetch('subcategories',
                     queryset=SubCategory.objects.filter(is_active=True),
                     to_attr='menu_subcategories'),
        )
        .annotate(product_count=Count('products', filter=Q(products__is_active=True)))
    )


def _normalise_phone(raw):
    """Strip spaces, +91 and other separators down to the last 10 digits."""
    digits = re.sub(r'\D', '', raw or '')
    return digits[-10:] if len(digits) > 10 else digits


def _payment_methods():
    """Payment options currently switched on in settings.STORE.

    Cash on Delivery was withdrawn -- every order is prepaid. Order.PAYMENT_COD
    stays on the model so historical COD orders still render.
    """
    cfg = settings.STORE
    methods = []
    if cfg.get('upi_enabled', True):
        methods.append({
            'value': Order.PAYMENT_UPI,
            'label': 'UPI / GPay / PhonePe',
            'hint': 'Pay now from any UPI app. We confirm your order once the payment is verified.',
        })
    return methods


def _validate_checkout(post, cart_total):
    """Clean the checkout POST. Returns (data, errors) -- both plain dicts."""
    data = {
        'full_name': (post.get('full_name') or '').strip(),
        'phone': _normalise_phone(post.get('phone')),
        'email': (post.get('email') or '').strip(),
        'address_line1': (post.get('address_line1') or '').strip(),
        'address_line2': (post.get('address_line2') or '').strip(),
        'city': (post.get('city') or '').strip(),
        'district': (post.get('district') or '').strip(),
        'state': (post.get('state') or '').strip(),
        'pincode': (post.get('pincode') or '').strip(),
        'payment_method': (post.get('payment_method') or '').strip(),
    }
    errors = {}

    if len(data['full_name']) < 3:
        errors['full_name'] = 'Please enter the full name of the person receiving the order.'

    if not PHONE_RE.match(data['phone']):
        errors['phone'] = 'Enter a valid 10 digit Indian mobile number.'

    if not data['email']:
        errors['email'] = (
            'Enter your email address -- your order confirmation and tracking '
            'code are sent there.')
    elif not EMAIL_RE.match(data['email']):
        errors['email'] = 'Enter a valid email address.'

    if len(data['address_line1']) < 5:
        errors['address_line1'] = 'Enter the house / flat number and street.'

    if not data['city']:
        errors['city'] = 'Enter your city, town or village.'

    if data['state'] not in INDIAN_STATES:
        errors['state'] = 'Please select your state.'

    if not PINCODE_RE.match(data['pincode']):
        errors['pincode'] = 'Enter a valid 6 digit PIN code.'

    allowed = [method['value'] for method in _payment_methods()]
    if data['payment_method'] not in allowed:
        errors['payment_method'] = 'Please choose a payment method.'

    return data, errors


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

def home(request):
    products = _product_queryset()
    context = {
        'banners': list(HomeBanner.live()),
        'home_products': products,
        'featured_combos': Combo.objects.filter(is_active=True)[:3],
        'categories': _category_queryset(),
        'process_stages': ProcessStage.for_category(),
        'gallery_images': GalleryImage.objects.all()[:6],
    }
    return render(request, 'website/home.html', context)


def food_products(request):
    """Product listing filtered by category, subcategory, search and pack size."""
    products = _product_queryset()

    category_slug = request.GET.get('category') or ''
    category = None
    if category_slug:
        category = Category.objects.filter(slug=category_slug, is_active=True).first()
        if category:
            products = products.filter(category=category)

    # Subcategories only mean anything inside a category, so the pills below the
    # category row come from the selected category alone
    subcategory_slug = request.GET.get('subcategory') or ''
    subcategory = None
    subcategories = SubCategory.objects.none()
    if category:
        subcategories = category.subcategories.filter(is_active=True).annotate(
            product_count=Count('products', filter=Q(products__is_active=True)),
        )
        if subcategory_slug:
            subcategory = subcategories.filter(slug=subcategory_slug).first()
            if subcategory:
                products = products.filter(subcategory=subcategory)

    query = (request.GET.get('q') or '').strip()
    if query:
        products = products.filter(
            Q(name__icontains=query)
            | Q(short_description__icontains=query)
            | Q(description__icontains=query)
            | Q(category__name__icontains=query)
        )

    pack = (request.GET.get('pack') or '').strip()
    if pack:
        products = products.filter(variants__label__iexact=pack, variants__is_active=True)

    sort = request.GET.get('sort') or ''
    products = products.annotate(low_price=Min('variants__price'))
    if sort == 'price_low':
        products = products.order_by('low_price')
    elif sort == 'price_high':
        products = products.order_by('-low_price')
    elif sort == 'name':
        products = products.order_by('name')
    else:
        products = products.order_by('display_order', '-created_at')

    products = products.distinct()

    # Pack sizes actually on sale, so the filter never offers a dead option
    pack_labels = list(
        ProductVariant.objects.filter(is_active=True, product__is_active=True)
        .order_by('pack_size').values_list('label', flat=True).distinct()
    )

    context = {
        'products': products,
        'categories': _category_queryset(),
        'selected_category': category_slug,
        'category': category,
        'subcategories': subcategories,
        'selected_subcategory': subcategory_slug,
        'subcategory': subcategory,
        'query': query,
        'sort': sort,
        'pack_labels': pack_labels,
        'selected_pack': pack,
        'process_stages': ProcessStage.for_category(category),
    }
    return render(request, 'website/food_products.html', context)


def category_detail(request, slug):
    """The standalone category page is gone -- send it to the filtered listing.

    The URL is kept as a permanent redirect rather than deleted: the header
    menu, breadcrumbs, older links and anything already indexed still point
    here, and a 301 lands all of them on the same products, filtered.
    """
    category = get_object_or_404(Category, slug=slug, is_active=True)
    url = f"{reverse('website:food_products')}?category={category.slug}"
    return redirect(url, permanent=True)


def subcategory_detail(request, category_slug, slug):
    subcategory = get_object_or_404(
        SubCategory.objects.select_related('category'),
        slug=slug, category__slug=category_slug,
        is_active=True, category__is_active=True,
    )
    category = subcategory.category
    context = {
        'subcategory': subcategory,
        'category': category,
        'siblings': category.subcategories.filter(is_active=True),
        'products': _product_queryset().filter(subcategory=subcategory),
        'process_stages': ProcessStage.for_category(category),
    }
    return render(request, 'website/subcategory_detail.html', context)


def product_detail(request, slug):
    product = get_object_or_404(
        _product_queryset().prefetch_related('images'), slug=slug,
    )
    related = _product_queryset().filter(category=product.category).exclude(pk=product.pk)[:4]
    context = {
        'product': product,
        'variants': product.active_variants,
        'selected_variant': product.default_variant,
        'related_products': related,
        'process_stages': ProcessStage.for_category(product.category),
    }
    return render(request, 'website/product_detail.html', context)


def product_detail_by_pk(request, pk):
    """Keeps old /products/<pk>/ links working."""
    product = get_object_or_404(FoodProduct, pk=pk)
    return redirect('website:product_detail', slug=product.slug, permanent=True)


def combos(request):
    return render(request, 'website/combos.html', {
        'combos': Combo.objects.filter(is_active=True).prefetch_related('products'),
    })


def combo_detail(request, pk):
    combo = get_object_or_404(Combo, pk=pk)
    return render(request, 'website/combo_detail.html', {
        'combo': combo,
        'combo_products': combo.products.filter(is_active=True).prefetch_related('variants'),
    })


def gallery(request):
    return render(request, 'website/gallery.html', {
        'gallery_images': GalleryImage.objects.all(),
    })


def about(request):
    return render(request, 'website/about.html', {
        'process_stages': ProcessStage.for_category(),
        'categories': Category.objects.filter(is_active=True),
    })


# ---------------------------------------------------------------------------
# Cart
# ---------------------------------------------------------------------------

def cart_detail(request):
    return render(request, 'website/cart.html', {
        'cart_obj': cart_service.get_cart(request),
    })


@require_POST
def cart_add(request):
    variant = get_object_or_404(
        ProductVariant.objects.select_related('product'),
        pk=request.POST.get('variant'), is_active=True, product__is_active=True,
    )

    try:
        quantity = int(request.POST.get('quantity', 1))
    except (TypeError, ValueError):
        quantity = 1

    if not variant.in_stock:
        messages.error(request, f'{variant.product.name} ({variant.label}) is out of stock.')
        return redirect(request.POST.get('next') or variant.product.get_absolute_url())

    item, capped = cart_service.add_item(request, variant, max(1, quantity))
    if capped:
        messages.warning(
            request,
            f'Only {item.quantity} left of {variant.product.name} ({variant.label}) — '
            'we added what we have.',
        )
    else:
        messages.success(
            request, f'{variant.product.name} ({variant.label}) added to your cart.')

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        summary = cart_service.cart_summary(request)
        return JsonResponse({'count': summary['count'], 'subtotal': str(summary['subtotal'])})

    if request.POST.get('buy_now'):
        return redirect('website:checkout')
    return redirect(request.POST.get('next') or 'website:cart_detail')


@require_POST
def cart_update(request, pk):
    cart = cart_service.get_cart(request)
    item = get_object_or_404(CartItem, pk=pk, cart=cart)
    try:
        quantity = int(request.POST.get('quantity', 1))
    except (TypeError, ValueError):
        quantity = 1

    if cart_service.set_quantity(request, item, quantity) is None:
        messages.info(request, 'Item removed from your cart.')
    return redirect('website:cart_detail')


@require_POST
def cart_remove(request, pk):
    cart = cart_service.get_cart(request)
    item = get_object_or_404(CartItem, pk=pk, cart=cart)
    cart_service.remove_item(item)
    messages.info(request, 'Item removed from your cart.')
    return redirect('website:cart_detail')


@require_POST
def combo_add_to_cart(request, pk):
    """Drop the cheapest pack of every product in the combo into the cart."""
    combo = get_object_or_404(Combo, pk=pk, is_active=True)
    added = 0
    for product in combo.products.filter(is_active=True):
        variant = product.default_variant
        if variant and variant.in_stock:
            cart_service.add_item(request, variant, 1)
            added += 1

    if added:
        messages.success(request, f'{added} item(s) from "{combo.name}" added to your cart.')
    else:
        messages.error(request, 'Sorry, the items in this combo are out of stock.')
    return redirect('website:cart_detail')


# ---------------------------------------------------------------------------
# Checkout, payment, tracking
# ---------------------------------------------------------------------------

def checkout(request):
    cart = cart_service.get_cart(request)
    if cart is None or not cart.items.exists():
        messages.info(request, 'Your cart is empty. Add something tasty first!')
        return redirect('website:food_products')

    if cart.has_out_of_stock:
        messages.error(
            request, 'Some items in your cart went out of stock. Please review your cart.')
        return redirect('website:cart_detail')

    methods = _payment_methods()
    errors = {}

    if request.method == 'POST':
        data, errors = _validate_checkout(request.POST, cart.total)

        if not errors:
            with transaction.atomic():
                order = Order(**data)
                order.user = request.user if request.user.is_authenticated else None
                order.session_key = request.session.session_key or ''
                order.save()

                build_order_from_cart(order, cart)
                reduce_stock(order)
                order.log_event(
                    Order.STATUS_PENDING,
                    note='Order received. We will confirm it shortly.',
                )

                if order.payment_method == Order.PAYMENT_UPI:
                    Payment.objects.create(
                        order=order, method=Order.PAYMENT_UPI, amount=order.total,
                    )

                cart_service.clear(cart)
                cart.is_active = False
                cart.save(update_fields=['is_active'])
                cart_service.release(request)
                remember_order(request, order)

            # After the transaction commits -- a slow mail server must not hold
            # the row locks, and a failed send must not roll the order back.
            send_order_confirmation(order)

            if order.payment_method == Order.PAYMENT_UPI:
                return redirect('website:payment', order_number=order.order_number)
            return redirect('website:order_success', order_number=order.order_number)

        messages.error(request, 'Please correct the highlighted fields.')
    else:
        # Prefill from the customer's last order so repeat buying is one tap
        data = {'state': 'Tamil Nadu', 'payment_method': methods[0]['value'] if methods else ''}
        if request.user.is_authenticated:
            last = Order.objects.filter(user=request.user).first()
            if last:
                data.update({
                    'full_name': last.full_name, 'phone': last.phone, 'email': last.email,
                    'address_line1': last.address_line1, 'address_line2': last.address_line2,
                    'city': last.city, 'district': last.district,
                    'state': last.state, 'pincode': last.pincode,
                })
            else:
                data.update({
                    'full_name': request.user.get_full_name(),
                    'email': request.user.email,
                })

    return render(request, 'website/checkout.html', {
        'cart_obj': cart,
        'data': data,
        'errors': errors,
        'states': INDIAN_STATES,
        'payment_methods': methods,
    })


def payment(request, order_number):
    order = get_object_or_404(Order, order_number=order_number)
    if not owns_order(request, order):
        return redirect('website:track_order')

    if order.is_paid:
        return redirect('website:order_success', order_number=order.order_number)

    record = order.payments.filter(
        status__in=[Payment.STATUS_INITIATED, Payment.STATUS_REJECTED]).first()
    if record is None:
        record = Payment.objects.create(
            order=order, method=order.payment_method, amount=order.total)

    data, errors = {'reference': '', 'payer_upi': ''}, {}

    if request.method == 'POST':
        data = {
            'reference': (request.POST.get('reference') or '').strip(),
            'payer_upi': (request.POST.get('payer_upi') or '').strip(),
        }

        if len(data['reference']) < 6:
            errors['reference'] = (
                'Enter the full transaction / UTR number from your payment app.')

        if not errors:
            record.reference = data['reference']
            record.payer_upi = data['payer_upi']
            record.amount = order.total
            record.method = order.payment_method
            record.status = Payment.STATUS_SUBMITTED
            if request.FILES.get('screenshot'):
                record.screenshot = request.FILES['screenshot']
            record.save()

            order.payment_status = Order.PAY_AWAITING
            order.payment_reference = record.reference
            order.save(update_fields=['payment_status', 'payment_reference'])
            order.log_event(
                order.status,
                note=f'Payment reference {record.reference} submitted, awaiting verification.',
            )
            messages.success(
                request, 'Payment details received. We will verify and confirm shortly.')
            return redirect('website:order_success', order_number=order.order_number)

        messages.error(request, 'Please check the transaction details.')

    upi_uri = upi_payment_uri(order)
    return render(request, 'website/payment.html', {
        'order': order,
        'data': data,
        'errors': errors,
        'upi_uri': upi_uri,
        'upi_qr': upi_qr_svg(upi_uri),
        'upi_id': settings.STORE['upi_id'],
        'upi_payee': settings.STORE['upi_payee'],
    })


def order_success(request, order_number):
    order = get_object_or_404(
        Order.objects.prefetch_related('items'), order_number=order_number)
    if not owns_order(request, order):
        return redirect('website:track_order')
    return render(request, 'website/order_success.html', {'order': order})


def order_detail(request, order_number):
    """Full tracking page. Guests confirm the phone number once per browser."""
    order = get_object_or_404(
        Order.objects.prefetch_related('items', 'events', 'payments'),
        order_number=order_number,
    )

    if not owns_order(request, order):
        if request.method == 'POST':
            if _normalise_phone(request.POST.get('phone')) == order.phone:
                remember_order(request, order)
                return redirect('website:order_detail', order_number=order.order_number)
            messages.error(request, 'That mobile number does not match this order.')
        return render(request, 'website/order_verify.html', {'order_number': order_number})

    return render(request, 'website/order_detail.html', {
        'order': order,
        'process_stages': ProcessStage.for_category(),
    })


ORDER_ID_RE = re.compile(r'^[A-Z0-9]{6}$')

OTP_SESSION_KEY = 'track_otp'


def _find_orders(lookup):
    """Orders matching either a 6 character order ID or a 10 digit mobile."""
    if PHONE_RE.match(lookup):
        return list(Order.objects.filter(phone=lookup).prefetch_related('items'))
    if ORDER_ID_RE.match(lookup):
        return list(Order.objects.filter(order_number=lookup).prefetch_related('items'))
    return []


def track_order(request):
    """Step one: look the orders up and email a code to the address on them."""
    data, errors = {'lookup': ''}, {}

    if request.method == 'POST':
        raw = (request.POST.get('lookup') or '').strip()
        data['lookup'] = raw

        # An order ID may be typed in lower case and can start with a digit, so
        # length is what separates the two: 10+ digits can only be a mobile,
        # anything else is treated as a 6 character order ID.
        cleaned = re.sub(r'[\s\-()]', '', raw).upper()
        digits = re.sub(r'\D', '', cleaned)
        lookup = _normalise_phone(digits) if len(digits) >= 10 else cleaned

        if not raw:
            errors['lookup'] = 'Enter your order ID or the mobile number you ordered with.'
        elif not (PHONE_RE.match(lookup) or ORDER_ID_RE.match(lookup)):
            errors['lookup'] = (
                'Enter a 6 character order ID (like AX3QE1) or your 10 digit mobile number.')

        if not errors:
            orders = _find_orders(lookup)
            if not orders:
                messages.error(
                    request, 'No orders found for that order ID or mobile number.')
            else:
                emails = [o.email for o in orders if o.email]
                if not emails:
                    # Older orders placed before email became compulsory
                    return redirect(
                        'website:order_detail', order_number=orders[0].order_number)

                code = generate_otp()
                request.session[OTP_SESSION_KEY] = {
                    'hash': hash_otp(code),
                    'email': emails[0],
                    'orders': [o.order_number for o in orders],
                    'expires': (timezone.now() + timedelta(
                        seconds=settings.ORDER_OTP_TTL_SECONDS)).isoformat(),
                    'attempts': 0,
                }
                send_tracking_otp(emails[0], code, len(orders))
                return redirect('website:track_verify')

    return render(request, 'website/track_order.html', {'data': data, 'errors': errors})


def track_verify(request):
    """Step two: check the emailed code, then unlock those orders."""
    pending = request.session.get(OTP_SESSION_KEY)
    if not pending:
        return redirect('website:track_order')

    if timezone.now() > datetime.fromisoformat(pending['expires']):
        request.session.pop(OTP_SESSION_KEY, None)
        messages.error(request, 'That code expired. Please request a new one.')
        return redirect('website:track_order')

    errors = {}
    if request.method == 'POST':
        code = re.sub(r'\D', '', request.POST.get('code') or '')

        if code and hash_otp(code) == pending['hash']:
            orders = Order.objects.filter(order_number__in=pending['orders'])
            for order in orders:
                remember_order(request, order)
            request.session.pop(OTP_SESSION_KEY, None)

            if len(pending['orders']) == 1:
                return redirect(
                    'website:order_detail', order_number=pending['orders'][0])
            return redirect('website:tracked_orders')

        # Count the wrong guess first, so the last allowed try actually stops
        # the flow instead of handing out one more.
        pending['attempts'] += 1
        if pending['attempts'] >= settings.ORDER_OTP_MAX_ATTEMPTS:
            request.session.pop(OTP_SESSION_KEY, None)
            messages.error(request, 'Too many wrong codes. Please start again.')
            return redirect('website:track_order')

        request.session[OTP_SESSION_KEY] = pending
        remaining = settings.ORDER_OTP_MAX_ATTEMPTS - pending['attempts']
        errors['code'] = f'That code is not right. {remaining} tries left.'

    return render(request, 'website/track_verify.html', {
        'masked_email': mask_email(pending['email']),
        'order_count': len(pending['orders']),
        'errors': errors,
    })


def tracked_orders(request):
    """Every order unlocked in this browser -- the guest version of my-orders."""
    numbers = request.session.get('my_orders', [])
    orders = (Order.objects.filter(order_number__in=numbers)
              .prefetch_related('items'))
    if not orders:
        messages.info(request, 'Look up your orders to see them here.')
        return redirect('website:track_order')
    return render(request, 'website/tracked_orders.html', {'orders': orders})


@require_POST
def cancel_order(request, order_number):
    order = get_object_or_404(Order, order_number=order_number)
    if not owns_order(request, order):
        return redirect('website:track_order')

    if not order.can_cancel:
        messages.error(request, 'This order has already been packed and cannot be cancelled.')
        return redirect('website:order_detail', order_number=order.order_number)

    with transaction.atomic():
        restore_stock(order)
        order.cancelled_reason = (request.POST.get('reason') or 'Cancelled by customer')[:250]
        order.log_event(Order.STATUS_CANCELLED, note=order.cancelled_reason)
    messages.success(request, f'Order {order.order_number} has been cancelled.')
    return redirect('website:order_detail', order_number=order.order_number)


@login_required
def my_orders(request):
    orders = Order.objects.filter(user=request.user).prefetch_related('items')
    return render(request, 'website/my_orders.html', {'orders': orders})
