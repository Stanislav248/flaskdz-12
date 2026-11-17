from django.contrib import admin

from .models import Category, Comment, Ticket

admin.site.register(Category)
admin.site.register(Comment)


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "status", "priority", "author", "assignee", "created_at")
    list_filter = ("status", "priority", "category")
    search_fields = ("title",)
