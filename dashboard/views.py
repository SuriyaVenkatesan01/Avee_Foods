import json
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from website.cart import merge_on_login
from website.models import (
    PRODUCT_DETAILS_TEMPLATE, Category, Combo, FoodProduct, GalleryImage,
    HomeBanner, Order, Payment, ProcessStage, ProductVariant, SubCategory,
)
from website.utils import restore_stock

LOGIN_URL = 'dashboard:login'


# ============= SMALL PARSING HELPERS =============
# The whole dashboard reads request.POST directly, so these keep the views
# short and give every screen the same "bad input" behaviour.

def _text(post, key, default=''):
    return (post.get(key) or default).strip()


def _checkbox(post, key):
    return post.get(key) in ('on', 'true', '1', 'yes')


def _to_decimal(raw, field, errors, label, required=True, minimum=None):
    raw = (raw or '').strip()
    if not raw:
        if required:
            errors[field] = f'{label} is required.'
        return None
    try:
        value = Decimal(raw)
    except InvalidOperation:
        errors[field] = f'{label} must be a number.'
        return None
    if minimum is not None and value < minimum:
        errors[field] = f'{label} cannot be less than {minimum}.'
        return None
    return value


def _to_int(raw, default=0):
    try:
        return max(0, int(str(raw).strip()))
    except (TypeError, ValueError):
        return default


# ============= AUTHENTICATION =============

def _authenticate_by_email(request, email, password):
    """Sign in with an email address instead of a username.

    Django's ModelBackend only knows how to check a username, so the email is
    resolved to its account(s) first. `User.email` carries no unique constraint,
    so if two accounts ever share an address, each is tried and the one whose
    password matches wins.
    """
    if not email or not password:
        return None

    candidates = list(User.objects.filter(email__iexact=email))
    for candidate in candidates:
        user = authenticate(request, username=candidate.get_username(), password=password)
        if user is not None:
            return user

    if not candidates:
        # Unknown email: spend the same time a real password check costs, so the
        # response speed cannot be used to discover which addresses have accounts
        User().set_password(password)

    return None


def login_view(request):
    """Dashboard login -- email address and password."""
    if request.user.is_authenticated:
        return redirect('dashboard:home')

    email = ''
    if request.method == 'POST':
        email = _text(request.POST, 'email')
        user = _authenticate_by_email(request, email, request.POST.get('password') or '')

        if user is not None:
            login(request, user)
            # "Remember me" off -> the session ends when the browser is closed
            if not _checkbox(request.POST, 'remember'):
                request.session.set_expiry(0)
            merge_on_login(request, user)
            messages.success(request, f'Welcome back, {user.first_name or user.get_username()}!')
            return redirect('dashboard:home')

        # Deliberately vague: never reveal whether the email or password was wrong
        messages.error(request, 'Invalid email or password.')

    return render(request, 'dashboard/login.html', {'email': email})


def logout_view(request):
    """User logout view"""
    if request.method == 'POST':
        logout(request)
        messages.success(request, 'You have been logged out successfully.')
        return redirect('dashboard:login')

    return render(request, 'dashboard/logout_confirm.html')


@login_required(login_url=LOGIN_URL)
def dashboard_home(request):
    """Dashboard home: catalog counts plus anything that needs attention."""
    open_statuses = [s for s in Order.STATUS_FLOW if s != Order.STATUS_DELIVERED]
    paid = Order.objects.filter(payment_status=Order.PAY_PAID).exclude(
        status=Order.STATUS_CANCELLED)

    context = {
        'products_count': FoodProduct.objects.count(),
        'categories_count': Category.objects.count(),
        'variants_count': ProductVariant.objects.count(),
        'stages_count': ProcessStage.objects.count(),
        'combos_count': Combo.objects.count(),
        'gallery_count': GalleryImage.objects.count(),
        'orders_count': Order.objects.count(),
        'open_orders': Order.objects.filter(status__in=open_statuses).count(),
        'awaiting_payment': Order.objects.filter(payment_status=Order.PAY_AWAITING).count(),
        'revenue': paid.aggregate(total=Sum('total'))['total'] or 0,
        'recent_orders': Order.objects.all()[:8],
        'low_stock': ProductVariant.objects.filter(
            is_active=True, product__stock_managed=True, stock__lte=5,
        ).select_related('product')[:10],
        'products_without_variants': FoodProduct.objects.annotate(
            variant_total=Count('variants')).filter(variant_total=0).count(),
    }
    return render(request, 'dashboard/home.html', context)


@login_required(login_url=LOGIN_URL)
def profile_view(request):
    """User profile view"""
    return render(request, 'dashboard/profile.html')


# ============= CATEGORY MANAGEMENT =============

@login_required(login_url=LOGIN_URL)
def categories_list(request):
    categories = Category.objects.annotate(product_total=Count('products'))
    return render(request, 'dashboard/categories_list.html', {'categories': categories})


def _save_category(request, category=None):
    """Shared add/edit handler. A category is just a name and an image.

    Everything else on the model (slug, icon, tagline, ordering, measure type)
    is left to its default on create and carried over untouched on edit, so
    editing the name never wipes a value set from the Django admin.
    """
    data = {'name': category.name if category else ''}
    errors = {}

    if request.method == 'POST':
        data = {'name': _text(request.POST, 'name')}

        if not data['name']:
            errors['name'] = 'Category name is required.'
        else:
            clash = Category.objects.filter(name__iexact=data['name'])
            if category:
                clash = clash.exclude(pk=category.pk)
            if clash.exists():
                errors['name'] = 'A category with this name already exists.'

        if category is None and not request.FILES.get('image'):
            errors['image'] = 'A category image is required.'

        if not errors:
            target = category or Category()
            target.name = data['name']
            if request.FILES.get('image'):
                target.image = request.FILES['image']
            # New categories go live straight away; Category.save() fills the slug
            target.save()

            messages.success(request, f'Category "{target.name}" saved.')
            return None, redirect('dashboard:categories_list')

        messages.error(request, 'Please fix the errors below.')

    return {'data': data, 'errors': errors, 'category': category}, None


@login_required(login_url=LOGIN_URL)
def category_add(request):
    context, response = _save_category(request)
    return response or render(request, 'dashboard/category_form.html', context)


@login_required(login_url=LOGIN_URL)
def category_edit(request, pk):
    category = get_object_or_404(Category, pk=pk)
    context, response = _save_category(request, category)
    return response or render(request, 'dashboard/category_form.html', context)


@login_required(login_url=LOGIN_URL)
def category_delete(request, pk):
    category = get_object_or_404(Category, pk=pk)
    product_total = category.products.count()

    if request.method == 'POST':
        # Products point at the category with PROTECT, so refuse rather than 500
        if product_total:
            messages.error(
                request,
                f'"{category.name}" still has {product_total} product(s). '
                'Move or delete them first.',
            )
            return redirect('dashboard:categories_list')
        category.delete()
        messages.success(request, 'Category deleted.')
        return redirect('dashboard:categories_list')

    return render(request, 'dashboard/category_confirm_delete.html',
                  {'category': category, 'product_total': product_total})


# ============= SUBCATEGORY MANAGEMENT =============

@login_required(login_url=LOGIN_URL)
def subcategories_list(request):
    subcategories = (
        SubCategory.objects.select_related('category')
        .annotate(product_total=Count('products'))
        .order_by('category__display_order', 'category__name', 'display_order', 'name')
    )

    category_slug = request.GET.get('category')
    if category_slug:
        subcategories = subcategories.filter(category__slug=category_slug)

    return render(request, 'dashboard/subcategories_list.html', {
        'subcategories': subcategories,
        'categories': Category.objects.all(),
        'selected_category': category_slug or '',
    })


def _save_subcategory(request, subcategory=None):
    """A subcategory is its parent category, a name and an image."""
    data = {
        'category': str(subcategory.category_id) if subcategory else '',
        'name': subcategory.name if subcategory else '',
    }
    errors = {}

    if request.method == 'POST':
        data = {
            'category': _text(request.POST, 'category'),
            'name': _text(request.POST, 'name'),
        }

        category = Category.objects.filter(pk=data['category']).first() if data['category'] else None
        if category is None:
            errors['category'] = 'Choose the category this belongs to.'

        if not data['name']:
            errors['name'] = 'Subcategory name is required.'
        elif category is not None:
            # Names only have to be unique inside their own category
            clash = SubCategory.objects.filter(category=category, name__iexact=data['name'])
            if subcategory:
                clash = clash.exclude(pk=subcategory.pk)
            if clash.exists():
                errors['name'] = f'"{data["name"]}" already exists under {category.name}.'

        if subcategory is None and not request.FILES.get('image'):
            errors['image'] = 'A subcategory image is required.'

        if not errors:
            target = subcategory or SubCategory()
            moved = target.pk and target.category_id != category.pk
            target.category = category
            target.name = data['name']
            if moved:
                target.slug = ''  # re-check uniqueness inside the new category
            if request.FILES.get('image'):
                target.image = request.FILES['image']
            target.save()

            # Products must never point at a subcategory of another category
            if moved:
                target.products.update(category=category)

            messages.success(request, f'Subcategory "{target.name}" saved.')
            return None, redirect('dashboard:subcategories_list')

        messages.error(request, 'Please fix the errors below.')

    return {
        'data': data,
        'errors': errors,
        'subcategory': subcategory,
        'categories': Category.objects.filter(is_active=True),
    }, None


@login_required(login_url=LOGIN_URL)
def subcategory_add(request):
    context, response = _save_subcategory(request)
    return response or render(request, 'dashboard/subcategory_form.html', context)


@login_required(login_url=LOGIN_URL)
def subcategory_edit(request, pk):
    subcategory = get_object_or_404(SubCategory, pk=pk)
    context, response = _save_subcategory(request, subcategory)
    return response or render(request, 'dashboard/subcategory_form.html', context)


@login_required(login_url=LOGIN_URL)
def subcategory_delete(request, pk):
    subcategory = get_object_or_404(SubCategory, pk=pk)
    product_total = subcategory.products.count()

    if request.method == 'POST':
        # Products survive -- they just fall back to showing under the category
        subcategory.delete()
        messages.success(
            request,
            f'Subcategory deleted. {product_total} product(s) now sit directly '
            'under the category.' if product_total else 'Subcategory deleted.',
        )
        return redirect('dashboard:subcategories_list')

    return render(request, 'dashboard/subcategory_confirm_delete.html',
                  {'subcategory': subcategory, 'product_total': product_total})


# ============= PRODUCT MANAGEMENT =============

@login_required(login_url=LOGIN_URL)
def products_list(request):
    products = (
        FoodProduct.objects.select_related('category', 'subcategory')
        .prefetch_related('variants')
        .annotate(variant_total=Count('variants'))
    )

    category_slug = request.GET.get('category')
    if category_slug:
        products = products.filter(category__slug=category_slug)

    subcategory_pk = request.GET.get('subcategory')
    if subcategory_pk:
        products = products.filter(subcategory__pk=subcategory_pk)

    query = (request.GET.get('q') or '').strip()
    if query:
        products = products.filter(Q(name__icontains=query) | Q(slug__icontains=query))

    return render(request, 'dashboard/products_list.html', {
        'products': products,
        'categories': Category.objects.all(),
        'subcategories': SubCategory.objects.select_related('category'),
        'selected_category': category_slug or '',
        'selected_subcategory': subcategory_pk or '',
        'query': query,
    })


def _read_variant_rows(post):
    """Read the repeating pack-size rows out of the product form.

    Rows are addressed by an index carried in the field name
    (variant_price_3, variant_stock_3, ...) and listed in `variant_rows`, so
    adding or removing a row in the browser never shifts the other rows.
    """
    rows = []
    for index in post.getlist('variant_rows'):
        prefix = f'_{index}'
        row = {
            'index': index,
            'id': _text(post, f'variant_id{prefix}'),
            'pack_size': _text(post, f'variant_pack_size{prefix}'),
            'unit': _text(post, f'variant_unit{prefix}'),
            'label': _text(post, f'variant_label{prefix}'),
            'price': _text(post, f'variant_price{prefix}'),
            'mrp': _text(post, f'variant_mrp{prefix}'),
            'stock': _text(post, f'variant_stock{prefix}'),
            'display_order': _text(post, f'variant_display_order{prefix}'),
            'is_active': _checkbox(post, f'variant_active{prefix}'),
            'delete': _checkbox(post, f'variant_delete{prefix}'),
            'errors': {},
        }
        # A row the user left completely untouched is simply ignored
        if not row['id'] and not row['pack_size'] and not row['price']:
            continue
        rows.append(row)
    return rows


def _validate_variant_rows(rows):
    """Fill in row['errors'] and return True when every kept row is usable."""
    units = dict(ProductVariant.UNIT_CHOICES)
    seen = set()
    ok = True

    for row in rows:
        if row['delete']:
            continue
        errors = row['errors']

        pack_size = _to_decimal(
            row['pack_size'], 'pack_size', errors, 'Pack size', minimum=Decimal('0.01'))
        _to_decimal(row['price'], 'price', errors, 'Price', minimum=Decimal('0'))

        if row['mrp']:
            mrp = _to_decimal(row['mrp'], 'mrp', errors, 'MRP', minimum=Decimal('0'))
            price_raw = row['price']
            if mrp is not None and price_raw:
                try:
                    if mrp < Decimal(price_raw):
                        errors['mrp'] = 'MRP cannot be lower than the selling price.'
                except InvalidOperation:
                    pass

        if row['unit'] not in units:
            errors['unit'] = 'Choose a unit.'

        if pack_size is not None and row['unit'] in units:
            key = (pack_size, row['unit'])
            if key in seen:
                errors['pack_size'] = 'This pack size is listed twice.'
            seen.add(key)

        if errors:
            ok = False

    if not any(not row['delete'] for row in rows):
        ok = False

    return ok


def _save_product(request, product=None):
    """Shared add/edit handler: the product plus its pack sizes."""
    data = {
        'name': product.name if product else '',
        'slug': product.slug if product else '',
        'category': str(product.category_id) if product and product.category_id else '',
        'subcategory': str(product.subcategory_id) if product and product.subcategory_id else '',
        'short_description': product.short_description if product else '',
        'description': product.description if product else '',
        'details': (json.dumps(product.details, indent=2, ensure_ascii=False)
                    if product and product.details else ''),
        'display_order': product.display_order if product else 0,
        'stock_managed': product.stock_managed if product else True,
        'is_active': product.is_active if product else True,
        'is_featured': product.is_featured if product else False,
    }
    errors = {}
    details = product.details if product else {}

    if product:
        variant_rows = [{
            'index': str(variant.pk),
            'id': str(variant.pk),
            'pack_size': variant.pack_size,
            'unit': variant.unit,
            'label': variant.label,
            'price': variant.price,
            'mrp': variant.mrp or '',
            'stock': variant.stock,
            'display_order': variant.display_order,
            'is_active': variant.is_active,
            'delete': False,
            'errors': {},
        } for variant in product.variants.all()]
    else:
        variant_rows = []

    if request.method == 'POST':
        data = {
            'name': _text(request.POST, 'name'),
            'slug': _text(request.POST, 'slug'),
            'category': _text(request.POST, 'category'),
            'subcategory': _text(request.POST, 'subcategory'),
            'short_description': _text(request.POST, 'short_description'),
            'description': _text(request.POST, 'description'),
            'details': _text(request.POST, 'details'),
            'display_order': _to_int(request.POST.get('display_order')),
            'stock_managed': _checkbox(request.POST, 'stock_managed'),
            'is_active': _checkbox(request.POST, 'is_active'),
            'is_featured': _checkbox(request.POST, 'is_featured'),
        }
        variant_rows = _read_variant_rows(request.POST)

        if not data['name']:
            errors['name'] = 'Product name is required.'

        category = Category.objects.filter(pk=data['category']).first() if data['category'] else None
        if category is None:
            errors['category'] = 'Choose a category.'

        # Optional, but if given it has to live under the chosen category --
        # otherwise the product would vanish from both browse paths
        subcategory = None
        if data['subcategory']:
            subcategory = SubCategory.objects.filter(pk=data['subcategory']).first()
            if subcategory is None:
                errors['subcategory'] = 'That subcategory no longer exists.'
            elif category and subcategory.category_id != category.pk:
                errors['subcategory'] = (
                    f'"{subcategory.name}" belongs to {subcategory.category.name}, '
                    f'not {category.name}.'
                )

        if not data['description']:
            errors['description'] = 'Description is required.'

        if product is None and not request.FILES.get('image'):
            errors['image'] = 'A product image is required.'

        # `details` is free-form JSON, so a typo must not lose the whole form
        if data['details']:
            try:
                details = json.loads(data['details'])
            except json.JSONDecodeError as exc:
                errors['details'] = (
                    f'Invalid JSON — {exc.msg} (line {exc.lineno}, column {exc.colno}).')
            else:
                if not isinstance(details, dict):
                    errors['details'] = 'The details block must be a JSON object { ... }.'
        else:
            details = {}

        variants_ok = _validate_variant_rows(variant_rows)
        if not variants_ok and 'variants' not in errors:
            errors['variants'] = (
                'Add at least one pack size and fix the highlighted rows.')

        if not errors and variants_ok:
            with transaction.atomic():
                target = product or FoodProduct()
                target.name = data['name']
                target.slug = data['slug']  # blank -> FoodProduct.save() generates it
                target.category = category
                target.subcategory = subcategory
                target.short_description = data['short_description']
                target.description = data['description']
                target.details = details
                target.display_order = data['display_order']
                target.stock_managed = data['stock_managed']
                target.is_active = data['is_active']
                target.is_featured = data['is_featured']
                if request.FILES.get('image'):
                    target.image = request.FILES['image']
                target.save()

                for row in variant_rows:
                    if row['delete']:
                        if row['id']:
                            ProductVariant.objects.filter(
                                pk=row['id'], product=target).delete()
                        continue

                    variant = None
                    if row['id']:
                        variant = ProductVariant.objects.filter(
                            pk=row['id'], product=target).first()
                    variant = variant or ProductVariant(product=target)

                    variant.pack_size = Decimal(row['pack_size'])
                    variant.unit = row['unit']
                    variant.label = row['label']  # blank -> auto "500 ml"
                    variant.price = Decimal(row['price'])
                    variant.mrp = Decimal(row['mrp']) if row['mrp'] else None
                    variant.stock = _to_int(row['stock'])
                    variant.display_order = _to_int(row['display_order'])
                    variant.is_active = row['is_active']
                    variant.save()

                # Extra gallery images are optional and simply appended
                for extra in request.FILES.getlist('extra_images'):
                    target.images.create(image=extra, alt_text=target.name)

            messages.success(
                request,
                f'"{target.name}" saved with {target.variants.count()} pack size(s).',
            )
            return None, redirect('dashboard:products_list')

        messages.error(request, 'Please fix the errors below.')

    context = {
        'data': data,
        'errors': errors,
        'product': product,
        'categories': Category.objects.filter(is_active=True),
        # Every subcategory is rendered once; the browser hides the ones that
        # do not belong to the selected category
        'subcategories': SubCategory.objects.filter(is_active=True).select_related('category'),
        'unit_choices': ProductVariant.UNIT_CHOICES,
        'variant_rows': variant_rows,
        'details_template': json.dumps(PRODUCT_DETAILS_TEMPLATE, indent=2, ensure_ascii=False),
    }
    return context, None


@login_required(login_url=LOGIN_URL)
def product_add(request):
    context, response = _save_product(request)
    return response or render(request, 'dashboard/product_form.html', context)


@login_required(login_url=LOGIN_URL)
def product_edit(request, pk):
    product = get_object_or_404(FoodProduct, pk=pk)
    context, response = _save_product(request, product)
    return response or render(request, 'dashboard/product_form.html', context)


@login_required(login_url=LOGIN_URL)
def product_delete(request, pk):
    product = get_object_or_404(FoodProduct, pk=pk)

    if request.method == 'POST':
        product.delete()
        messages.success(request, 'Product deleted.')
        return redirect('dashboard:products_list')

    return render(request, 'dashboard/product_confirm_delete.html', {'product': product})


@login_required(login_url=LOGIN_URL)
def stock_list(request):
    """One screen to review and correct stock across every pack size."""
    variants = (
        ProductVariant.objects.select_related('product', 'product__category')
        .order_by('product__name', 'pack_size')
    )
    if request.GET.get('low'):
        variants = variants.filter(stock__lte=5)

    if request.method == 'POST':
        updated = 0
        for variant in variants:
            raw = request.POST.get(f'stock_{variant.pk}')
            if raw is None:
                continue
            value = _to_int(raw, default=-1)
            if value >= 0 and value != variant.stock:
                variant.stock = value
                variant.save(update_fields=['stock'])
                updated += 1
        messages.success(request, f'{updated} pack size(s) updated.')
        return redirect(request.get_full_path())

    return render(request, 'dashboard/stock_list.html', {
        'variants': variants,
        'low_only': bool(request.GET.get('low')),
    })


# ============= HOME BANNER MANAGEMENT =============

@login_required(login_url=LOGIN_URL)
def banners_list(request):
    """Photos and videos listed separately, with a live/hidden toggle."""
    banners = HomeBanner.objects.all()

    # Toggling Active is the everyday action, so it is a one-click POST here
    # rather than a trip through the edit form
    if request.method == 'POST' and request.POST.get('action') == 'toggle':
        banner = get_object_or_404(HomeBanner, pk=request.POST.get('banner_id'))
        banner.is_active = not banner.is_active
        banner.save(update_fields=['is_active'])
        messages.success(
            request,
            'Now showing on the home page.' if banner.is_active
            else 'Hidden from the home page.',
        )
        return redirect('dashboard:banners_list')

    return render(request, 'dashboard/banners_list.html', {
        'photos': banners.filter(media_type=HomeBanner.TYPE_IMAGE),
        'videos': banners.filter(media_type=HomeBanner.TYPE_VIDEO),
        'live_count': banners.filter(is_active=True).count(),
    })


def _save_banner(request, banner=None):
    data = {
        'media_type': banner.media_type if banner else HomeBanner.TYPE_IMAGE,
        'title': banner.title if banner else '',
        'subtitle': banner.subtitle if banner else '',
        'button_text': banner.button_text if banner else '',
        'button_url': banner.button_url if banner else '',
        'duration_seconds': banner.duration_seconds if banner else 5,
        'display_order': banner.display_order if banner else 0,
        'is_active': banner.is_active if banner else True,
    }
    errors = {}

    if request.method == 'POST':
        data = {
            'media_type': _text(request.POST, 'media_type'),
            'title': _text(request.POST, 'title'),
            'subtitle': _text(request.POST, 'subtitle'),
            'button_text': _text(request.POST, 'button_text'),
            'button_url': _text(request.POST, 'button_url'),
            'duration_seconds': _to_int(request.POST.get('duration_seconds'), default=5),
            'display_order': _to_int(request.POST.get('display_order')),
            'is_active': _checkbox(request.POST, 'is_active'),
        }

        if data['media_type'] not in dict(HomeBanner.TYPE_CHOICES):
            errors['media_type'] = 'Choose photo or video.'

        upload = request.FILES.get('file')
        if banner is None and not upload:
            errors['file'] = 'Choose a photo or video file to upload.'

        # A video uploaded as a "photo" would render as a broken image, so the
        # extension has to agree with the chosen type
        if upload and not errors.get('media_type'):
            extension = upload.name.rsplit('.', 1)[-1].lower() if '.' in upload.name else ''
            allowed = (HomeBanner.VIDEO_EXTENSIONS if data['media_type'] == HomeBanner.TYPE_VIDEO
                       else HomeBanner.IMAGE_EXTENSIONS)
            if extension not in allowed:
                errors['file'] = (
                    f'That is a .{extension or "?"} file. For a '
                    f'{dict(HomeBanner.TYPE_CHOICES)[data["media_type"]].lower()} use: '
                    f'{", ".join(allowed)}.'
                )

        if data['duration_seconds'] < 1:
            data['duration_seconds'] = 5

        if data['button_text'] and not data['button_url']:
            errors['button_url'] = 'Add the link the button should open.'

        if not errors:
            target = banner or HomeBanner()
            target.media_type = data['media_type']
            target.title = data['title']
            target.subtitle = data['subtitle']
            target.button_text = data['button_text']
            target.button_url = data['button_url']
            target.duration_seconds = data['duration_seconds']
            target.display_order = data['display_order']
            target.is_active = data['is_active']
            if upload:
                target.file = upload
            target.save()

            messages.success(request, 'Home banner saved.')
            return None, redirect('dashboard:banners_list')

        messages.error(request, 'Please fix the errors below.')

    return {
        'data': data,
        'errors': errors,
        'banner': banner,
        'type_choices': HomeBanner.TYPE_CHOICES,
        'image_extensions': ', '.join(HomeBanner.IMAGE_EXTENSIONS),
        'video_extensions': ', '.join(HomeBanner.VIDEO_EXTENSIONS),
    }, None


@login_required(login_url=LOGIN_URL)
def banner_add(request):
    context, response = _save_banner(request)
    return response or render(request, 'dashboard/banner_form.html', context)


@login_required(login_url=LOGIN_URL)
def banner_edit(request, pk):
    banner = get_object_or_404(HomeBanner, pk=pk)
    context, response = _save_banner(request, banner)
    return response or render(request, 'dashboard/banner_form.html', context)


@login_required(login_url=LOGIN_URL)
def banner_delete(request, pk):
    banner = get_object_or_404(HomeBanner, pk=pk)
    if request.method == 'POST':
        banner.delete()
        messages.success(request, 'Home banner deleted.')
        return redirect('dashboard:banners_list')
    return render(request, 'dashboard/banner_confirm_delete.html', {'banner': banner})


# ============= PROCESS STAGE MANAGEMENT =============

@login_required(login_url=LOGIN_URL)
def stages_list(request):
    stages = ProcessStage.objects.select_related('category')
    return render(request, 'dashboard/stages_list.html', {
        'global_stages': stages.filter(category__isnull=True),
        'category_stages': stages.filter(category__isnull=False),
    })


def _save_stage(request, stage=None):
    data = {
        'title': stage.title if stage else '',
        'subtitle': stage.subtitle if stage else '',
        'description': stage.description if stage else '',
        'icon': stage.icon if stage else '',
        'category': str(stage.category_id) if stage and stage.category_id else '',
        'duration': stage.duration if stage else '',
        'display_order': stage.display_order if stage else 0,
        'is_active': stage.is_active if stage else True,
    }
    errors = {}

    if request.method == 'POST':
        data = {
            'title': _text(request.POST, 'title'),
            'subtitle': _text(request.POST, 'subtitle'),
            'description': _text(request.POST, 'description'),
            'icon': _text(request.POST, 'icon'),
            'category': _text(request.POST, 'category'),
            'duration': _text(request.POST, 'duration'),
            'display_order': _to_int(request.POST.get('display_order')),
            'is_active': _checkbox(request.POST, 'is_active'),
        }

        if not data['title']:
            errors['title'] = 'Stage title is required.'

        category = None
        if data['category']:
            category = Category.objects.filter(pk=data['category']).first()
            if category is None:
                errors['category'] = 'That category no longer exists.'

        if not errors:
            target = stage or ProcessStage()
            target.title = data['title']
            target.subtitle = data['subtitle']
            target.description = data['description']
            target.icon = data['icon']
            target.category = category
            target.duration = data['duration']
            target.display_order = data['display_order']
            target.is_active = data['is_active']
            if request.FILES.get('image'):
                target.image = request.FILES['image']
            target.save()

            messages.success(request, f'Process stage "{target.title}" saved.')
            return None, redirect('dashboard:stages_list')

        messages.error(request, 'Please fix the errors below.')

    context = {
        'data': data,
        'errors': errors,
        'stage': stage,
        'categories': Category.objects.all(),
    }
    return context, None


@login_required(login_url=LOGIN_URL)
def stage_add(request):
    context, response = _save_stage(request)
    return response or render(request, 'dashboard/stage_form.html', context)


@login_required(login_url=LOGIN_URL)
def stage_edit(request, pk):
    stage = get_object_or_404(ProcessStage, pk=pk)
    context, response = _save_stage(request, stage)
    return response or render(request, 'dashboard/stage_form.html', context)


@login_required(login_url=LOGIN_URL)
def stage_delete(request, pk):
    stage = get_object_or_404(ProcessStage, pk=pk)
    if request.method == 'POST':
        stage.delete()
        messages.success(request, 'Process stage deleted.')
        return redirect('dashboard:stages_list')
    return render(request, 'dashboard/stage_confirm_delete.html', {'stage': stage})


# ============= ORDER MANAGEMENT =============

@login_required(login_url=LOGIN_URL)
def orders_list(request):
    orders = Order.objects.prefetch_related('items')

    status = request.GET.get('status') or ''
    if status == 'open':
        orders = orders.exclude(status__in=[Order.STATUS_DELIVERED, Order.STATUS_CANCELLED])
    elif status:
        orders = orders.filter(status=status)

    payment = request.GET.get('payment') or ''
    if payment:
        orders = orders.filter(payment_status=payment)

    query = (request.GET.get('q') or '').strip()
    if query:
        orders = orders.filter(
            Q(order_number__icontains=query)
            | Q(full_name__icontains=query)
            | Q(phone__icontains=query)
            | Q(pincode__icontains=query)
            | Q(tracking_number__icontains=query)
        )

    return render(request, 'dashboard/orders_list.html', {
        'orders': orders,
        'status_choices': Order.STATUS_CHOICES,
        'payment_choices': Order.PAYMENT_STATUS_CHOICES,
        'selected_status': status,
        'selected_payment': payment,
        'query': query,
    })


@login_required(login_url=LOGIN_URL)
def order_detail(request, order_number):
    """One screen for fulfilment: status, shipment, payment and the timeline."""
    order = get_object_or_404(
        Order.objects.prefetch_related('items', 'events', 'payments'),
        order_number=order_number,
    )

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'status':
            status = _text(request.POST, 'status')
            if status not in dict(Order.STATUS_CHOICES):
                messages.error(request, 'Unknown status.')
                return redirect('dashboard:order_detail', order_number=order.order_number)

            note = _text(request.POST, 'note')[:250]
            # Putting stock back is the whole point of cancelling from here
            if status == Order.STATUS_CANCELLED and not order.is_cancelled:
                restore_stock(order)
                order.cancelled_reason = note or 'Cancelled by store'

            order.log_event(
                status, note=note, location=_text(request.POST, 'location')[:120],
                user=request.user,
            )
            messages.success(request, f'Order moved to "{order.get_status_display()}".')

        elif action == 'shipment':
            order.courier_name = _text(request.POST, 'courier_name')[:100]
            order.tracking_number = _text(request.POST, 'tracking_number')[:80]
            order.tracking_url = _text(request.POST, 'tracking_url')
            order.internal_notes = _text(request.POST, 'internal_notes')
            expected = _text(request.POST, 'expected_delivery')
            order.expected_delivery = expected or None
            order.save()
            messages.success(request, 'Shipment details saved.')

        elif action == 'payment':
            status = _text(request.POST, 'payment_status')
            if status not in dict(Order.PAYMENT_STATUS_CHOICES):
                messages.error(request, 'Unknown payment status.')
                return redirect('dashboard:order_detail', order_number=order.order_number)

            order.payment_status = status
            order.payment_reference = _text(request.POST, 'payment_reference')[:80]
            if status == Order.PAY_PAID and not order.paid_at:
                order.paid_at = timezone.now()
            order.save()
            messages.success(request, 'Payment status updated.')

        elif action == 'verify_payment':
            record = get_object_or_404(Payment, pk=request.POST.get('payment_id'), order=order)
            # mark_paid() writes through its own Order instance, so re-read ours
            # before log_event() saves and overwrites the new payment status
            record.mark_paid(user=request.user)
            order.refresh_from_db()
            order.log_event(
                order.status, note=f'Payment {record.reference} verified.', user=request.user)
            messages.success(request, f'Payment {record.reference} verified.')

        elif action == 'reject_payment':
            record = get_object_or_404(Payment, pk=request.POST.get('payment_id'), order=order)
            record.status = Payment.STATUS_REJECTED
            record.note = _text(request.POST, 'note', 'Could not verify this transaction')[:250]
            record.save()
            order.payment_status = Order.PAY_FAILED
            order.save(update_fields=['payment_status'])
            messages.warning(request, 'Payment marked as rejected.')

        return redirect('dashboard:order_detail', order_number=order.order_number)

    return render(request, 'dashboard/order_detail.html', {
        'order': order,
        'status_choices': Order.STATUS_CHOICES,
        'payment_choices': Order.PAYMENT_STATUS_CHOICES,
    })


@login_required(login_url=LOGIN_URL)
def order_invoice(request, order_number):
    """Printable invoice / packing slip."""
    order = get_object_or_404(
        Order.objects.prefetch_related('items'), order_number=order_number)
    return render(request, 'dashboard/order_invoice.html', {'order': order})


# ============= COMBO MANAGEMENT =============

@login_required(login_url=LOGIN_URL)
def combos_list(request):
    combos = Combo.objects.prefetch_related('products')
    return render(request, 'dashboard/combos_list.html', {'combos': combos})


def _save_combo(request, combo=None):
    data = {
        'name': combo.name if combo else '',
        'description': combo.description if combo else '',
        'price': combo.price if combo else '',
        'discount_percent': combo.discount_percent if combo else 0,
        'is_active': combo.is_active if combo else True,
        'products': ([str(pk) for pk in combo.products.values_list('pk', flat=True)]
                     if combo else []),
    }
    errors = {}

    if request.method == 'POST':
        data = {
            'name': _text(request.POST, 'name'),
            'description': _text(request.POST, 'description'),
            'price': _text(request.POST, 'price'),
            'discount_percent': _to_int(request.POST.get('discount_percent')),
            'is_active': _checkbox(request.POST, 'is_active'),
            'products': request.POST.getlist('products'),
        }

        if not data['name']:
            errors['name'] = 'Combo name is required.'
        if not data['description']:
            errors['description'] = 'Description is required.'

        price = _to_decimal(data['price'], 'price', errors, 'Price', minimum=Decimal('0'))

        if data['discount_percent'] > 100:
            errors['discount_percent'] = 'Discount cannot be more than 100%.'

        if combo is None and not request.FILES.get('image'):
            errors['image'] = 'A combo image is required.'

        if not errors:
            target = combo or Combo()
            target.name = data['name']
            target.description = data['description']
            target.price = price
            target.discount_percent = data['discount_percent']
            target.is_active = data['is_active']
            if request.FILES.get('image'):
                target.image = request.FILES['image']
            target.save()
            target.products.set(data['products'])

            messages.success(request, f'Combo "{target.name}" saved.')
            return None, redirect('dashboard:combos_list')

        messages.error(request, 'Please fix the errors below.')

    context = {
        'data': data,
        'errors': errors,
        'combo': combo,
        'products': FoodProduct.objects.filter(is_active=True),
    }
    return context, None


@login_required(login_url=LOGIN_URL)
def combo_add(request):
    context, response = _save_combo(request)
    return response or render(request, 'dashboard/combo_form.html', context)


@login_required(login_url=LOGIN_URL)
def combo_edit(request, pk):
    combo = get_object_or_404(Combo, pk=pk)
    context, response = _save_combo(request, combo)
    return response or render(request, 'dashboard/combo_form.html', context)


@login_required(login_url=LOGIN_URL)
def combo_delete(request, pk):
    combo = get_object_or_404(Combo, pk=pk)
    if request.method == 'POST':
        combo.delete()
        messages.success(request, 'Combo deleted.')
        return redirect('dashboard:combos_list')
    return render(request, 'dashboard/combo_confirm_delete.html', {'combo': combo})


# ============= GALLERY MANAGEMENT =============

@login_required(login_url=LOGIN_URL)
def gallery_list(request):
    return render(request, 'dashboard/gallery_list.html',
                  {'images': GalleryImage.objects.all()})


def _save_gallery(request, gallery=None):
    data = {
        'title': gallery.title if gallery else '',
        'description': gallery.description if gallery else '',
    }
    errors = {}

    if request.method == 'POST':
        data = {
            'title': _text(request.POST, 'title'),
            'description': _text(request.POST, 'description'),
        }

        if not data['title']:
            errors['title'] = 'Title is required.'
        if gallery is None and not request.FILES.get('image'):
            errors['image'] = 'An image is required.'

        if not errors:
            target = gallery or GalleryImage()
            target.title = data['title']
            target.description = data['description']
            if request.FILES.get('image'):
                target.image = request.FILES['image']
            target.save()

            messages.success(request, 'Image saved.')
            return None, redirect('dashboard:gallery_list')

        messages.error(request, 'Please fix the errors below.')

    return {'data': data, 'errors': errors, 'gallery': gallery}, None


@login_required(login_url=LOGIN_URL)
def gallery_add(request):
    context, response = _save_gallery(request)
    return response or render(request, 'dashboard/gallery_form.html', context)


@login_required(login_url=LOGIN_URL)
def gallery_edit(request, pk):
    gallery = get_object_or_404(GalleryImage, pk=pk)
    context, response = _save_gallery(request, gallery)
    return response or render(request, 'dashboard/gallery_form.html', context)


@login_required(login_url=LOGIN_URL)
def gallery_delete(request, pk):
    gallery = get_object_or_404(GalleryImage, pk=pk)
    if request.method == 'POST':
        gallery.delete()
        messages.success(request, 'Image deleted.')
        return redirect('dashboard:gallery_list')
    return render(request, 'dashboard/gallery_confirm_delete.html', {'gallery': gallery})
