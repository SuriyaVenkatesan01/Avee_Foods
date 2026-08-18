from django.urls import path

from . import views

app_name = 'website'

urlpatterns = [
    # Catalog
    path('', views.home, name='home'),
    path('products/', views.food_products, name='food_products'),
    path('products/<int:pk>/', views.product_detail_by_pk, name='product_detail_legacy'),
    path('product/<slug:slug>/', views.product_detail, name='product_detail'),
    path('category/<slug:slug>/', views.category_detail, name='category_detail'),
    path('category/<slug:category_slug>/<slug:slug>/', views.subcategory_detail,
         name='subcategory_detail'),
    path('combos/', views.combos, name='combos'),
    path('combos/<int:pk>/', views.combo_detail, name='combo_detail'),
    path('combos/<int:pk>/add/', views.combo_add_to_cart, name='combo_add_to_cart'),
    path('gallery/', views.gallery, name='gallery'),
    path('about/', views.about, name='about'),

    # Cart
    path('cart/', views.cart_detail, name='cart_detail'),
    path('cart/add/', views.cart_add, name='cart_add'),
    path('cart/<int:pk>/update/', views.cart_update, name='cart_update'),
    path('cart/<int:pk>/remove/', views.cart_remove, name='cart_remove'),

    # Checkout and payment
    path('checkout/', views.checkout, name='checkout'),
    path('pay/<str:order_number>/', views.payment, name='payment'),
    path('order/<str:order_number>/placed/', views.order_success, name='order_success'),

    # Order tracking
    path('track/', views.track_order, name='track_order'),
    path('order/<str:order_number>/', views.order_detail, name='order_detail'),
    path('order/<str:order_number>/cancel/', views.cancel_order, name='cancel_order'),
    path('my-orders/', views.my_orders, name='my_orders'),
]
