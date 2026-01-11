
from django.urls import path
from .views import MarketplaceStockView, MarketplaceConfigView

urlpatterns = [
    path('stock/<str:marketplace_name>/<str:sku>/', MarketplaceStockView.as_view(), name='marketplace-stock'),
    path('config/<str:marketplace_name>/', MarketplaceConfigView.as_view(), name='marketplace-config'),
]