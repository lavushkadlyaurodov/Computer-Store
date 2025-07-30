from datetime import timedelta, datetime
from decimal import Decimal

from django.contrib import messages
from django.db.models import Sum, ProtectedError, Case, When, F
from django.forms import inlineformset_factory
from django.http import JsonResponse, HttpResponseRedirect
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import ListView, DetailView, UpdateView, DeleteView
from collections import defaultdict

from .forms import (
    InvoiceForm, InvoiceItemForm,
    SaleDocumentForm, DocumentItemForm, SalesReportForm
)
from .models import Customer, Product, Invoice, SaleDocument, DocumentItem, InvoiceItem

from django.db.models import Value, CharField
from django.db.models.functions import Concat
from django.core.paginator import Paginator
from django.db.models import IntegerField
from django.db.models.functions import Cast, Substr


def home(request):
    today = timezone.now().date()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)

    # исключаем возвраты
    base_qs = SaleDocument.objects.exclude(type='return')

    sales_today = base_qs.filter(date=today).aggregate(total=Sum('total'))['total'] or Decimal('0.00')
    sales_week = base_qs.filter(date__gte=week_ago).aggregate(total=Sum('total'))['total'] or Decimal('0.00')
    sales_month = base_qs.filter(date__gte=month_ago).aggregate(total=Sum('total'))['total'] or Decimal('0.00')
    total_sales_amount = base_qs.aggregate(total=Sum('total'))['total'] or Decimal('0.00')

    total_returns_amount = SaleDocument.objects.filter(type='return').aggregate(
        total=Sum('total')
    )['total'] or Decimal('0.00')

    context = {
        'stats': {
            'sales_today': sales_today,
            'sales_week': sales_week,
            'sales_month': sales_month,
            'total_sales_amount': total_sales_amount,
            'total_returns_amount': total_returns_amount,
        }
    }
    return render(request, 'store/dashboard.html', context)


# Базовые представления
class CustomerListView(ListView):
    model = Customer
    template_name = 'store/customers/list.html'
    context_object_name = 'customers'
    paginate_by = 20


class ProductListView(ListView):
    model = Product
    template_name = 'store/products/list.html'
    context_object_name = 'products'
    paginate_by = 20


# Счета на оплату
def create_invoice(request):
    InvoiceItemFormSet = inlineformset_factory(
        Invoice, InvoiceItem, form=InvoiceItemForm, extra=1, can_delete=False
    )

    if request.method == 'POST':
        form = InvoiceForm(request.POST)
        formset = InvoiceItemFormSet(request.POST, prefix='items')

        if form.is_valid() and formset.is_valid():
            invoice = form.save(commit=False)
            invoice.save()

            instances = formset.save(commit=False)
            for instance in instances:
                instance.invoice = invoice
                instance.save()

            invoice.update_total()
            messages.success(request, f"Счет №{invoice.number} успешно создан.")
            return redirect('invoice_detail', pk=invoice.pk)
    else:
        form = InvoiceForm()
        formset = InvoiceItemFormSet(prefix='items')

    return render(request, 'store/invoices/create.html', {
        'form': form,
        'formset': formset
    })


class InvoiceDetailView(DetailView):
    model = Invoice
    template_name = 'store/invoices/detail.html'
    context_object_name = 'invoice'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['items'] = self.object.items.all()
        return context


def mark_invoice_paid(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    if not invoice.is_paid:
        invoice.is_paid = True
        invoice.save()
        messages.success(request, f"Счет №{invoice.number} помечен как оплаченный")
    return redirect('invoice_detail', pk=invoice.pk)


# Документы продаж


class SaleDocumentDetailView(DetailView):
    model = SaleDocument
    template_name = 'store/documents/detail.html'
    context_object_name = 'document'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['items'] = self.object.items.all()
        return context



TYPE_NAMES = {
    'cash': 'Наличный расчет',
    'cashless': 'Безналичный расчет',
    'return': 'Возврат товара',
}

def sales_report(request):
    form = SalesReportForm(request.GET or None)

    raw_report_data = defaultdict(lambda: {
        'total': Decimal('0.00'),
        'dates': defaultdict(lambda: {'total': Decimal('0.00'), 'documents': []})
    })
    overall_total = Decimal('0.00')

    if form.is_valid():
        report_type = form.cleaned_data['report_type']
        start_date = form.cleaned_data['start_date']
        end_date = form.cleaned_data['end_date']

        docs = SaleDocument.objects.all()

        if report_type:
            docs = docs.filter(type=report_type)
        if start_date:
            docs = docs.filter(date__gte=start_date)
        if end_date:
            docs = docs.filter(date__lte=end_date)

        docs = docs.order_by('type', 'date')

        for doc in docs:
            rd = raw_report_data[doc.type]
            rd['total'] += doc.total

            date_dict = rd['dates'][doc.date]
            date_dict['total'] += doc.total

            date_dict['documents'].append({
                'number': doc.number,
                'date': doc.date,
                'total': doc.total,
            })

            overall_total += doc.total

    # Преобразуем defaultdict в обычные dict для шаблона
    report_data = []
    for sale_type_key, data in raw_report_data.items():
        dates_dict = {}
        for date_key, day_data in data['dates'].items():
            dates_dict[date_key] = {
                'total': day_data['total'],
                'documents': day_data['documents']
            }

        report_data.append({
            'type_key': sale_type_key,
            'type_name': TYPE_NAMES.get(sale_type_key, sale_type_key),
            'total': data['total'],
            'dates': dates_dict,
        })

    context = {
        'form': form,
        'report_data': report_data,
        'overall_total': overall_total,
    }

    return render(request, 'store/reports/sales_report.html', context)




# Вспомогательные API
def get_product_price(request, product_id):
    product = get_object_or_404(Product, pk=product_id)
    return JsonResponse({'price': str(product.price), 'quantity': product.quantity})


def get_customer_invoices(request, customer_id):
    customer = get_object_or_404(Customer, pk=customer_id)
    invoices = customer.invoice_set.filter(is_paid=False).values('id', 'number', 'total')
    return JsonResponse(list(invoices), safe=False)

# Журнал
class DocumentListView(ListView):
    template_name = 'store/documents/document_list.html'
    context_object_name = 'documents'
    paginate_by = 20

    def get_queryset(self):
        qs = SaleDocument.objects.annotate(
            doc_type=Case(
                When(type='cash', then=Value('Наличный')),
                When(type='cashless', then=Value('Безналичный')),
                When(type='return', then=Value('Возврат')),
                default=Value('Неизвестно'),
                output_field=CharField()
            ),
            doc_number=Concat(Value('Документ №'), 'number', output_field=CharField()),
            customer_name=F('customer__name'),
            number_numeric=Cast(Substr('number', 4), IntegerField())
        ).order_by('-date', 'type', 'number_numeric')

        # фильтрация
        doc_type = self.request.GET.get('type')
        start_date = self.request.GET.get('start_date')
        end_date = self.request.GET.get('end_date')
        customer = self.request.GET.get('customer')

        if doc_type:
            qs = qs.filter(type=doc_type)

        if start_date:
            try:
                qs = qs.filter(date__gte=datetime.strptime(start_date, '%Y-%m-%d'))
            except ValueError:
                pass

        if end_date:
            try:
                qs = qs.filter(date__lte=datetime.strptime(end_date, '%Y-%m-%d'))
            except ValueError:
                pass

        if customer:
            qs = qs.filter(customer__name__icontains=customer)

        combined = list(qs.values(
            'id', 'date', 'doc_type', 'doc_number', 'number_numeric', 'total', 'customer_name'
        ))

        return combined


class SaleDocumentUpdateView(UpdateView):
    model = SaleDocument
    fields = '__all__'
    template_name = 'store/documents/edit.html'
    success_url = reverse_lazy('document_list')

class SaleDocumentDeleteView(DeleteView):
    model = SaleDocument
    template_name = 'store/documents/delete.html'
    success_url = reverse_lazy('document_list')

    def post(self, request, *args, **kwargs):
        if hasattr(self, '_already_deleting'):
            return HttpResponseRedirect(self.success_url)
        self._already_deleting = True

        self.object = self.get_object()
        try:
            self.object.delete()
            messages.success(request, "Документ успешно удалён.")
            print(f"Deleted document {self.object.pk}")  # DEBUG
        except ProtectedError:
            messages.error(request, "Нельзя удалить продажу, для которой уже оформлен возврат.")
            print("ProtectedError: document not deleted")  # DEBUG
        finally:
            delattr(self, '_already_deleting')

        return HttpResponseRedirect(self.success_url)


def create_sale_document(request, doc_type):
    DocumentItemFormSet = inlineformset_factory(
        SaleDocument, DocumentItem, form=DocumentItemForm, extra=1, can_delete=False
    )

    if request.method == 'POST':
        form = SaleDocumentForm(request.POST)
        formset = DocumentItemFormSet(request.POST, prefix='items')

        if form.is_valid() and formset.is_valid():
            document = form.save(commit=False)
            document.type = doc_type
            document.save()

            instances = formset.save(commit=False)
            for instance in instances:
                instance.document = document
                if not instance.price:
                    instance.price = instance.product.price
                instance.save()

            document.update_total()
            document.update_product_quantities()

            msg = {
                'cashless': 'Безналичная продажа',
                'cash': 'Товарный чек',
                'return': 'Возврат товара'
            }[doc_type]

            messages.success(request, f"{msg} №{document.number} успешно создан.")
            return redirect('document_list')
    else:
        initial = {'type': doc_type}
        invoice_id = request.GET.get('invoice_id')

        if doc_type == 'cashless' and invoice_id:
            invoice = get_object_or_404(Invoice, pk=invoice_id)
            initial.update({
                'customer': invoice.customer,
                'invoice': invoice,
                'total': invoice.total
            })

        form = SaleDocumentForm(initial=initial)
        formset = DocumentItemFormSet(prefix='items')

    template = {
        'cashless': 'store/documents/noncash_sale_form.html',
        'cash': 'store/documents/cash_sale_form.html',
        'return': 'store/documents/return_form.html'
    }[doc_type]

    return render(request, template, {
        'form': form,
        'formset': formset,
        'doc_type': doc_type
    })
