from django.contrib import admin

from .models import Customer


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("id", "full_name", "email", "phone_number", "created_at")
    search_fields = ("full_name", "email", "phone_number")
    list_filter = ("created_at",)
