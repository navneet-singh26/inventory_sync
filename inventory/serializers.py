
from rest_framework import serializers
from .models import Product, Warehouse, InventoryStock, StockTransaction


class ProductSerializer(serializers.ModelSerializer):
    """Serializer for Product model"""
    
    class Meta:
        model = Product
        fields = [
            'id', 'sku', 'name', 'description', 'category',
            'unit_price', 'weight', 'dimensions', 'barcode',
            'is_active', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class WarehouseSerializer(serializers.ModelSerializer):
    """Serializer for Warehouse model"""
    
    class Meta:
        model = Warehouse
        fields = [
            'id', 'code', 'name', 'address', 'city', 'state',
            'country', 'postal_code', 'contact_email', 'contact_phone',
            'is_active', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class InventoryStockSerializer(serializers.ModelSerializer):
    """Serializer for InventoryStock model"""
    product = ProductSerializer(read_only=True)
    warehouse = WarehouseSerializer(read_only=True)
    product_id = serializers.IntegerField(write_only=True)
    warehouse_id = serializers.IntegerField(write_only=True)
    available_quantity = serializers.IntegerField(read_only=True)
    
    class Meta:
        model = InventoryStock
        fields = [
            'id', 'product', 'warehouse', 'product_id', 'warehouse_id',
            'quantity', 'reserved_quantity', 'available_quantity',
            'reorder_point', 'reorder_quantity', 'last_sync_at',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'available_quantity', 'created_at', 'updated_at']


class StockTransactionSerializer(serializers.ModelSerializer):
    """Serializer for StockTransaction model"""
    stock = InventoryStockSerializer(read_only=True)
    stock_id = serializers.IntegerField(write_only=True)
    
    class Meta:
        model = StockTransaction
        fields = [
            'id', 'stock', 'stock_id', 'transaction_type',
            'quantity', 'reference_id', 'notes', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']