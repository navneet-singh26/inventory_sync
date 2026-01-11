
from django.contrib import admin
from django.utils.html import format_html
from .models import Product, Warehouse, InventoryStock, StockTransaction


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    """Admin interface for Product model"""
    list_display = ['sku', 'name', 'category', 'unit_price', 'is_active', 'created_at']
    list_filter = ['is_active', 'category', 'created_at']
    search_fields = ['sku', 'name', 'barcode']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('sku', 'name', 'description', 'category', 'is_active')
        }),
        ('Pricing & Dimensions', {
            'fields': ('unit_price', 'weight', 'dimensions', 'barcode')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    """Admin interface for Warehouse model"""
    list_display = ['code', 'name', 'city', 'state', 'country', 'is_active']
    list_filter = ['is_active', 'country', 'state']
    search_fields = ['code', 'name', 'city']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('code', 'name', 'is_active')
        }),
        ('Location', {
            'fields': ('address', 'city', 'state', 'country', 'postal_code')
        }),
        ('Contact', {
            'fields': ('contact_email', 'contact_phone')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(InventoryStock)
class InventoryStockAdmin(admin.ModelAdmin):
    """Admin interface for InventoryStock model"""
    list_display = [
        'product_sku', 'warehouse_code', 'quantity', 
        'reserved_quantity', 'available_display', 'last_sync_at'
    ]
    list_filter = ['warehouse', 'last_sync_at', 'created_at']
    
    search_fields = ['product__sku', 'product__name', 'warehouse__code']
    readonly_fields = ['available_quantity', 'created_at', 'updated_at', 'last_sync_at']
    raw_id_fields = ['product', 'warehouse']
    
    fieldsets = (
        ('Stock Information', {
            'fields': ('product', 'warehouse', 'quantity', 'reserved_quantity', 'available_quantity')
        }),
        ('Reorder Settings', {
            'fields': ('reorder_point', 'reorder_quantity')
        }),
        ('Timestamps', {
            'fields': ('last_sync_at', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def product_sku(self, obj):
        """Display product SKU"""
        return obj.product.sku
    product_sku.short_description = 'Product SKU'
    product_sku.admin_order_field = 'product__sku'
    
    def warehouse_code(self, obj):
        """Display warehouse code"""
        return obj.warehouse.code
    warehouse_code.short_description = 'Warehouse'
    warehouse_code.admin_order_field = 'warehouse__code'
    
    def available_display(self, obj):
        """Display available quantity with color coding"""
        available = obj.available_quantity
        if available <= 0:
            color = 'red'
        elif available < obj.reorder_point:
            color = 'orange'
        else:
            color = 'green'
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color, available
        )
    available_display.short_description = 'Available'
    available_display.admin_order_field = 'available_quantity'


@admin.register(StockTransaction)
class StockTransactionAdmin(admin.ModelAdmin):
    """Admin interface for StockTransaction model"""
    list_display = [
        'id', 'product_sku', 'warehouse_code', 'transaction_type',
        'quantity_display', 'reference_id', 'created_at'
    ]
    list_filter = ['transaction_type', 'created_at', 'stock__warehouse']
    search_fields = [
        'stock__product__sku', 'stock__product__name',
        'reference_id', 'notes'
    ]
    readonly_fields = ['created_at']
    raw_id_fields = ['stock']
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Transaction Details', {
            'fields': ('stock', 'transaction_type', 'quantity', 'reference_id')
        }),
        ('Additional Information', {
            'fields': ('notes', 'created_at')
        }),
    )
    
    def product_sku(self, obj):
        """Display product SKU"""
        return obj.stock.product.sku
    product_sku.short_description = 'Product SKU'
    product_sku.admin_order_field = 'stock__product__sku'
    
    def warehouse_code(self, obj):
        """Display warehouse code"""
        return obj.stock.warehouse.code
    warehouse_code.short_description = 'Warehouse'
    warehouse_code.admin_order_field = 'stock__warehouse__code'
    
    def quantity_display(self, obj):
        """Display quantity with color coding"""
        if obj.quantity > 0:
            color = 'green'
            sign = '+'
        else:
            color = 'red'
            sign = ''
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}{}</span>',
            color, sign, obj.quantity
        )
    quantity_display.short_description = 'Quantity'
    quantity_display.admin_order_field = 'quantity'
    
    def has_add_permission(self, request):
        """Disable manual creation of transactions"""
        return False
    
    def has_change_permission(self, request, obj=None):
        """Disable editing of transactions"""
        return False