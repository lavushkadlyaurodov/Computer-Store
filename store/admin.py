from django.contrib import admin
from .models import (
    Customer,
    Product,
    Invoice,
    InvoiceItem,
    SaleDocument,
    DocumentItem
)


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_company', 'contact', 'created_at')
    search_fields = ('name', 'contact')
    list_filter = ('is_company', 'created_at')
    ordering = ('-created_at',)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'price', 'quantity', 'created_at', 'updated_at')
    search_fields = ('name',)
    list_filter = ('created_at', 'updated_at')
    ordering = ('name',)
    fields = ('name', 'price', 'quantity')


class InvoiceItemInline(admin.TabularInline):
    model = InvoiceItem
    extra = 1


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('number', 'date', 'customer', 'is_paid', 'total')
    search_fields = ('number', 'customer__name')
    list_filter = ('date', 'is_paid')
    ordering = ('-date',)
    inlines = [InvoiceItemInline]
    readonly_fields = ('total',)


class DocumentItemInline(admin.TabularInline):
    model = DocumentItem
    extra = 1


@admin.register(SaleDocument)
class SaleDocumentAdmin(admin.ModelAdmin):
    list_display = ('number', 'type', 'date', 'customer', 'total')
    search_fields = ('number', 'customer__name')
    list_filter = ('type', 'date')
    ordering = ('-date',)
    inlines = [DocumentItemInline]
    readonly_fields = ('total',)


@admin.register(InvoiceItem)
class InvoiceItemAdmin(admin.ModelAdmin):
    list_display = ('invoice', 'product', 'quantity', 'price', 'created_at')
    search_fields = ('invoice__number', 'product__name')
    list_filter = ('created_at',)
    ordering = ('-created_at',)


@admin.register(DocumentItem)
class DocumentItemAdmin(admin.ModelAdmin):
    list_display = ('document', 'product', 'quantity', 'price')
    search_fields = ('document__number', 'product__name')
    ordering = ('document',)
