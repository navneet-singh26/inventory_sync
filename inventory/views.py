
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Q, Sum, F
from django.core.cache import cache
from .models import Product, Warehouse, InventoryStock, StockTransaction
from .serializers import (
    ProductSerializer, WarehouseSerializer, 
    InventoryStockSerializer, StockTransactionSerializer
)
from .services import InventoryService
from inventory_sync_project.sync_engine.tasks import (
    sync_warehouse_stock, sync_marketplace_stock,
    batch_update_stock, reconcile_inventory
)
import logging

logger = logging.getLogger(__name__)


class ProductViewSet(viewsets.ModelViewSet):
    """ViewSet for Product operations"""
    queryset = Product.objects.filter(is_active=True)
    serializer_class = ProductSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Filter products based on query parameters"""
        queryset = super().get_queryset()
        
        # Filter by SKU
        sku = self.request.query_params.get('sku', None)
        if sku:
            queryset = queryset.filter(sku__icontains=sku)
        
        # Filter by name
        name = self.request.query_params.get('name', None)
        if name:
            queryset = queryset.filter(name__icontains=name)
        
        # Filter by category
        category = self.request.query_params.get('category', None)
        if category:
            queryset = queryset.filter(category=category)
        
        return queryset.order_by('-created_at')
    
    @action(detail=True, methods=['get'])
    def stock_summary(self, request, pk=None):
        """Get stock summary for a product across all warehouses"""
        product = self.get_object()
        stock_info = InventoryService.get_available_stock(product.id)
        
        return Response({
            'product_id': product.id,
            'sku': product.sku,
            'name': product.name,
            'stock_info': stock_info
        })
    
    @action(detail=True, methods=['post'])
    def reserve_stock(self, request, pk=None):
        """Reserve stock for a product"""
        product = self.get_object()
        warehouse_id = request.data.get('warehouse_id')
        quantity = request.data.get('quantity')
        order_id = request.data.get('order_id')
        
        if not all([warehouse_id, quantity, order_id]):
            return Response(
                {'error': 'warehouse_id, quantity, and order_id are required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            success = InventoryService.reserve_stock(
                product_id=product.id,
                warehouse_id=warehouse_id,
                quantity=int(quantity),
                order_id=order_id
            )
            
            if success:
                return Response({
                    'status': 'success',
                    'message': f'Reserved {quantity} units for order {order_id}'
                })
            else:
                return Response(
                    {'error': 'Failed to reserve stock'},
                    status=status.HTTP_400_BAD_REQUEST
                )
                
        except Exception as e:
            logger.error(f"Error reserving stock: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'])
    def release_stock(self, request, pk=None):
        """Release reserved stock for a product"""
        product = self.get_object()
        warehouse_id = request.data.get('warehouse_id')
        quantity = request.data.get('quantity')
        order_id = request.data.get('order_id')
        
        
        if not all([warehouse_id, quantity, order_id]):
            return Response(
                {'error': 'warehouse_id, quantity, and order_id are required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            success = InventoryService.release_stock(
                product_id=product.id,
                warehouse_id=warehouse_id,
                quantity=int(quantity),
                order_id=order_id
            )
            
            if success:
                return Response({
                    'status': 'success',
                    'message': f'Released {quantity} units for order {order_id}'
                })
            else:
                return Response(
                    {'error': 'Failed to release stock'},
                    status=status.HTTP_400_BAD_REQUEST
                )
                
        except Exception as e:
            logger.error(f"Error releasing stock: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class WarehouseViewSet(viewsets.ModelViewSet):
    """ViewSet for Warehouse operations"""
    queryset = Warehouse.objects.filter(is_active=True)
    serializer_class = WarehouseSerializer
    permission_classes = [IsAuthenticated]
    
    @action(detail=True, methods=['get'])
    def inventory(self, request, pk=None):
        """Get all inventory for a warehouse"""
        warehouse = self.get_object()
        stocks = InventoryStock.objects.filter(
            warehouse=warehouse
        ).select_related('product').order_by('-updated_at')
        
        serializer = InventoryStockSerializer(stocks, many=True)
        return Response({
            'warehouse': WarehouseSerializer(warehouse).data,
            'inventory': serializer.data,
            'total_items': stocks.count()
        })
    
    @action(detail=True, methods=['post'])
    def sync_stock(self, request, pk=None):
        """Trigger stock synchronization for a warehouse"""
        warehouse = self.get_object()
        
        try:
            # Trigger async task
            task = sync_warehouse_stock.delay(warehouse.id)
            
            return Response({
                'status': 'success',
                'message': f'Stock sync initiated for warehouse {warehouse.code}',
                'task_id': task.id
            })
            
        except Exception as e:
            logger.error(f"Error triggering warehouse sync: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['get'])
    def low_stock_products(self, request, pk=None):
        """Get low stock products for a warehouse"""
        warehouse = self.get_object()
        threshold = int(request.query_params.get('threshold', 10))
        
        low_stock = InventoryStock.objects.filter(
            warehouse=warehouse,
            available_quantity__lt=threshold
        ).select_related('product').order_by('available_quantity')
        
        serializer = InventoryStockSerializer(low_stock, many=True)
        return Response({
            'warehouse': warehouse.code,
            'threshold': threshold,
            'low_stock_items': serializer.data,
            'count': low_stock.count()
        })


class InventoryStockViewSet(viewsets.ModelViewSet):
    """ViewSet for InventoryStock operations"""
    queryset = InventoryStock.objects.all()
    serializer_class = InventoryStockSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Filter inventory based on query parameters"""
        queryset = super().get_queryset().select_related('product', 'warehouse')
        
        # Filter by product
        product_id = self.request.query_params.get('product_id', None)
        if product_id:
            queryset = queryset.filter(product_id=product_id)
        
        # Filter by warehouse
        warehouse_id = self.request.query_params.get('warehouse_id', None)
        if warehouse_id:
            queryset = queryset.filter(warehouse_id=warehouse_id)
        
        # Filter by low stock
        low_stock = self.request.query_params.get('low_stock', None)
        if low_stock:
            threshold = int(low_stock)
            queryset = queryset.filter(available_quantity__lt=threshold)
        
        return queryset.order_by('-updated_at')
    
    @action(detail=False, methods=['post'])
    def batch_update(self, request):
        """Batch update stock for multiple products"""
        updates = request.data.get('updates', [])
        
        if not updates:
            return Response(
                {'error': 'updates list is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Trigger async task
            task = batch_update_stock.delay(updates)
            
            return Response({
                'status': 'success',
                'message': f'Batch update initiated for {len(updates)} items',
                'task_id': task.id
            })
            
        except Exception as e:
            logger.error(f"Error triggering batch update: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['post'])
    def reconcile(self, request):
        """Reconcile inventory discrepancies"""
        warehouse_id = request.data.get('warehouse_id', None)
        
        try:
            # Trigger async task
            task = reconcile_inventory.delay(warehouse_id)
            
            return Response({
                'status': 'success',
                'message': 'Inventory reconciliation initiated',
                'task_id': task.id
            })
            
        except Exception as e:
            logger.error(f"Error triggering reconciliation: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'])
    def adjust_stock(self, request, pk=None):
        """Manually adjust stock quantity"""
        stock = self.get_object()
        quantity = request.data.get('quantity')
        reason = request.data.get('reason', 'Manual adjustment')
        
        if quantity is None:
            return Response(
                {'error': 'quantity is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            success = InventoryService.update_stock(
                product_id=stock.product_id,
                warehouse_id=stock.warehouse_id,
                quantity=int(quantity),
                transaction_type='ADJUST',
                reference_id=f"manual_adjust_{stock.id}"
            )
            
            if success:
                return Response({
                    'status': 'success',
                    'message': f'Stock adjusted by {quantity} units',
                    'reason': reason
                })
            else:
                return Response(
                    {'error': 'Failed to adjust stock'},
                    status=status.HTTP_400_BAD_REQUEST
                )
                
        except Exception as e:
            logger.error(f"Error adjusting stock: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class StockTransactionViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for StockTransaction operations (read-only)"""
    queryset = StockTransaction.objects.all()
    serializer_class = StockTransactionSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Filter transactions based on query parameters"""
        queryset = super().get_queryset().select_related(
            'stock__product', 'stock__warehouse'
        )
        
        # Filter by product
        product_id = self.request.query_params.get('product_id', None)
        if product_id:
            queryset = queryset.filter(stock__product_id=product_id)
        
        # Filter by warehouse
        warehouse_id = self.request.query_params.get('warehouse_id', None)
        if warehouse_id:
            queryset = queryset.filter(stock__warehouse_id=warehouse_id)
        
        # Filter by transaction type
        transaction_type = self.request.query_params.get('transaction_type', None)
        if transaction_type:
            queryset = queryset.filter(transaction_type=transaction_type)
        
        # Filter by date range
        start_date = self.request.query_params.get('start_date', None)
        if start_date:
            queryset = queryset.filter(created_at__gte=start_date)
        
        end_date = self.request.query_params.get('end_date', None)
        if end_date:
            queryset = queryset.filter(created_at__lte=end_date)
        
        return queryset.order_by('-created_at')
    
    @action(detail=False, methods=['get'])
    def summary(self, request):
        """Get transaction summary statistics"""
        queryset = self.get_queryset()
        
        summary = {
            'total_transactions': queryset.count(),
            'by_type': {}
        }
        
        # Count by transaction type
        from django.db.models import Count
        type_counts = queryset.values('transaction_type').annotate(
            count=Count('id')
        )
        
        for item in type_counts:
            summary['by_type'][item['transaction_type']] = item['count']
        
        return Response(summary)


class SyncViewSet(viewsets.ViewSet):
    """ViewSet for synchronization operations"""
    permission_classes = [IsAuthenticated]
    
    @action(detail=False, methods=['post'])
    def marketplace(self, request):
        """Trigger marketplace synchronization"""
        marketplace_name = request.data.get('marketplace_name')
        product_ids = request.data.get('product_ids', None)
        
        if not marketplace_name:
            return Response(
                {'error': 'marketplace_name is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Trigger async task
            task = sync_marketplace_stock.delay(marketplace_name, product_ids)
            
            return Response({
                'status': 'success',
                'message': f'Marketplace sync initiated for {marketplace_name}',
                'task_id': task.id
            })
            
        except Exception as e:
            logger.error(f"Error triggering marketplace sync: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['get'])
    def status(self, request):
        """Get synchronization status"""
        from celery.result import AsyncResult
        
        task_id = request.query_params.get('task_id')
        
        if not task_id:
            return Response(
                {'error': 'task_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            result = AsyncResult(task_id)
            
            response_data = {
                'task_id': task_id,
                'status': result.state,
                'ready': result.ready(),
                'successful': result.successful() if result.ready() else None
            }
            
            if result.ready():
                if result.successful():
                    response_data['result'] = result.result
                else:
                    response_data['error'] = str(result.info)
            
            return Response(response_data)
            
        except Exception as e:
            logger.error(f"Error getting task status: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )