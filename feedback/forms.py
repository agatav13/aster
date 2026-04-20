from django import forms


class BugReportForm(forms.Form):
    title = forms.CharField(
        label="Tytuł",
        max_length=255,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Krótki opis problemu"}
        ),
    )
    description = forms.CharField(
        label="Opis",
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 5,
                "placeholder": "Co się stało? Jakie kroki prowadzą do błędu?",
            }
        ),
    )
    page_url = forms.URLField(
        required=False,
        assume_scheme="https",
        widget=forms.HiddenInput(),
    )
    website = forms.CharField(
        required=False,
        label="",
        widget=forms.TextInput(
            attrs={
                "class": "honeypot",
                "autocomplete": "off",
                "tabindex": "-1",
                "aria-hidden": "true",
            }
        ),
    )

    def clean_title(self) -> str:
        return self.cleaned_data["title"].strip()

    def clean_description(self) -> str:
        return self.cleaned_data["description"].strip()

    def clean_website(self) -> str:
        value = self.cleaned_data.get("website", "")
        if value:
            raise forms.ValidationError("Wykryto aktywność bota.")
        return value
