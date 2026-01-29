from django.db import connection
import logging

logger = logging.getLogger(__name__)

class InventoryMaterializedViews:
    """Manages materialized views for optimized read performance"""

    @staticmethod
    def create_aggregated_stock_view():
        """Creates materialized view for aggregated stock across warehouses"""
        with connection.cursor() as cursor:
            # Drop existing view if it exists (for clean recreation)
            cursor.execute("""
                DROP MATERIALIZED VIEW IF EXISTS inventory_aggregated_stock CASCADE;
            """)
            
            # Create materialized view with proper NULL handling
            cursor.execute("""
                CREATE MATERIALIZED VIEW inventory_aggregated_stock AS
                SELECT 
                    p.id as product_id,
                    p.sku,
                    p.name,
                    p.category,
                    COALESCE(SUM(s.quantity), 0) as total_quantity,
                    COALESCE(SUM(s.reserved_quantity), 0) as total_reserved,
                    COALESCE(SUM(s.available_quantity), 0) as total_available,
                    COUNT(s.warehouse_id) as warehouse_count,
                    COALESCE(MAX(s.updated_at), p.updated_at) as last_updated,
                    p.created_at,
                    p.updated_at as product_updated_at
                FROM inventory_product p
                LEFT JOIN inventory_inventorystock s ON p.id = s.product_id
                WHERE p.is_active = true
                GROUP BY p.id, p.sku, p.name, p.category, p.created_at, p.updated_at
                WITH DATA;
            """)
            
            # Create unique index IMMEDIATELY after view creation (required for CONCURRENT refresh)
            cursor.execute("""
                CREATE UNIQUE INDEX idx_agg_stock_product_id 
                ON inventory_aggregated_stock(product_id);
            """)
            
            # Create additional indexes for common queries
            cursor.execute("""
                CREATE INDEX idx_agg_stock_sku 
                ON inventory_aggregated_stock(sku);
                
                CREATE INDEX idx_agg_stock_category 
                ON inventory_aggregated_stock(category);
                
                CREATE INDEX idx_agg_stock_available 
                ON inventory_aggregated_stock(total_available);
                
                CREATE INDEX idx_agg_stock_low_stock 
                ON inventory_aggregated_stock(total_available) 
                WHERE total_available < 10;
            """)
            
            logger.info("Aggregated stock materialized view created successfully")

    @staticmethod
    def create_low_stock_alert_view():
        """Creates materialized view for low stock alerts"""
        with connection.cursor() as cursor:
            # Drop existing view if it exists
            cursor.execute("""
                DROP MATERIALIZED VIEW IF EXISTS inventory_low_stock_alert CASCADE;
            """)
            
            cursor.execute("""
                CREATE MATERIALIZED VIEW inventory_low_stock_alert AS
                SELECT 
                    s.id,
                    s.product_id,
                    p.sku,
                    p.name,
                    p.category,
                    s.warehouse_id,
                    w.code as warehouse_code,
                    w.name as warehouse_name,
                    s.quantity,
                    s.available_quantity,
                    s.reserved_quantity,
                    s.updated_at,
                    CASE 
                        WHEN s.available_quantity = 0 THEN 'OUT_OF_STOCK'
                        WHEN s.available_quantity < 5 THEN 'CRITICAL'
                        WHEN s.available_quantity < 10 THEN 'LOW'
                        ELSE 'WARNING'
                    END as alert_level
                FROM inventory_inventorystock s
                JOIN inventory_product p ON s.product_id = p.id
                JOIN inventory_warehouse w ON s.warehouse_id = w.id
                WHERE s.available_quantity < 10 
                AND p.is_active = true 
                AND w.is_active = true
                WITH DATA;
            """)
            
            # Create unique index for CONCURRENT refresh
            cursor.execute("""
                CREATE UNIQUE INDEX idx_low_stock_id 
                ON inventory_low_stock_alert(id);
            """)
            
            # Create additional indexes
            cursor.execute("""
                CREATE INDEX idx_low_stock_warehouse 
                ON inventory_low_stock_alert(warehouse_code);
                
                CREATE INDEX idx_low_stock_sku 
                ON inventory_low_stock_alert(sku);
                
                CREATE INDEX idx_low_stock_alert_level 
                ON inventory_low_stock_alert(alert_level);
                
                CREATE INDEX idx_low_stock_product_warehouse 
                ON inventory_low_stock_alert(product_id, warehouse_id);
            """)
            
            logger.info("Low stock alert materialized view created successfully")

    @staticmethod
    def refresh_inventory_summary():
        """Refresh aggregated stock view with error handling"""
        try:
            with connection.cursor() as cursor:
                # Use CONCURRENTLY to avoid locking the view during refresh
                cursor.execute("""
                    REFRESH MATERIALIZED VIEW CONCURRENTLY inventory_aggregated_stock;
                """)
            logger.info("Inventory summary view refreshed successfully")
        except Exception as e:
            logger.error(f"Error refreshing inventory summary view: {e}")
            # Fallback to non-concurrent refresh if concurrent fails
            try:
                with connection.cursor() as cursor:
                    cursor.execute("""
                        REFRESH MATERIALIZED VIEW inventory_aggregated_stock;
                    """)
                logger.warning("Inventory summary view refreshed (non-concurrent)")
            except Exception as fallback_error:
                logger.error(f"Fallback refresh also failed: {fallback_error}")
                raise

    @staticmethod
    def refresh_low_stock_alert():
        """Refresh low stock alert view with error handling"""
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    REFRESH MATERIALIZED VIEW CONCURRENTLY inventory_low_stock_alert;
                """)
            logger.info("Low stock alert view refreshed successfully")
        except Exception as e:
            logger.error(f"Error refreshing low stock alert view: {e}")
            # Fallback to non-concurrent refresh
            try:
                with connection.cursor() as cursor:
                    cursor.execute("""
                        REFRESH MATERIALIZED VIEW inventory_low_stock_alert;
                    """)
                logger.warning("Low stock alert view refreshed (non-concurrent)")
            except Exception as fallback_error:
                logger.error(f"Fallback refresh also failed: {fallback_error}")
                raise

    @staticmethod
    def refresh_all_views():
        """Refresh all materialized views"""
        InventoryMaterializedViews.refresh_inventory_summary()
        InventoryMaterializedViews.refresh_low_stock_alert()
        logger.info("All materialized views refreshed successfully")

    @staticmethod
    def drop_all_views():
        """Drop all materialized views (useful for migrations)"""
        with connection.cursor() as cursor:
            cursor.execute("""
                DROP MATERIALIZED VIEW IF EXISTS inventory_low_stock_alert CASCADE;
                DROP MATERIALIZED VIEW IF EXISTS inventory_aggregated_stock CASCADE;
            """)
        logger.info("All materialized views dropped successfully")

    @staticmethod
    def get_view_stats():
        """Get statistics about materialized views"""
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT 
                    schemaname,
                    matviewname,
                    pg_size_pretty(pg_total_relation_size(schemaname||'.'||matviewname)) as size,
                    last_refresh
                FROM pg_matviews
                WHERE matviewname IN ('inventory_aggregated_stock', 'inventory_low_stock_alert')
                ORDER BY matviewname;
            """)
            
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]