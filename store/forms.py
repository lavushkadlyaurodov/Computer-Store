from django import forms
from django.core.exceptions import ValidationError
from .models import Customer, Product, Invoice, InvoiceItem, SaleDocument, DocumentItem, SalesReport


class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ['name', 'is_company', 'contact']
        widgets = {
            'contact': forms.Textarea(attrs={'rows': 2, 'placeholder': 'Телефон, email и др.'}),
            'name': forms.TextInput(attrs={'placeholder': 'Название организации или ФИО'}),
        }
        labels = {
            'is_company': 'Юридическое лицо',
        }


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ['name', 'price', 'quantity']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Название товара'}),
            'price': forms.NumberInput(attrs={
                'step': '0.01',
                'min': '0',
                'placeholder': 'Цена в руб.'
            }),
            'quantity': forms.NumberInput(attrs={
                'min': '0',
                'placeholder': 'Количество на складе'
            }),
        }


class InvoiceForm(forms.ModelForm):
    class Meta:
        model = Invoice
        fields = ['customer', 'date']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Ограничиваем выбор покупателей только юр. лицами для счетов
        self.fields['customer'].queryset = Customer.objects.filter(is_company=True)


class InvoiceItemForm(forms.ModelForm):
    class Meta:
        model = InvoiceItem
        fields = ['product', 'quantity']
        widgets = {
            'quantity': forms.NumberInput(attrs={'min': '1'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['product'].widget.attrs.update({'class': 'product-select'})

        # Устанавливаем цену товара при выборе
        if 'product' in self.initial:
            product = Product.objects.get(pk=self.initial['product'])
            self.fields['price'] = forms.DecimalField(
                initial=product.price,
                max_digits=10,
                decimal_places=2,
                disabled=True,
                label="Цена"
            )


class SaleDocumentForm(forms.ModelForm):
    class Meta:
        model = SaleDocument
        fields = ['customer', 'date']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        self.doc_type = kwargs.pop('doc_type', None)
        super().__init__(*args, **kwargs)

        # Устанавливаем тип документа
        if self.doc_type:
            self.instance.type = self.doc_type

        # Динамически добавляем специфичные поля в зависимости от типа документа
        if self.doc_type == 'cashless':
            self.fields['invoice'] = forms.ModelChoiceField(
                queryset=Invoice.objects.filter(is_paid=True),
                label="Счет на оплату",
                required=True
            )
        elif self.doc_type == 'cash':
            self.fields['cash_register'] = forms.CharField(
                max_length=50,
                label="Номер кассы/отдела",
                required=True
            )
        elif self.doc_type == 'return':
            self.fields['original_sale'] = forms.ModelChoiceField(
                queryset=SaleDocument.objects.filter(type__in=['cash', 'cashless']),
                label="Оригинальная продажа",
                required=True
            )
            self.fields['reason'] = forms.CharField(
                widget=forms.Textarea(attrs={'rows': 3}),
                label="Причина возврата",
                required=False
            )

    def clean(self):
        cleaned_data = super().clean()
        doc_type = self.doc_type or self.instance.type

        # Валидация для безналичных продаж
        if doc_type == 'cashless':
            invoice = cleaned_data.get('invoice')
            if invoice and not invoice.is_paid:
                raise ValidationError("Выбранный счет не оплачен")

        # Валидация для возвратов
        if doc_type == 'return':
            original_sale = cleaned_data.get('original_sale')
            customer = cleaned_data.get('customer')

            if original_sale and customer != original_sale.customer:
                raise ValidationError("Покупатель должен совпадать с оригинальной продажей")


class DocumentItemForm(forms.ModelForm):
    class Meta:
        model = DocumentItem
        fields = ['product', 'quantity']
        widgets = {
            'quantity': forms.NumberInput(attrs={'min': '1'}),
        }

    def __init__(self, *args, **kwargs):
        self.document = kwargs.pop('document', None)
        super().__init__(*args, **kwargs)

        self.fields['product'].widget.attrs.update({'class': 'product-select'})

        # Устанавливаем цену товара при выборе
        if 'product' in self.initial:
            product = Product.objects.get(pk=self.initial['product'])
            self.fields['price'] = forms.DecimalField(
                initial=product.price,
                max_digits=10,
                decimal_places=2,
                disabled=True,
                label="Цена"
            )

        # Для возвратов: фильтруем товары только из оригинальной продажи
        if self.document and self.document.type == 'return' and self.document.original_sale:
            sold_products = self.document.original_sale.items.values_list('product', flat=True)
            self.fields['product'].queryset = Product.objects.filter(id__in=sold_products)

    def clean_quantity(self):
        quantity = self.cleaned_data['quantity']
        product = self.cleaned_data.get('product')
        document = self.document

        if not product or not document:
            return quantity

        # Проверка доступности товара для продажи
        if document.type in ['cash', 'cashless']:
            if quantity > product.quantity:
                raise ValidationError(
                    f"Недостаточно товара на складе. Доступно: {product.quantity}"
                )

        # Проверка максимального количества для возврата
        if document.type == 'return' and document.original_sale:
            try:
                original_item = document.original_sale.items.get(product=product)
                if quantity > original_item.quantity:
                    raise ValidationError(
                        f"Максимальное количество для возврата: {original_item.quantity}"
                    )
            except DocumentItem.DoesNotExist:
                raise ValidationError("Этот товар отсутствует в оригинальной продаже")

        return quantity


# forms.py
from django import forms

class SalesReportForm(forms.Form):
    REPORT_TYPE_CHOICES = [
        ('', 'Все продажи'),
        ('cash', 'Наличный расчет'),
        ('cashless', 'Безналичный расчет'),
        ('return', 'Возврат товара'),
    ]

    report_type = forms.ChoiceField(
        choices=REPORT_TYPE_CHOICES,
        required=False,
        label="Тип отчета"
    )
    start_date = forms.DateField(
        required=False,
        label="Начальная дата",
        widget=forms.DateInput(attrs={'type': 'date'})
    )
    end_date = forms.DateField(
        required=False,
        label="Конечная дата",
        widget=forms.DateInput(attrs={'type': 'date'})
    )

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')

        if start_date and end_date and start_date > end_date:
            raise forms.ValidationError("Начальная дата не может быть позже конечной")

        return cleaned_data




