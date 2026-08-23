"""Small helpers shared by the checkout and payment views."""

import hashlib
import logging
import re
import secrets
import string
from decimal import Decimal
from io import BytesIO
from urllib.parse import quote

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse

logger = logging.getLogger(__name__)


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


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

def send_order_confirmation(order):
    """Email the customer their confirmation, and copy the store.

    Never raises: a mail server that is down or misconfigured must not lose an
    order that has already been paid for and written to the database.
    """
    if not order.email:
        return False

    context = {
        'order': order,
        'items': list(order.items.all()),
        'store': settings.STORE,
        'site_url': settings.SITE_URL,
        'track_url': f"{settings.SITE_URL}{reverse('website:track_order')}",
    }
    subject = f'Order {order.order_number} confirmed - Avee Foods'
    body = render_to_string('website/email/order_confirmation.txt', context)

    recipients = [order.email]
    company = getattr(settings, 'COMPANY_EMAIL', '')
    if company:
        recipients.append(company)

    return _send(subject, body, recipients, context=order.order_number)


def send_tracking_otp(email, code, order_count):
    """Email a one-time code before showing someone their orders."""
    subject = f'{code} is your Avee Foods tracking code'
    body = render_to_string('website/email/tracking_otp.txt', {
        'code': code,
        'order_count': order_count,
        'minutes': settings.ORDER_OTP_TTL_SECONDS // 60,
        'store': settings.STORE,
    })
    return _send(subject, body, [email], context='tracking OTP')


def _send(subject, body, recipients, context=''):
    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipients,
            fail_silently=False,
        )
        return True
    except Exception:
        logger.exception('Could not send mail (%s) to %s', context, recipients)
        return False


# ---------------------------------------------------------------------------
# Tracking one-time codes
# ---------------------------------------------------------------------------

def generate_otp():
    length = settings.ORDER_OTP_LENGTH
    return ''.join(secrets.choice(string.digits) for _ in range(length))


def hash_otp(code):
    """Only the hash goes in the session, never the code itself."""
    salted = f'{settings.SECRET_KEY}:{code}'
    return hashlib.sha256(salted.encode()).hexdigest()


def mask_email(email):
    """ab***@gmail.com -- enough to recognise, not enough to harvest."""
    if not email or '@' not in email:
        return ''
    name, domain = email.split('@', 1)
    keep = name[:2] if len(name) > 2 else name[:1]
    return f'{keep}{"*" * max(3, len(name) - len(keep))}@{domain}'
