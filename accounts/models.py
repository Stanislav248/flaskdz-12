from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        CLIENT = "client", "Клієнт"
        AGENT = "agent", "Агент"
        MANAGER = "manager", "Менеджер"

    role = models.CharField("Роль", max_length=10, choices=Role.choices, default=Role.CLIENT)
    phone = models.CharField("Телефон", max_length=30, blank=True)
    bio = models.TextField("Про себе", blank=True)

    def save(self, *args, **kwargs):
        # суперкористувач, створений через createsuperuser, одразу стає менеджером
        if self._state.adding and self.is_superuser:
            self.role = self.Role.MANAGER
        super().save(*args, **kwargs)

    @property
    def is_client(self):
        return self.role == self.Role.CLIENT

    @property
    def is_agent(self):
        return self.role == self.Role.AGENT

    @property
    def is_manager(self):
        return self.role == self.Role.MANAGER

    @property
    def display_name(self):
        return self.get_full_name() or self.username

    def __str__(self):
        return self.display_name
