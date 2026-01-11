
from django.core.management.base import BaseCommand
from inventory_sync_project.sync_engine.tasks import reconcile_inventory
from inventory.models import Warehouse


class Command(BaseCommand):
    help = 'Reconcile inventory discrepancies'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--warehouse',
            type=int,
            help='Specific warehouse ID to reconcile',
        )
        parser.add_argument(
            '--async',
            action='store_true',
            help='Run reconciliation asynchronously',
        )
    
    def handle(self, *args, **options):
        warehouse_id = options.get('warehouse')
        run_async = options.get('async', False)
        
        if warehouse_id:
            warehouse = Warehouse.objects.get(id=warehouse_id)
            self.stdout.write(f'Reconciling warehouse {warehouse.code}...')
        else:
            self.stdout.write('Reconciling all warehouses...')
        
        if run_async:
            task = reconcile_inventory.delay(warehouse_id)
            self.stdout.write(self.style.SUCCESS(f'Reconciliation task queued: {task.id}'))
        else:
            result = reconcile_inventory(warehouse_id)
            
            self.stdout.write('\nReconciliation Results:')
            self.stdout.write(f"Total checked: {result['total_checked']}")
            self.stdout.write(f"Discrepancies found: {result['discrepancies_found']}")
            self.stdout.write(f"Corrections made: {result['corrections_made']}")
            
            if result['errors']:
                self.stdout.write(self.style.WARNING('\nErrors:'))
                for error in result['errors']:
                    self.stdout.write(self.style.ERROR(f"  - {error}"))
            
            self.stdout.write(self.style.SUCCESS('\nReconciliation completed!'))