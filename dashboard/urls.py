from django.urls import path

from . import views

app_name = 'dashboard'

urlpatterns = [
    # Authentication
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),

    # Dashboard home
    path('', views.dashboard_home, name='home'),
    path('profile/', views.profile_view, name='profile'),

    # Category URLs
    path('categories/', views.categories_list, name='categories_list'),
    path('categories/add/', views.category_add, name='category_add'),
    path('categories/<int:pk>/edit/', views.category_edit, name='category_edit'),
    path('categories/<int:pk>/delete/', views.category_delete, name='category_delete'),

    # Subcategory URLs (Oils -> Groundnut Oil, Coconut Oil, ...)
    path('subcategories/', views.subcategories_list, name='subcategories_list'),
    path('subcategories/add/', views.subcategory_add, name='subcategory_add'),
    path('subcategories/<int:pk>/edit/', views.subcategory_edit, name='subcategory_edit'),
    path('subcategories/<int:pk>/delete/', views.subcategory_delete, name='subcategory_delete'),

    # Product URLs
    path('products/', views.products_list, name='products_list'),
    path('products/add/', views.product_add, name='product_add'),
    path('products/<int:pk>/edit/', views.product_edit, name='product_edit'),
    path('products/<int:pk>/delete/', views.product_delete, name='product_delete'),
    path('stock/', views.stock_list, name='stock_list'),

    # Home banner URLs (photos / videos under the header)
    path('home-banner/', views.banners_list, name='banners_list'),
    path('home-banner/add/', views.banner_add, name='banner_add'),
    path('home-banner/<int:pk>/edit/', views.banner_edit, name='banner_edit'),
    path('home-banner/<int:pk>/delete/', views.banner_delete, name='banner_delete'),

    # Process stage URLs (farmer -> customer journey)
    path('process/', views.stages_list, name='stages_list'),
    path('process/add/', views.stage_add, name='stage_add'),
    path('process/<int:pk>/edit/', views.stage_edit, name='stage_edit'),
    path('process/<int:pk>/delete/', views.stage_delete, name='stage_delete'),

    # Order URLs
    path('orders/', views.orders_list, name='orders_list'),
    path('orders/<str:order_number>/', views.order_detail, name='order_detail'),
    path('orders/<str:order_number>/invoice/', views.order_invoice, name='order_invoice'),

    # Combo URLs
    path('combos/', views.combos_list, name='combos_list'),
    path('combos/add/', views.combo_add, name='combo_add'),
    path('combos/<int:pk>/edit/', views.combo_edit, name='combo_edit'),
    path('combos/<int:pk>/delete/', views.combo_delete, name='combo_delete'),

    # Gallery URLs
    path('gallery/', views.gallery_list, name='gallery_list'),
    path('gallery/add/', views.gallery_add, name='gallery_add'),
    path('gallery/<int:pk>/edit/', views.gallery_edit, name='gallery_edit'),
    path('gallery/<int:pk>/delete/', views.gallery_delete, name='gallery_delete'),
]
