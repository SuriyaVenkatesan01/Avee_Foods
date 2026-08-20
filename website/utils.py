"""Small helpers shared by the checkout and payment views."""

import re
from decimal import Decimal
from io import BytesIO
from urllib.parse import quote

from django.conf import settings


def upi_payment_uri(order):
    """Build a `upi://pay` deep link that opens GPay / PhonePe / Paytm.

    Tapping this on a phone pre-fills the payee, amount and order number, so
    the customer cannot pay the wrong amount to the wrong VPA by accident.
    """
    cfg = settings.STORE
    params = {
        'pa': cfg['upi_id'],
        'pn': cfg['upi_payee'],
        'am': f'{order.total:.2f}',
        'cu': 'INR',
        'tn': f'Avee Foods order {order.order_number}',
        'tr': order.order_number,
    }
    query = '&'.join(f'{k}={quote(str(v))}' for k, v in params.items())
    return f'upi://pay?{query}'


def upi_qr_svg(uri):
    """Render `uri` as an inline SVG QR code the customer can scan.

    Returns an empty string when the optional `qrcode` package is missing so a
    fresh deployment shows the UPI ID and the deep link instead of erroring.
    """
    try:
        import qrcode
        import qrcode.image.svg
    except ImportError:
        return ''

    img = qrcode.make(
        uri,
        image_factory=qrcode.image.svg.SvgPathImage,
        box_size=10,
        border=2,
    )
    buffer = BytesIO()
    img.save(buffer)
    svg = buffer.getvalue().decode('utf-8')

    # Drop the XML prolog (invalid inside HTML) and the fixed mm size so the
    # QR scales to whatever box the payment page gives it.
    svg = svg.split('?>', 1)[-1].strip()
    return re.sub(r'(width|height)="[\d.]+mm"',
                  lambda m: m.group(1) + '="100%"', svg, count=2)


def build_order_from_cart(order, cart):
    """Freeze cart lines onto the order and lock in the totals.

    Prices are copied, not referenced, so a later price change never rewrites
    an order the customer already paid for.
    """
    from .models import OrderItem  # local import avoids a circular import

    items = []
    for line in cart.line_items:
        variant = line.variant
        items.append(OrderItem(
            order=order,
            variant=variant,
            product=variant.product,
            product_name=variant.product.name,
            variant_label=variant.label,
            sku=variant.sku,
            unit_price=variant.price,
            quantity=line.quantity,
            line_total=variant.price * line.quantity,
        ))
    OrderItem.objects.bulk_create(items)

    order.subtotal = sum((i.line_total for i in items), Decimal('0.00'))
    order.shipping_fee = cart.shipping_fee
    order.total = order.subtotal + order.shipping_fee - order.discount
    order.save()
    return order


def reduce_stock(order):
    """Take the ordered quantity out of stock, never going below zero."""
    for item in order.items.select_related('variant__product'):
        variant = item.variant
        if variant and variant.product and variant.product.stock_managed:
            variant.stock = max(0, variant.stock - item.quantity)
            variant.save(update_fields=['stock'])


def restore_stock(order):
    """Put stock back when an order is cancelled."""
    for item in order.items.select_related('variant__product'):
        variant = item.variant
        if variant and variant.product and variant.product.stock_managed:
            variant.stock = variant.stock + item.quantity
            variant.save(update_fields=['stock'])


def owns_order(request, order):
    """Can this visitor see this order without typing the phone number?"""
    if request.user.is_authenticated and order.user_id == request.user.pk:
        return True
    if order.order_number in request.session.get('my_orders', []):
        return True
    return False


def remember_order(request, order):
    """Let a guest reopen their own order from the same browser."""
    orders = request.session.get('my_orders', [])
    if order.order_number not in orders:
        orders.append(order.order_number)
        request.session['my_orders'] = orders[-25:]
