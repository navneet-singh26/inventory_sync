
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ProductViewSet, WarehouseViewSet, 
    InventoryStockViewSet, StockTransactionViewSet,
    SyncViewSet
)

router = DefaultRouter()
router.register(r'products', ProductViewSet, basename='product')
router.register(r'warehouses', WarehouseViewSet, basename='warehouse')
router.register(r'stocks', InventoryStockViewSet, basename='stock')
router.register(r'transactions', StockTransactionViewSet, basename='transaction')
router.register(r'sync', SyncViewSet, basename='sync')

urlpatterns = [
    path('', include(router.urls)),
]