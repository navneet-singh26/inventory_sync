from django.db import models
from django.core.validators import MinValueValidator
from django.utils import timezone
from django.contrib.postgres.indexes import BTreeIndex, HashIndex

class Warehouse(models.Model):
    """Represents a physical warehouse location"""
    name = models.CharField(max_length=255, unique=True)
    code = models.CharField(max_length=50, unique=True, db_index=True)
    location = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    priority = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-priority', 'name']
        indexes = [
            models.Index(fields=['code', 'is_active']),
        ]

    def __str__(self):
        return f"{self.name} ({self.code})"


class Product(models.Model):
    """Product master data"""
    sku = models.CharField(max_length=100, unique=True, db_index=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=100, db_index=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['sku', 'is_active']),
            models.Index(fields=['category', 'is_active']),
        ]

    def __str__(self):
        return f"{self.sku} - {self.name}"


class InventoryStock(models.Model):
    """Real-time inventory stock per warehouse"""
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='stocks')
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name='stocks')
    quantity = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    reserved_quantity = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    available_quantity = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    last_sync_at = models.DateTimeField(null=True, blank=True)
    version = models.IntegerField(default=0)  # For optimistic locking
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['product', 'warehouse']]
        indexes = [
            models.Index(fields=['product', 'warehouse']),
            models.Index(fields=['warehouse', 'available_quantity']),
            BTreeIndex(fields=['product', 'available_quantity']),
            HashIndex(fields=['product']),
        ]

    def __str__(self):
        return f"{self.product.sku} @ {self.warehouse.code}: {self.available_quantity}"

    def save(self, *args, **kwargs):
        self.available_quantity = self.quantity - self.reserved_quantity
        self.version += 1
        super().save(*args, **kwargs)


class StockTransaction(models.Model):
    """Audit trail for all stock movements"""
    TRANSACTION_TYPES = [
        ('IN', 'Stock In'),
        ('OUT', 'Stock Out'),
        ('RESERVE', 'Reserve'),
        ('RELEASE', 'Release'),
        ('ADJUST', 'Adjustment'),
        ('SYNC', 'Synchronization'),
    ]

    stock = models.ForeignKey(InventoryStock, on_delete=models.CASCADE, related_name='transactions')
    transaction_type = models.CharField(max_length=10, choices=TRANSACTION_TYPES)
    quantity = models.IntegerField()
    reference_id = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.CharField(max_length=255, default='system')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['stock', '-created_at']),
            models.Index(fields=['reference_id']),
        ]

    def __str__(self):
        return f"{self.transaction_type}: {self.quantity} @ {self.created_at}"