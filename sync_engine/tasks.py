from celery import shared_task, group
from django.db import transaction
from django.utils import timezone
from typing import List, Dict
import logging
from inventory.models import Warehouse, Product, InventoryStock
from inventory.services import InventoryService
from inventory.materialized_views import InventoryMaterializedViews
from marketplace.services import MarketplaceService
from inventory_sync_project.sync_engine.distributed_lock import LockManager
from prometheus_client import Counter, Gauge

logger = logging.getLogger(__name__)

# Prometheus metrics
sync_task_counter = Counter('sync_tasks_total', 'Total sync tasks', ['task_type', 'status'])
sync_duration = Gauge('sync_duration_seconds', 'Sync duration', ['task_type'])
sync_errors = Counter('sync_errors_total', 'Total sync errors', ['task_type'])


@shared_task(bind=True, max_retries=3)
def sync_warehouse_stock(self, warehouse_id: int) -> Dict:
    """
    Synchronize stock for a specific warehouse
    
    Args:
        warehouse_id: Warehouse ID
        
    Returns:
        Dict with sync results
    """
    start_time = timezone.now()
    
    try:
        warehouse = Warehouse.objects.get(id=warehouse_id, is_active=True)
        
        # Acquire warehouse lock
        lock = LockManager.get_warehouse_lock(warehouse_id)
        
        with lock:
            # Simulate fetching stock data from warehouse system
            # In production, this would call warehouse API
            stocks = InventoryStock.objects.filter(warehouse=warehouse).select_related('product')
            
            synced_count = 0
            errors = []
            
            for stock in stocks:
                try:
                    # Update last sync time
                    stock.last_sync_at = timezone.now()
                    stock.save(update_fields=['last_sync_at'])
                    synced_count += 1
                    
                except Exception as e:
                    errors.append(f"Product {stock.product.sku}: {str(e)}")
                    logger.error(f"Error syncing product {stock.product.sku}: {e}")
            
            duration = (timezone.now() - start_time).total_seconds()
            sync_duration.labels(task_type='warehouse').set(duration)
            sync_task_counter.labels(task_type='warehouse', status='success').inc()
            
            result = {
                'warehouse_id': warehouse_id,
                'warehouse_name': warehouse.name,
                'synced_count': synced_count,
                'errors': errors,
                'duration': duration
            }
            
            logger.info(f"Warehouse sync completed: {result}")
            return result
            
    except Warehouse.DoesNotExist:
        sync_task_counter.labels(task_type='warehouse', status='error').inc()
        logger.error(f"Warehouse {warehouse_id} not found")
        raise
    except Exception as e:
        sync_errors.labels(task_type='warehouse').inc()
        logger.error(f"Error syncing warehouse {warehouse_id}: {e}")
        raise self.retry(exc=e, countdown=60)


@shared_task
def sync_all_warehouses() -> Dict:
    """
    Synchronize stock for all active warehouses in parallel
    
    Returns:
        Dict with overall sync results
    """
    warehouses = Warehouse.objects.filter(is_active=True).values_list('id', flat=True)
    
    # Create parallel tasks for each warehouse
    job = group(sync_warehouse_stock.s(wh_id) for wh_id in warehouses)
    result = job.apply_async()
    
    logger.info(f"Started sync for {len(warehouses)} warehouses")
    
    return {
        'task_id': result.id,
        'warehouse_count': len(warehouses),
        'status': 'started'
    }


@shared_task(bind=True, max_retries=3)
def sync_marketplace_stock(self, marketplace_name: str, product_ids: List[int] = None) -> Dict:
    """
    Synchronize stock to marketplace
    
    Args:
        marketplace_name: Name of marketplace (e.g., 'amazon', 'ebay')
        product_ids: Optional list of specific product IDs to sync
        
    Returns:
        Dict with sync results
    """
    start_time = timezone.now()
    
    try:
        marketplace_service = MarketplaceService(marketplace_name)
        
        if product_ids:
            products = Product.objects.filter(id__in=product_ids, is_active=True)
        else:
            products = Product.objects.filter(is_active=True)
        
        synced_count = 0
        errors = []
        
        for product in products:
            try:
                # Get aggregated stock across all warehouses
                stock_info = InventoryService.get_available_stock(product.id)
                
                # Push to marketplace
                success = marketplace_service.update_stock(
                    product.sku,
                    stock_info['available']
                )
                
                if success:
                    synced_count += 1
                else:
                    errors.append(f"Failed to sync {product.sku}")
                    
            except Exception as e:
                errors.append(f"Product {product.sku}: {str(e)}")
                logger.error(f"Error syncing product {product.sku} to {marketplace_name}: {e}")
        
        duration = (timezone.now() - start_time).total_seconds()
        sync_duration.labels(task_type='marketplace').set(duration)
        sync_task_counter.labels(task_type='marketplace', status='success').inc()
        
        result = {
            'marketplace': marketplace_name,
            'synced_count': synced_count,
            'total_products': products.count(),
            'errors': errors,
            'duration': duration
        }
        
        logger.info(f"Marketplace sync completed: {result}")
        return result
        
    except Exception as e:
        sync_errors.labels(task_type='marketplace').inc()
        logger.error(f"Error syncing to marketplace {marketplace_name}: {e}")
        raise self.retry(exc=e, countdown=120)


@shared_task
def sync_all_marketplaces() -> Dict:
    """
    Synchronize stock to all configured marketplaces
    
    Returns:
        Dict with overall sync results
    """
    marketplaces = ['amazon', 'ebay', 'shopify']  # Configure as needed
    
    # Create parallel tasks for each marketplace
    job = group(sync_marketplace_stock.s(marketplace) for marketplace in marketplaces)
    result = job.apply_async()
    
    logger.info(f"Started sync for {len(marketplaces)} marketplaces")
    
    return {
        'task_id': result.id,
        'marketplace_count': len(marketplaces),
        'status': 'started'
    }


@shared_task(bind=True, max_retries=5)
def process_flash_sale_order(self, order_data: Dict) -> Dict:
    """
    Process flash sale order with optimized locking for high concurrency
    
    Args:
        order_data: Order information including product_id, quantity, warehouse_id
        
    Returns:
        Dict with processing result
    """
    product_id = order_data['product_id']
    quantity = order_data['quantity']
    warehouse_id = order_data.get('warehouse_id')
    order_id = order_data['order_id']
    
    try:
        # Use flash sale specific lock with shorter TTL
        lock = LockManager.get_flash_sale_lock(product_id)
        
        with lock:
            # Check stock availability
            stock_info = InventoryService.get_available_stock(product_id, warehouse_id)
            
            if stock_info['available'] < quantity:
                logger.warning(f"Insufficient stock for flash sale order {order_id}")
                return {
                    'order_id': order_id,
                    'status': 'failed',
                    'reason': 'insufficient_stock',
                    'available': stock_info['available'],
                    'requested': quantity
                }
            
            # Reserve stock
            success = InventoryService.reserve_stock(
                product_id=product_id,
                warehouse_id=warehouse_id,
                quantity=quantity,
                order_id=order_id
            )
            
            if success:
                logger.info(f"Flash sale order {order_id} processed successfully")
                return {
                    'order_id': order_id,
                    'status': 'success',
                    'reserved_quantity': quantity
                }
            else:
                return {
                    'order_id': order_id,
                    'status': 'failed',
                    'reason': 'reservation_failed'
                }
                
    except Exception as e:
        logger.error(f"Error processing flash sale order {order_id}: {e}")
        raise self.retry(exc=e, countdown=1)  # Quick retry for flash sales


@shared_task
def refresh_materialized_views() -> Dict:
    """
    Refresh all materialized views for optimized read performance
    
    Returns:
        Dict with refresh results
    """
    start_time = timezone.now()
    
    try:
        # Refresh inventory summary view
        InventoryMaterializedViews.refresh_inventory_summary()
        
        # Refresh low stock alert view
        InventoryMaterializedViews.refresh_low_stock_alert()
        
        duration = (timezone.now() - start_time).total_seconds()
        
        logger.info(f"Materialized views refreshed in {duration} seconds")
        
        return {
            'status': 'success',
            'duration': duration,
            'refreshed_at': timezone.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error refreshing materialized views: {e}")
        raise


@shared_task
def cleanup_old_transactions(days: int = 90) -> Dict:
    """
    Clean up old stock transactions to maintain database performance
    
    Args:
        days: Number of days to keep transactions
        
    Returns:
        Dict with cleanup results
    """
    from inventory.models import StockTransaction
    
    cutoff_date = timezone.now() - timezone.timedelta(days=days)
    
    try:
        deleted_count, _ = StockTransaction.objects.filter(
            created_at__lt=cutoff_date
        ).delete()
        
        logger.info(f"Cleaned up {deleted_count} old transactions")
        
        return {
            'status': 'success',
            'deleted_count': deleted_count,
            'cutoff_date': cutoff_date.isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error cleaning up transactions: {e}")
        raise


@shared_task(bind=True)
def reconcile_inventory(self, warehouse_id: int = None) -> Dict:
    """
    Reconcile inventory discrepancies between system and actual stock
    
    Args:
        warehouse_id: Optional warehouse ID to reconcile specific warehouse
        
    Returns:
        Dict with reconciliation results
    """
    try:
        if warehouse_id:
            stocks = InventoryStock.objects.filter(warehouse_id=warehouse_id)
        else:
            stocks = InventoryStock.objects.all()
        
        discrepancies = []
        reconciled_count = 0
        
        for stock in stocks:
            # Check if available quantity matches (quantity - reserved)
            expected_available = stock.quantity - stock.reserved_quantity
            
            if stock.available_quantity != expected_available:
                discrepancies.append({
                    'product_sku': stock.product.sku,
                    'warehouse': stock.warehouse.code,
                    'system_available': stock.available_quantity,
                    
                    'calculated_available': expected_available,
                    'difference': stock.available_quantity - expected_available
                })
                
                # Auto-fix the discrepancy
                stock.available_quantity = expected_available
                stock.save(update_fields=['available_quantity'])
                reconciled_count += 1
                
                logger.warning(f"Reconciled stock for {stock.product.sku} at {stock.warehouse.code}")
        
        logger.info(f"Inventory reconciliation completed: {reconciled_count} discrepancies fixed")
        
        return {
            'status': 'success',
            'reconciled_count': reconciled_count,
            'discrepancies': discrepancies,
            'total_checked': stocks.count()
        }
        
    except Exception as e:
        logger.error(f"Error reconciling inventory: {e}")
        raise


@shared_task
def generate_stock_report(warehouse_id: int = None, format: str = 'json') -> Dict:
    """
    Generate comprehensive stock report
    
    Args:
        warehouse_id: Optional warehouse ID for specific warehouse report
        format: Report format ('json', 'csv')
        
    Returns:
        Dict with report data
    """
    try:
        if warehouse_id:
            stocks = InventoryStock.objects.filter(
                warehouse_id=warehouse_id
            ).select_related('product', 'warehouse')
        else:
            stocks = InventoryStock.objects.all().select_related('product', 'warehouse')
        
        report_data = []
        total_value = 0
        
        for stock in stocks:
            item_value = stock.quantity * stock.product.price
            total_value += item_value
            
            report_data.append({
                'sku': stock.product.sku,
                'name': stock.product.name,
                'warehouse': stock.warehouse.code,
                'quantity': stock.quantity,
                'reserved': stock.reserved_quantity,
                'available': stock.available_quantity,
                'unit_price': float(stock.product.price),
                'total_value': float(item_value),
                'last_sync': stock.last_sync_at.isoformat() if stock.last_sync_at else None
            })
        
        return {
            'status': 'success',
            'report_date': timezone.now().isoformat(),
            'total_items': len(report_data),
            'total_value': float(total_value),
            'data': report_data
        }
        
    except Exception as e:
        logger.error(f"Error generating stock report: {e}")
        raise


@shared_task(bind=True, max_retries=3)
def handle_stock_alert(self, product_id: int, warehouse_id: int, alert_type: str) -> Dict:
    """
    Handle stock alerts (low stock, out of stock, etc.)
    
    Args:
        product_id: Product ID
        warehouse_id: Warehouse ID
        alert_type: Type of alert ('low_stock', 'out_of_stock', 'overstock')
        
    Returns:
        Dict with alert handling result
    """
    try:
        product = Product.objects.get(id=product_id)
        warehouse = Warehouse.objects.get(id=warehouse_id)
        stock = InventoryStock.objects.get(product=product, warehouse=warehouse)
        
        # Log alert
        logger.warning(
            f"Stock alert: {alert_type} for {product.sku} at {warehouse.code}. "
            f"Available: {stock.available_quantity}"
        )
        
        # In production, this would send notifications via email, SMS, etc.
        # For now, we'll just log and return the alert info
        
        alert_data = {
            'alert_type': alert_type,
            'product_sku': product.sku,
            'product_name': product.name,
            'warehouse_code': warehouse.code,
            'current_stock': stock.available_quantity,
            'reserved_stock': stock.reserved_quantity,
            'timestamp': timezone.now().isoformat()
        }
        
        # Trigger auto-reorder if configured
        if alert_type == 'low_stock' and product.auto_reorder:
            # Trigger reorder task
            logger.info(f"Triggering auto-reorder for {product.sku}")
            # auto_reorder_product.delay(product_id, warehouse_id)
        
        return {
            'status': 'success',
            'alert_data': alert_data
        }
        
    except Exception as e:
        logger.error(f"Error handling stock alert: {e}")
        raise self.retry(exc=e, countdown=60)


@shared_task
def batch_update_stock(updates: List[Dict]) -> Dict:
    """
    Batch update stock for multiple products
    
    Args:
        updates: List of dicts with product_id, warehouse_id, quantity, transaction_type
        
    Returns:
        Dict with batch update results
    """
    results = {
        'success': [],
        'failed': [],
        'total': len(updates)
    }
    
    for update in updates:
        try:
            success = InventoryService.update_stock(
                product_id=update['product_id'],
                warehouse_id=update['warehouse_id'],
                quantity=update['quantity'],
                transaction_type=update.get('transaction_type', 'ADJUST'),
                reference_id=update.get('reference_id', '')
            )
            
            if success:
                results['success'].append(update)
            else:
                results['failed'].append({
                    'update': update,
                    'reason': 'Update returned False'
                })
                
        except Exception as e:
            results['failed'].append({
                'update': update,
                'reason': str(e)
            })
            logger.error(f"Error in batch update for product {update['product_id']}: {e}")
    
    logger.info(
        f"Batch update completed: {len(results['success'])} success, "
        f"{len(results['failed'])} failed"
    )
    
    return results