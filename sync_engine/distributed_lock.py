import redis
import time
import uuid
from typing import Optional, Callable
from functools import wraps
from django.conf import settings
from redis.lock import Lock as RedisLock
import logging

logger = logging.getLogger(__name__)

class RedlockException(Exception):
    """Exception raised when lock acquisition fails"""
    pass


class DistributedLock:
    """
    Implements Redlock algorithm for distributed locking across Redis instances.
    Ensures 100% inventory accuracy during high-concurrency scenarios like flash sales.
    """
    
    def __init__(self, resource_name: str, ttl: int = None, retry_times: int = 3, retry_delay: float = None):
        """
        Initialize distributed lock
        
        Args:
            resource_name: Unique identifier for the resource to lock
            ttl: Time to live for the lock in seconds
            retry_times: Number of times to retry acquiring the lock
            retry_delay: Delay between retries in seconds
        """
        self.resource_name = resource_name
        self.ttl = ttl or settings.LOCK_TIMEOUT
        self.retry_times = retry_times
        self.retry_delay = retry_delay or settings.LOCK_RETRY_DELAY
        self.lock_id = str(uuid.uuid4())
        self.redis_clients = self._initialize_redis_clients()
        self.quorum = len(self.redis_clients) // 2 + 1
        self.clock_drift_factor = 0.01
        self.acquired_locks = []
        
    def _initialize_redis_clients(self):
        """Initialize Redis clients for each server in the cluster"""
        clients = []
        for server_config in settings.REDLOCK_SERVERS:
            client = redis.StrictRedis(
                host=server_config['host'],
                port=server_config['port'],
                db=server_config['db'],
                decode_responses=True,
                socket_timeout=5,
                socket_connect_timeout=5,
                retry_on_timeout=True
            )
            clients.append(client)
        return clients
    
    def _acquire_lock_on_instance(self, client: redis.StrictRedis) -> bool:
        """
        Attempt to acquire lock on a single Redis instance
        
        Args:
            client: Redis client instance
            
        Returns:
            bool: True if lock acquired, False otherwise
        """
        try:
            # Use SET with NX (only set if not exists) and PX (expire in milliseconds)
            result = client.set(
                self.resource_name,
                self.lock_id,
                nx=True,
                px=int(self.ttl * 1000)
            )
            return result is True
        except Exception as e:
            logger.error(f"Error acquiring lock on Redis instance: {e}")
            return False
    
    def _release_lock_on_instance(self, client: redis.StrictRedis) -> bool:
        """
        Release lock on a single Redis instance using Lua script for atomicity
        
        Args:
            client: Redis client instance
            
        Returns:
            bool: True if lock released, False otherwise
        """
        lua_script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
        """
        try:
            result = client.eval(lua_script, 1, self.resource_name, self.lock_id)
            return result == 1
        except Exception as e:
            logger.error(f"Error releasing lock on Redis instance: {e}")
            return False
    
    def acquire(self) -> bool:
        """
        Acquire distributed lock using Redlock algorithm
        
        Returns:
            bool: True if lock acquired successfully, False otherwise
        """
        for attempt in range(self.retry_times):
            acquired_count = 0
            start_time = time.time()
            self.acquired_locks = []
            
            # Try to acquire lock on all Redis instances
            for client in self.redis_clients:
                if self._acquire_lock_on_instance(client):
                    acquired_count += 1
                    self.acquired_locks.append(client)
            
            # Calculate elapsed time and drift
            elapsed_time = time.time() - start_time
            drift = (self.ttl * self.clock_drift_factor) + 0.002
            validity_time = self.ttl - elapsed_time - drift
            
            # Check if we have quorum and lock is still valid
            if acquired_count >= self.quorum and validity_time > 0:
                logger.info(f"Lock acquired for resource: {self.resource_name}")
                return True
            else:
                # Release all acquired locks if quorum not reached
                self._release_all_locks()
                
            # Wait before retry
            if attempt < self.retry_times - 1:
                time.sleep(self.retry_delay)
        
        logger.warning(f"Failed to acquire lock for resource: {self.resource_name}")
        return False
    
    def _release_all_locks(self):
        """Release locks on all instances where lock was acquired"""
        for client in self.acquired_locks:
            self._release_lock_on_instance(client)
        self.acquired_locks = []
    
    def release(self):
        """Release the distributed lock"""
        self._release_all_locks()
        logger.info(f"Lock released for resource: {self.resource_name}")
    
    def __enter__(self):
        """Context manager entry"""
        if not self.acquire():
            raise RedlockException(f"Failed to acquire lock for resource: {self.resource_name}")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.release()
        return False


class LockManager:
    """Manages distributed locks for inventory operations"""
    
    @staticmethod
    def get_product_lock(product_id: int, warehouse_id: int = None) -> DistributedLock:
        """
        Get a distributed lock for a specific product
        
        Args:
            product_id: Product ID
            warehouse_id: Optional warehouse ID for warehouse-specific lock
            
        Returns:
            DistributedLock instance
        """
        if warehouse_id:
            resource_name = f"inventory:product:{product_id}:warehouse:{warehouse_id}"
        else:
            resource_name = f"inventory:product:{product_id}"
        
        return DistributedLock(resource_name)
    
    @staticmethod
    def get_warehouse_lock(warehouse_id: int) -> DistributedLock:
        """
        Get a distributed lock for a specific warehouse
        
        Args:
            warehouse_id: Warehouse ID
            
        Returns:
            DistributedLock instance
        """
        resource_name = f"inventory:warehouse:{warehouse_id}"
        return DistributedLock(resource_name)
    
    @staticmethod
    def get_order_lock(order_id: str) -> DistributedLock:
        """
        Get a distributed lock for a specific order
        
        Args:
            order_id: Order ID
            
        Returns:
            DistributedLock instance
        """
        resource_name = f"inventory:order:{order_id}"
        return DistributedLock(resource_name)
    
    @staticmethod
    def get_flash_sale_lock(product_id: int) -> DistributedLock:
        """
        Get a distributed lock for flash sale operations
        
        Args:
            product_id: Product ID
            
        Returns:
            DistributedLock instance with shorter TTL for high-concurrency
        """
        resource_name = f"inventory:flashsale:{product_id}"
        return DistributedLock(resource_name, ttl=5, retry_times=10, retry_delay=0.05)


def with_distributed_lock(lock_key_func: Callable):
    """
    Decorator to automatically acquire and release distributed lock
    
    Args:
        lock_key_func: Function that takes the decorated function's arguments
                      and returns the lock resource name
    
    Example:
        @with_distributed_lock(lambda product_id, warehouse_id: f"inventory:product:{product_id}:warehouse:{warehouse_id}")
        def update_stock(product_id, warehouse_id, quantity):
            # Your code here
            pass
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Get lock resource name from the key function
            resource_name = lock_key_func(*args, **kwargs)
            lock = DistributedLock(resource_name)
            
            try:
                with lock:
                    return func(*args, **kwargs)
            except RedlockException as e:
                logger.error(f"Lock acquisition failed: {e}")
                raise
        
        return wrapper
    return decorator


# Convenience decorators for common lock patterns
def with_product_lock(func):
    """Decorator for product-level locking"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        product_id = kwargs.get('product_id') or args[0]
        warehouse_id = kwargs.get('warehouse_id')
        
        lock = LockManager.get_product_lock(product_id, warehouse_id)
        
        try:
            with lock:
                return func(*args, **kwargs)
        except RedlockException as e:
            logger.error(f"Product lock acquisition failed: {e}")
            raise
    
    return wrapper


def with_warehouse_lock(func):
    """Decorator for warehouse-level locking"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        warehouse_id = kwargs.get('warehouse_id') or args[0]
        
        lock = LockManager.get_warehouse_lock(warehouse_id)
        
        try:
            with lock:
                return func(*args, **kwargs)
        except RedlockException as e:
            logger.error(f"Warehouse lock acquisition failed: {e}")
            raise
    
    return wrapper


def with_flash_sale_lock(func):
    """Decorator for flash sale operations with optimized lock settings"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        product_id = kwargs.get('product_id') or args[0]
        
        lock = LockManager.get_flash_sale_lock(product_id)
        
        try:
            with lock:
                return func(*args, **kwargs)
        except RedlockException as e:
            logger.error(f"Flash sale lock acquisition failed: {e}")
            raise
    
    return wrapper