"""
URL configuration for backend project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static

# One admin panel for both Driver app and Customer app
admin.site.site_header = "E-Transport Admin"
admin.site.site_title = "E-Transport"
admin.site.index_title = "Logistics platform: Drivers, Customers, Bookings, Settings"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/drivers/", include("drivers.urls")),
    path("api/customers/", include("customers.urls")),
    # Logistics: User booking + Driver booking APIs
    path("api/", include("bookings.urls")),
    # Admin platform settings & analytics
    path("api/admin/", include("core.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
