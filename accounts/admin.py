from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("Helpdesk", {"fields": ("role", "phone", "bio")}),)
    list_display = ("username", "email", "role", "is_active")
    list_filter = ("role", "is_active")
