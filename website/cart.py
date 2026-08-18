"""Session backed shopping cart.

The cart row lives in the database (so abandoned carts are visible in the
dashboard) but is addressed by a key kept in the session, which means guests
can shop without an account. When a guest logs in, `merge_on_login` folds the
guest cart into the account cart.
"""

from django.db.models import F

from .models import Cart, CartItem

CART_SESSION_KEY = 'cart_id'


def _session_key(request):
    if not request.session.session_key:
        request.session.create()
    return request.session.session_key


def get_cart(request, create=False):
    """Return the visitor's cart, or None when there is nothing yet."""
    cart = None
    cart_id = request.session.get(CART_SESSION_KEY)

    if cart_id:
        cart = Cart.objects.filter(pk=cart_id, is_active=True).first()

    if cart is None and request.user.is_authenticated:
        cart = Cart.objects.filter(user=request.user, is_active=True).order_by('-updated_at').first()

    if cart is None and create:
        cart = Cart.objects.create(
            session_key=_session_key(request),
            user=request.user if request.user.is_authenticated else None,
        )

    if cart is not None:
        request.session[CART_SESSION_KEY] = cart.pk
        # Claim the cart the first time a logged in user touches it
        if request.user.is_authenticated and cart.user_id != request.user.pk:
            cart.user = request.user
            cart.save(update_fields=['user'])

    return cart


def add_item(request, variant, quantity=1):
    """Add (or top up) a variant in the cart, capped at available stock."""
    cart = get_cart(request, create=True)
    item, created = CartItem.objects.get_or_create(
        cart=cart, variant=variant, defaults={'quantity': quantity},
    )
    if not created:
        item.quantity = item.quantity + quantity

    max_qty = variant.stock if variant.product.stock_managed else 99
    max_qty = min(max_qty, 99)
    capped = item.quantity > max_qty
    item.quantity = max(1, min(item.quantity, max_qty))
    item.save()
    cart.save(update_fields=['updated_at'])
    return item, capped


def set_quantity(request, item, quantity):
    """Set an exact quantity; zero or less removes the line."""
    if quantity <= 0:
        item.delete()
        return None

    max_qty = item.variant.stock if item.variant.product.stock_managed else 99
    item.quantity = max(1, min(quantity, min(max_qty, 99)))
    item.save()
    item.cart.save(update_fields=['updated_at'])
    return item


def remove_item(item):
    cart = item.cart
    item.delete()
    cart.save(update_fields=['updated_at'])


def clear(cart):
    cart.items.all().delete()


def cart_summary(request):
    """Lightweight header badge data -- no cart row is created for browsers."""
    cart = get_cart(request)
    if cart is None:
        return {'count': 0, 'subtotal': 0, 'cart': None}
    return {'count': cart.total_quantity, 'subtotal': cart.subtotal, 'cart': cart}


def merge_on_login(request, user):
    """Fold the guest cart into the user's existing cart after login."""
    guest_id = request.session.get(CART_SESSION_KEY)
    if not guest_id:
        return

    guest_cart = Cart.objects.filter(pk=guest_id, is_active=True).first()
    user_cart = (
        Cart.objects.filter(user=user, is_active=True)
        .exclude(pk=guest_id).order_by('-updated_at').first()
    )
    if guest_cart is None or user_cart is None:
        if guest_cart is not None:
            guest_cart.user = user
            guest_cart.save(update_fields=['user'])
        return

    for item in guest_cart.items.all():
        existing = user_cart.items.filter(variant=item.variant).first()
        if existing:
            CartItem.objects.filter(pk=existing.pk).update(
                quantity=F('quantity') + item.quantity)
        else:
            item.cart = user_cart
            item.save(update_fields=['cart'])

    guest_cart.is_active = False
    guest_cart.save(update_fields=['is_active'])
    request.session[CART_SESSION_KEY] = user_cart.pk


def release(request):
    """Drop the cart pointer once the order is placed."""
    request.session.pop(CART_SESSION_KEY, None)
