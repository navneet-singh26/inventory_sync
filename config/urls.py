
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/inventory/', include('inventory.urls')),
    path('api/marketplace/', include('marketplace.urls')),
    path('', include('django_prometheus.urls')),
]