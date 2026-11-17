from django import forms

from .models import Ticket


class TicketForm(forms.ModelForm):
    class Meta:
        model = Ticket
        fields = ("title", "category", "priority", "description")
        widgets = {"description": forms.Textarea(attrs={"rows": 6})}

    def __init__(self, *args, user=None, editing=False, **kwargs):
        super().__init__(*args, **kwargs)
        # після створення пріоритет може змінювати лише менеджер
        if editing and not (user and user.is_manager):
            del self.fields["priority"]
