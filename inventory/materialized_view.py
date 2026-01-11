from django.db import connection

class InventoryMaterializedViews:
    """Manages materialized views for optimized read performance"""

    @staticmethod
    def create_aggregated_stock_view():
        """Creates materialized view for aggregated stock across warehouses"""
        with connection.cursor() as cursor:
            cursor.execute("""
                CREATE MATERIALIZED VIEW IF NOT EXISTS inventory_aggregated_stock AS
                SELECT 
                    p.id as product_id,
                    p.sku,
                    p.name,
                    SUM(s.quantity) as total_quantity,
                    SUM(s.reserved_quantity) as total_reserved,
                    SUM(s.available_quantity) as total_available,
                    COUNT(DISTINCT s.warehouse_id) as warehouse_count,
                    MAX(s.updated_at) as last_updated
                FROM inventory_product p
                LEFT JOIN inventory_inventorystock s ON p.id = s.product_id
                WHERE p.is_active = true
                GROUP BY p.id, p.sku, p.name
                WITH DATA;
                
                CREATE UNIQUE INDEX IF NOT EXISTS idx_agg_stock_product_id 
                ON inventory_aggregated_stock(product_id);
                
                CREATE INDEX IF NOT EXISTS idx_agg_stock_sku 
                ON inventory_aggregated_stock(sku);
                
                CREATE INDEX IF NOT EXISTS idx_agg_stock_available 
                ON inventory_aggregated_stock(total_available);
            """)

    @staticmethod
    def create_low_stock_alert_view():
        """Creates materialized view for low stock alerts"""
        with connection.cursor() as cursor:
            cursor.execute("""
                CREATE MATERIALIZED VIEW IF NOT EXISTS inventory_low_stock_alert AS
                SELECT 
                    s.id,
                    p.sku,
                    p.name,
                    w.code as warehouse_code,
                    w.name as warehouse_name,
                    s.available_quantity,
                    s.reserved_quantity,
                    s.updated_at
                FROM inventory_inventorystock s
                JOIN inventory_product p ON s.product_id = p.id
                JOIN inventory_warehouse w ON s.warehouse_id = w.id
                WHERE s.available_quantity < 10 
                AND p.is_active = true 
                AND w.is_active = true
                WITH DATA;
                
                CREATE INDEX IF NOT EXISTS idx_low_stock_warehouse 
                ON inventory_low_stock_alert(warehouse_code);
                
                CREATE INDEX IF NOT EXISTS idx_low_stock_sku 
                ON inventory_low_stock_alert(sku);
            """)

    @staticmethod
    def refresh_all_views():
        """Refresh all materialized views"""
        with connection.cursor() as cursor:
            cursor.execute("""
                REFRESH MATERIALIZED VIEW CONCURRENTLY inventory_aggregated_stock;
                REFRESH MATERIALIZED VIEW CONCURRENTLY inventory_low_stock_alert;
            """)