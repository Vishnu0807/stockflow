from django import forms
from .models import Product


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ['sku', 'name', 'price', 'on_hand', 'reorder_point']
        labels = {'on_hand': 'Opening stock', 'reorder_point': 'Low-stock threshold'}


class AdjustmentForm(forms.Form):
    delta = forms.IntegerField(min_value=-100000, max_value=100000, label='Quantity change',
                               help_text='Positive to receive stock; negative to remove it.')
    reason = forms.CharField(max_length=200)
