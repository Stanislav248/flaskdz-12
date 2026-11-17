from django.shortcuts import redirect
from django.urls import path

from . import views

urlpatterns = [
    path("", lambda request: redirect("ticket_list")),
    path("tickets/", views.ticket_list, name="ticket_list"),
    path("tickets/new/", views.ticket_create, name="ticket_create"),
    path("tickets/<int:pk>/", views.ticket_detail, name="ticket_detail"),
    path("tickets/<int:pk>/edit/", views.ticket_edit, name="ticket_edit"),
    path("tickets/<int:pk>/comment/", views.ticket_comment, name="ticket_comment"),
    path("tickets/<int:pk>/status/", views.ticket_status, name="ticket_status"),
    path("tickets/<int:pk>/take/", views.ticket_take, name="ticket_take"),
    path("tickets/<int:pk>/assign/", views.ticket_assign, name="ticket_assign"),
    path("tickets/<int:pk>/priority/", views.ticket_priority, name="ticket_priority"),
    path("manage/users/", views.manage_users, name="manage_users"),
    path("manage/users/<int:pk>/role/", views.manage_user_role, name="manage_user_role"),
    path("manage/users/<int:pk>/toggle/", views.manage_user_toggle, name="manage_user_toggle"),
    path("manage/categories/", views.manage_categories, name="manage_categories"),
    path("manage/categories/<int:pk>/rename/", views.manage_category_rename, name="manage_category_rename"),
    path("manage/categories/<int:pk>/delete/", views.manage_category_delete, name="manage_category_delete"),
    path("manage/stats/", views.manage_stats, name="manage_stats"),
]
