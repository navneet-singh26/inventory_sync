from django.db import transaction, connection
from django.core.cache import cache
from django.db.models import F
from typing import Dict, List, Optional
import logging
from .models import Product, Warehouse, InventoryStock, StockTransaction
from inventory_sync_project.sync_engine.distributed_lock import LockManager, with_product_lock
from prometheus_client import Counter, Histogram

logger = logging.getLogger(__name__)

# Prometheus metrics
stock_update_counter = Counter('inventory_stock_updates_total', 'Total stock updates', ['operation'])
stock_update_duration = Histogram('inventory_stock_update_duration_seconds', 'Stock update duration')


class InventoryService:
    """Core service for inventory operations with distributed locking"""
    
    @staticmethod
    @stock_update_duration.time()
    def get_available_stock(product_id: int, warehouse_id: int = None) -> Dict:
        """
        Get available stock with caching
        
        Args:
            product_id: Product ID
            warehouse_id: Optional warehouse ID
            
        Returns:
            Dict with stock information
        """
        cache_key = f"stock:{product_id}:{warehouse_id or 'all'}"
        cached_stock = cache.get(cache_key)
        
        if cached_stock:
            return cached_stock
        
        if warehouse_id:
            try:
                stock = InventoryStock.objects.select_related('product', 'warehouse').get(
                    product_id=product_id,
                    warehouse_id=warehouse_id
                )
                result = {
                    'product_id': product_id,
                    'warehouse_id': warehouse_id,
                    'available': stock.available_quantity,
                    'reserved': stock.reserved_quantity,
                    'total': stock.quantity
                }
            except InventoryStock.DoesNotExist:
                result = {
                    'product_id': product_id,
                    'warehouse_id': warehouse_id,
                    'available': 0,
                    'reserved': 0,
                    'total': 0
                }
        else:
            stocks = InventoryStock.objects.filter(product_id=product_id)
            result = {
                'product_id': product_id,
                'available': sum(s.available_quantity for s in stocks),
                'reserved': sum(s.reserved_quantity for s in stocks),
                'total': sum(s.quantity for s in stocks),
                'warehouses': [
                    {
                        'warehouse_id': s.warehouse_id,
                        'available': s.available_quantity,
                        'reserved': s.reserved_quantity,
                        'total': s.quantity
                    }
                    for s in stocks
                ]
            }
        
        cache.set(cache_key, result, timeout=60)
        return result
    
    @staticmethod
    @with_product_lock
    @transaction.atomic
    def reserve_stock(product_id: int, warehouse_id: int, quantity: int, order_id: str) -> bool:
        """
        Reserve stock for an order with distributed locking
        
        Args:
            product_id: Product ID
            warehouse_id: Warehouse ID
            quantity: Quantity to reserve
            order_id: Order reference ID
            
        Returns:
            bool: True if reservation successful
        """
        try:
            # Use select_for_update for database-level locking
            stock = InventoryStock.objects.select_for_update().get(
                product_id=product_id,
                warehouse_id=warehouse_id
            )
            
            if stock.available_quantity < quantity:
                logger.warning(f"Insufficient stock for product {product_id} at warehouse {warehouse_id}")
                return False
            
            # Update stock
            stock.reserved_quantity = F('reserved_quantity') + quantity
            stock.save(update_fields=['reserved_quantity', 'updated_at'])
            stock.refresh_from_db()
            
            # Create transaction record
            StockTransaction.objects.create(
                stock=stock,
                transaction_type='RESERVE',
                quantity=quantity,
                reference_id=order_id,
                notes=f"Reserved for order {order_id}"
            )
            
            # Invalidate cache
            cache_key = f"stock:{product_id}:{warehouse_id}"
            cache.delete(cache_key)
            
            stock_update_counter.labels(operation='reserve').inc()
            logger.info(f"Reserved {quantity} units of product {product_id} at warehouse {warehouse_id}")
            
            return True
            
        except InventoryStock.DoesNotExist:
            logger.error(f"Stock not found for product {product_id} at warehouse {warehouse_id}")
            return False
        except Exception as e:
            logger.error(f"Error reserving stock: {e}")
            raise
    
    @staticmethod
    @with_product_lock
    @transaction.atomic
    def release_stock(product_id: int, warehouse_id: int, quantity: int, order_id: str) -> bool:
        """
        Release reserved stock
        
        Args:
            product_id: Product ID
            warehouse_id: Warehouse ID
            quantity: Quantity to release
            order_id: Order reference ID
            
        Returns:
            bool: True if release successful
        """
        try:
            stock = InventoryStock.objects.select_for_update().get(
                product_id=product_id,
                warehouse_id=warehouse_id
            )
            
            if stock.reserved_quantity < quantity:
                logger.warning(f"Cannot release more than reserved for product {product_id}")
                return False
            
            stock.reserved_quantity = F('reserved_quantity') - quantity
            stock.save(update_fields=['reserved_quantity', 'updated_at'])
            stock.refresh_from_db()
            
            StockTransaction.objects.create(
                stock=stock,
                transaction_type='RELEASE',
                quantity=quantity,
                reference_id=order_id,
                notes=f"Released from order {order_id}"
            )
            
            cache_key = f"stock:{product_id}:{warehouse_id}"
            cache.delete(cache_key)
            
            stock_update_counter.labels(operation='release').inc()
            logger.info(f"Released {quantity} units of product {product_id} at warehouse {warehouse_id}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error releasing stock: {e}")
            raise
    
    @staticmethod
    @with_product_lock
    @transaction.atomic
    def update_stock(product_id: int, warehouse_id: int, quantity: int, 
                    transaction_type: str = 'ADJUST', reference_id: str = '') -> bool:
        """
        Update stock quantity
        
        Args:
            product_id: Product ID
            warehouse_id: Warehouse ID
            quantity: Quantity change (positive or negative)
            transaction_type: Type of transaction
            reference_id: Reference ID for the transaction
            
        Returns:
            bool: True if update successful
        """
        try:
            stock, created = InventoryStock.objects.select_for_update().get_or_create(
                product_id=product_id,
                warehouse_id=warehouse_id,
                defaults={'quantity': 0, 'reserved_quantity': 0}
            )
            
            new_quantity = stock.quantity + quantity
            
            if new_quantity < 0:
                logger.warning(f"Cannot set negative stock for product {product_id}")
                return False
            
            stock.quantity = new_quantity
            stock.save(update_fields=['quantity', 'updated_at'])
            stock.refresh_from_db()
            
            StockTransaction.objects.create(
                stock=stock,
                transaction_type=transaction_type,
                quantity=quantity,
                reference_id=reference_id,
                notes=f"{transaction_type} operation"
            )
            
            cache_key = f"stock:{product_id}:{warehouse_id}"
            cache.delete(cache_key)
            
            stock_update_counter.labels(operation=transaction_type.lower()).inc()
            logger.info(f"Updated stock for product {product_id} at warehouse {warehouse_id}: {quantity}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error updating stock: {e}")
            raise
    
    @staticmethod
    def get_low_stock_products(threshold: int = 10) -> List[Dict]:
        """
        Get products with low stock using materialized view
        
        Args:
            threshold: Stock threshold
            
        Returns:
            List of products with low stock
        """
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT sku, name, warehouse_code, warehouse_name, available_quantity
                FROM inventory_low_stock_alert
                WHERE available_quantity < %s
                ORDER BY available_quantity ASC
            """, [threshold])
            
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]