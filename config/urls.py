from django.contrib.auth import views as auth
from django.urls import path

from shop import api, views

urlpatterns = [
    path('', views.inventory, name='inventory'),
    path('products/new/', views.product_new, name='product_new'),
    path('products/<int:pk>/adjust/', views.adjust, name='adjust'),
    path('orders/', views.orders, name='orders'),
    path('orders/new/', views.order_new, name='order_new'),
    path('orders/<int:pk>/', views.order_detail, name='order_detail'),
    path('orders/<int:pk>/action/', views.order_action, name='order_action'),
    path('reports/', views.reports, name='reports'),
    path('login/', auth.LoginView.as_view(template_name='login.html'), name='login'),
    path('logout/', auth.LogoutView.as_view(), name='logout'),
    path('api/products/', api.ProductsAPI.as_view()),
    path('api/orders/', api.OrdersAPI.as_view()),
    path('api/orders/<int:pk>/', api.OrderAPI.as_view()),
]
