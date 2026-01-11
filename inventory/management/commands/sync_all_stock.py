
from django.core.management.base import BaseCommand
from inventory_sync_project.sync_engine.tasks import sync_warehouse_stock, sync_marketplace_stock
from inventory.models import Warehouse
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Synchronize stock across all warehouses and marketplaces'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--warehouse',
            type=int,
            help='Specific warehouse ID to sync',
        )
        parser.add_argument(
            '--marketplace',
            type=str,
            help='Specific marketplace to sync (amazon, ebay, shopify)',
        )
        parser.add_argument(
            '--async',
            action='store_true',
            help='Run synchronization asynchronously',
        )
    
    def handle(self, *args, **options):
        warehouse_id = options.get('warehouse')
        marketplace = options.get('marketplace')
        run_async = options.get('async', False)
        
        if warehouse_id:
            self.stdout.write(f'Syncing warehouse {warehouse_id}...')
            if run_async:
                task = sync_warehouse_stock.delay(warehouse_id)
                self.stdout.write(self.style.SUCCESS(f'Task queued: {task.id}'))
            else:
                result = sync_warehouse_stock(warehouse_id)
                self.stdout.write(self.style.SUCCESS(f'Synced: {result}'))
        
        elif marketplace:
            self.stdout.write(f'Syncing marketplace {marketplace}...')
            if run_async:
                task = sync_marketplace_stock.delay(marketplace)
                self.stdout.write(self.style.SUCCESS(f'Task queued: {task.id}'))
            else:
                result = sync_marketplace_stock(marketplace)
                self.stdout.write(self.style.SUCCESS(f'Synced: {result}'))
        
        else:
            # Sync all warehouses
            warehouses = Warehouse.objects.filter(is_active=True)
            self.stdout.write(f'Syncing {warehouses.count()} warehouses...')
            
            for warehouse in warehouses:
                if run_async:
                    task = sync_warehouse_stock.delay(warehouse.id)
                    self.stdout.write(f'Warehouse {warehouse.code}: Task {task.id}')
                else:
                    result = sync_warehouse_stock(warehouse.id)
                    self.stdout.write(f'Warehouse {warehouse.code}: {result}')
            
            # Sync all marketplaces
            marketplaces = ['amazon', 'ebay', 'shopify']
            self.stdout.write(f'\nSyncing {len(marketplaces)} marketplaces...')
            
            for marketplace in marketplaces:
                if run_async:
                    task = sync_marketplace_stock.delay(marketplace)
                    self.stdout.write(f'Marketplace {marketplace}: Task {task.id}')
                else:
                    try:
                        result = sync_marketplace_stock(marketplace)
                        self.stdout.write(f'Marketplace {marketplace}: {result}')
                    except Exception as e:
                        self.stdout.write(
                            self.style.ERROR(f'Marketplace {marketplace}: Error - {e}')
                        )
            
            self.stdout.write(self.style.SUCCESS('\nAll synchronizations completed!'))