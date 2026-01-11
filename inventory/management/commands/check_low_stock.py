
from django.core.management.base import BaseCommand
from inventory.services import InventoryService
from tabulate import tabulate


class Command(BaseCommand):
    help = 'Check and display products with low stock'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--threshold',
            type=int,
            default=10,
            help='Stock threshold (default: 10)',
        )
        parser.add_argument(
            '--export',
            type=str,
            help='Export to CSV file',
        )
    
    def handle(self, *args, **options):
        threshold = options['threshold']
        export_file = options.get('export')
        
        self.stdout.write(f'Checking products with stock below {threshold}...\n')
        
        low_stock_products = InventoryService.get_low_stock_products(threshold)
        
        if not low_stock_products:
            self.stdout.write(self.style.SUCCESS('No low stock products found!'))
            return
        
        # Prepare table data
        headers = ['SKU', 'Product', 'Warehouse', 'Available Qty']
        table_data = [
            [
                item['sku'],
                item['name'],
                item['warehouse_code'],
                item['available_quantity']
            ]
            for item in low_stock_products
        ]
        
        # Display table
        self.stdout.write(tabulate(table_data, headers=headers, tablefmt='grid'))
        self.stdout.write(f'\nTotal: {len(low_stock_products)} products with low stock')
        
        # Export to CSV if requested
        if export_file:
            import csv
            with open(export_file, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=low_stock_products[0].keys())
                writer.writeheader()
                writer.writerows(low_stock_products)
            self.stdout.write(self.style.SUCCESS(f'\nExported to {export_file}'))