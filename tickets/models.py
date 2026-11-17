from django.conf import settings
from django.db import models


class Category(models.Model):
    name = models.CharField("Назва", max_length=80, unique=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Категорія"
        verbose_name_plural = "Категорії"

    def __str__(self):
        return self.name


class Ticket(models.Model):
    class Status(models.TextChoices):
        NEW = "new", "Нова"
        IN_PROGRESS = "in_progress", "В роботі"
        WAITING = "waiting_client", "Очікує відповіді клієнта"
        RESOLVED = "resolved", "Вирішена"
        CLOSED = "closed", "Закрита"
        REJECTED = "rejected", "Відхилена"

    class Priority(models.IntegerChoices):  # числа - щоб працювало сортування
        LOW = 1, "Низький"
        MEDIUM = 2, "Середній"
        HIGH = 3, "Високий"
        CRITICAL = 4, "Критичний"

    title = models.CharField("Заголовок", max_length=200)
    description = models.TextField("Опис")
    category = models.ForeignKey(Category, verbose_name="Категорія", null=True, blank=True,
                                 on_delete=models.SET_NULL, related_name="tickets")
    priority = models.PositiveSmallIntegerField("Пріоритет", choices=Priority.choices, default=Priority.MEDIUM)
    status = models.CharField("Статус", max_length=20, choices=Status.choices, default=Status.NEW)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Автор", on_delete=models.CASCADE,
                               related_name="tickets_created")
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Виконавець", null=True, blank=True,
                                 on_delete=models.SET_NULL, related_name="tickets_assigned")
    created_at = models.DateTimeField("Створено", auto_now_add=True)
    updated_at = models.DateTimeField("Оновлено", auto_now=True)
    resolved_at = models.DateTimeField("Вирішено", null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Заявка"
        verbose_name_plural = "Заявки"

    def __str__(self):
        return f"#{self.pk} {self.title}"

    @property
    def is_final(self):
        return self.status in (self.Status.CLOSED, self.Status.REJECTED)


class Comment(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="comments")
    body = models.TextField("Коментар")
    is_internal = models.BooleanField("Внутрішній", default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
