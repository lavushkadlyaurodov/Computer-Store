from django.urls import path
from . import views
from store.views import sales_report


urlpatterns = [
    path('', views.home, name='home'),  # добавляем главную
    # Списки
    path('customer_list/', views.CustomerListView.as_view(), name='customers'),
    path('product_list/', views.ProductListView.as_view(), name='products'),

    # Счета на оплату
    path('invoices/create/', views.create_invoice, name='invoice_form'),
    #path('invoices/<int:pk>/', views.InvoiceDetailView.as_view(), name='detail'),
    path('invoices/<int:pk>/mark_paid/', views.mark_invoice_paid, name='mark_invoice_paid'),

    # Документы продаж
    path('sale_documents/create/<str:doc_type>/', views.create_sale_document, name='create_sale_document'),
    path('sale_documents/<int:pk>/', views.SaleDocumentDetailView.as_view(), name='detail'),

    # Отчеты
    path('reports/sales/', views.sales_report, name='sales_report'),

    # API
    path('api/products/<int:product_id>/price/', views.get_product_price, name='get_product_price'),
    path('api/customers/<int:customer_id>/invoices/', views.get_customer_invoices, name='get_customer_invoices'),

    # Журнал
    path('journal/', views.DocumentListView.as_view(), name='document_list'),

    path('sale_documents/<int:pk>/edit/', views.SaleDocumentUpdateView.as_view(), name='edit'),
    path('sale_documents/<int:pk>/delete/', views.SaleDocumentDeleteView.as_view(), name='delete'),
]
