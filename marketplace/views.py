
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from .services import MarketplaceService
import logging

logger = logging.getLogger(__name__)


class MarketplaceStockView(APIView):
    """API view for marketplace stock operations"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request, marketplace_name, sku):
        """Get stock from marketplace"""
        try:
            marketplace_service = MarketplaceService(marketplace_name)
            stock = marketplace_service.get_stock(sku)
            
            if stock is not None:
                return Response({
                    'marketplace': marketplace_name,
                    'sku': sku,
                    'stock': stock
                })
            else:
                return Response(
                    {'error': 'Failed to retrieve stock'},
                    status=status.HTTP_404_NOT_FOUND
                )
                
        except Exception as e:
            logger.error(f"Error getting marketplace stock: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def post(self, request, marketplace_name, sku):
        """Update stock on marketplace"""
        quantity = request.data.get('quantity')
        
        if quantity is None:
            return Response(
                {'error': 'quantity is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            marketplace_service = MarketplaceService(marketplace_name)
            success = marketplace_service.update_stock(sku, int(quantity))
            
            if success:
                return Response({
                    'status': 'success',
                    'marketplace': marketplace_name,
                    'sku': sku,
                    'quantity': quantity
                })
            else:
                return Response(
                    {'error': 'Failed to update stock'},
                    status=status.HTTP_400_BAD_REQUEST
                )
                
        except Exception as e:
            logger.error(f"Error updating marketplace stock: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class MarketplaceConfigView(APIView):
    """API view for marketplace configuration"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request, marketplace_name):
        """Get marketplace configuration"""
        try:
            marketplace_service = MarketplaceService(marketplace_name)
            
            # Return sanitized config (without sensitive data)
            config = {
                'marketplace': marketplace_name,
                'api_url': marketplace_service.config.get('api_url'),
                'enabled': True
            }
            
            return Response(config)
            
        except Exception as e:
            logger.error(f"Error getting marketplace config: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )