
# Inventory Sync System

A distributed inventory management and synchronization system built with Django, Celery, and Redis. Supports multi-warehouse inventory tracking and real-time synchronization with multiple e-commerce marketplaces (Amazon, eBay, Shopify).

## Features

- **Multi-Warehouse Management**: Track inventory across multiple warehouse locations
- **Real-time Synchronization**: Automatic sync with e-commerce marketplaces
- **Distributed Locking**: Prevent race conditions with Redis-based distributed locks
- **Stock Reservation**: Reserve stock for orders with automatic release
- **Low Stock Alerts**: Automated monitoring and alerts for low stock levels
- **Transaction History**: Complete audit trail of all stock movements
- **REST API**: Full-featured API for integration with other systems
- **Monitoring**: Prometheus metrics and Grafana dashboards
- **Async Processing**: Background task processing with Celery

## Architecture
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Django    │────▶│   Celery    │────▶│   Redis     │
│   REST API  │     │   Workers   │     │   Cache     │
└─────────────┘     └─────────────┘     └─────────────┘
       │                    │                    │
       │                    │                    │
       ▼                    ▼                    ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│ PostgreSQL  │     │ Marketplace │     │ Prometheus  │
│  Database   │     │    APIs     │     │  Metrics    │
└─────────────┘     └─────────────┘     └─────────────┘