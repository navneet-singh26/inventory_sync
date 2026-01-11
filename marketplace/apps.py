
from django.apps import AppConfig


class MarketplaceConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'marketplace'
    verbose_name = 'Marketplace Integration'
    
    def ready(self):
        """Initialize marketplace services when app is ready"""
        import logging
        logger = logging.getLogger(__name__)
        logger.info("Marketplace app initialized")