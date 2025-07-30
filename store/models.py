from decimal import Decimal
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import Sum, F
from django.urls import reverse
from django.utils import timezone


class Customer(models.Model):
    name = models.CharField(max_length=255, verbose_name="Наименование")
    is_company = models.BooleanField(default=False, verbose_name="Юр.лицо")
    contact = models.CharField(max_length=255, verbose_name="Контакты", blank=True)
    #created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")

    class Meta:
        verbose_name = "Покупатель"
        verbose_name_plural = "Покупатели"
        indexes = [
            models.Index(fields=['name']),
            models.Index(fields=['is_company']),
        ]

    def __str__(self):
        return self.name


class Product(models.Model):
    name = models.CharField(max_length=255, verbose_name="Наименование")
    price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Цена")
    quantity = models.IntegerField(
        validators=[MinValueValidator(0)],
        verbose_name="Остаток",
        default=0
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Дата обновления")

    class Meta:
        verbose_name = "Товар"
        verbose_name_plural = "Товары"
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.price} руб.)"

    def available_quantity(self):
        """Доступное количество для продажи"""
        return self.quantity




class Invoice(models.Model):
    """Счет на оплату (предварительный документ)"""
    number = models.CharField(max_length=20, unique=True, verbose_name="Номер")
    date = models.DateField(default=timezone.now, verbose_name="Дата")
    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        verbose_name="Покупатель"
    )
    is_paid = models.BooleanField(default=False, verbose_name="Оплачен")
    total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name="Сумма"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")

    class Meta:
        verbose_name = "Счет"
        verbose_name_plural = "Счета"
        ordering = ['-date', '-id']
        indexes = [
            models.Index(fields=['date']),
            models.Index(fields=['is_paid']),
        ]

    def __str__(self):
        return f"Счет №{self.number} от {self.date}"

    def get_absolute_url(self):
        return reverse('invoice_detail', args=[str(self.id)])


    def save(self, *args, **kwargs):
        if not self.number:
            last_invoice = Invoice.objects.order_by('-id').first()
            last_num = int(last_invoice.number.split('-')[-1]) if last_invoice else 0
            self.number = f"СЧ-{last_num + 1}"

        # При оплате счета создаем связанную продажу
        if self.is_paid and not hasattr(self, 'sale_document'):
            SaleDocument.objects.create(
                type='cashless',
                customer=self.customer,
                invoice=self,
                total=self.total
            )

        super().save(*args, **kwargs)
    def update_total(self):
        """Обновляет сумму счета на основе позиций"""
        self.total = self.items.aggregate(
            total=Sum(F('price') * F('quantity'))
        )['total'] or Decimal('0.00')
        self.save(update_fields=['total'])

def save(self, *args, **kwargs):
    from django.db import transaction

    self.clean()

    with transaction.atomic():
        if self.pk:
            # Обработка редактирования: вернуть старое количество на склад
            old_item = InvoiceItem.objects.get(pk=self.pk)
            self.product.quantity += old_item.quantity
        # Списываем новое количество
        if self.quantity > self.product.available_quantity():
            raise ValidationError(
                f"Недостаточно товара на складе. Доступно: {self.product.available_quantity()}"
            )
        self.product.quantity -= self.quantity
        self.product.save()

        super().save(*args, **kwargs)
        self.invoice.update_total()

class InvoiceItem(models.Model):
    """Позиция в счете на оплату"""
    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name="Счет"
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        verbose_name="Товар"
    )
    quantity = models.IntegerField(
        validators=[MinValueValidator(1)],
        verbose_name="Количество"
    )
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name="Цена"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")

    class Meta:
        verbose_name = "Позиция счета"
        verbose_name_plural = "Позиции счетов"
        constraints = [
            models.UniqueConstraint(
                fields=['invoice', 'product'],
                name='unique_invoice_product'
            )
        ]

    def __str__(self):
        return f"{self.product.name} - {self.quantity} шт."

    def clean(self):
        # Проверка доступного количества товара
        if self.quantity > self.product.available_quantity():
            raise ValidationError(
                f"Недостаточно товара на складе. Доступно: {self.product.available_quantity()}"
            )

    def save(self, *args, **kwargs):
        from django.db import transaction

        self.clean()

        with transaction.atomic():
            if self.pk:
                # Обработка редактирования: вернуть старое количество на склад
                old_item = InvoiceItem.objects.get(pk=self.pk)
                self.product.quantity += old_item.quantity
            # Списываем новое количество
            if self.quantity > self.product.available_quantity():
                raise ValidationError(
                    f"Недостаточно товара на складе. Доступно: {self.product.available_quantity()}"
                )
            self.product.quantity -= self.quantity
            self.product.save()

            super().save(*args, **kwargs)
            self.invoice.update_total()

    def delete(self, *args, **kwargs):
        from django.db import transaction

        with transaction.atomic():
            # Возвращаем товар на склад при удалении
            self.product.quantity += self.quantity
            self.product.save()

            super().delete(*args, **kwargs)
            self.invoice.update_total()

class SaleDocument(models.Model):
    """Базовый класс для документов продаж"""
    DOC_TYPES = (
        ('cashless', 'Безналичная продажа'),
        ('cash', 'Наличная продажа'),
        ('return', 'Возврат товара'),
    )

    type = models.CharField(
        max_length=10,
        choices=DOC_TYPES,
        verbose_name="Тип"
    )
    number = models.CharField(
        max_length=20,
        unique=True,
        verbose_name="Номер",
        #blank=True
    )
    date = models.DateField(
        default=timezone.now,
        verbose_name="Дата"
    )
    total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name="Сумма"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Дата создания"
    )

    # Для безналичных продаж
    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        verbose_name="Счет",
        related_name='sale_documents'
    )

    # Для наличных продаж
    cash_register = models.CharField(
        max_length=50,
        blank=True,
        verbose_name="Номер кассы/отдела"
    )

    # Для возвратов
    original_sale = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        verbose_name="Оригинальная продажа",
        related_name='returns'
    )
    reason = models.TextField(
        blank=True,
        verbose_name="Причина возврата"
    )

    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        verbose_name="Покупатель"
    )

    class Meta:
        verbose_name = "Документ продажи"
        verbose_name_plural = "Документы продаж"
        ordering = ['-date', '-id']
        indexes = [
            models.Index(fields=['type', 'date']),
            models.Index(fields=['customer']),
        ]

    def __str__(self):
        return f"{self.get_type_display()} №{self.number}"

    def get_absolute_url(self):
        return reverse('detail', args=[str(self.id)])

    def update_total(self):
        """Обновляет сумму документа на основе позиций"""
        self.total = self.items.aggregate(
            total=Sum(F('price') * F('quantity'))
        )['total'] or Decimal('0.00')
        self.save(update_fields=['total'])

    def can_create_return(self):
        """Можно ли создать возврат для этого документа"""
        return self.type in ['cash', 'cashless'] and not self.returns.exists()

    def get_returnable_products(self):
        """Товары, доступные для возврата"""
        if self.type != 'return':
            return self.items.all()
        return Product.objects.none()

    def clean(self):
        # Валидация при создании/обновлении документа

        if self.type == 'cashless' and not self.invoice:
            raise ValidationError("Для безналичной продажи необходимо выбрать счет")

        if self.type == 'cashless' and self.invoice and not self.invoice.is_paid:
            raise ValidationError("Счет должен быть оплачен перед созданием продажи")

        if self.type == 'return' and not self.original_sale:
            raise ValidationError("Для возврата укажите оригинальную продажу")

        if self.type == 'return' and self.original_sale and self.original_sale.type == 'return':
            raise ValidationError("Нельзя создавать возврат на возврат")

        if self.type == 'cash' and not self.cash_register:
            raise ValidationError("Укажите номер кассы/отдела")

        # Проверка доступности товаров для продажи
        if self.type in ['cash', 'cashless']:
            for item in self.items.all():
                if item.quantity > item.product.available_quantity():
                    raise ValidationError(
                        f"Недостаточно товара '{item.product.name}' на складе. "
                        f"Доступно: {item.product.available_quantity()}"
                    )

    def save(self, *args, **kwargs):
        if hasattr(self, '_saving'):
            return  # предотвращаем рекурсию
        self._saving = True  # устанавливаем флаг

        # Генерация номера документа
        if not self.number:
            prefix = {
                'cashless': 'БН',
                'cash': 'ТЧ',
                'return': 'ВР'
            }[self.type]

            last_doc = SaleDocument.objects.filter(
                type=self.type
            ).order_by('-id').first()

            last_num = int(last_doc.number.split('-')[-1]) if last_doc else 0
            self.number = f"{prefix}-{last_num + 1}"

        super().save(*args, **kwargs)

        try:
            self.update_total()  # пересчитать сумму после сохранения
            self.update_product_quantities()  # обновить остатки
        finally:
            delattr(self, '_saving')  # снимаем флаг

    def update_product_quantities(self):
        """Обновляет остатки товаров в зависимости от типа документа"""
        if self.type == 'return':
            # Возврат - увеличиваем остатки
            for item in self.items.all():
                item.product.quantity += item.quantity
                item.product.save()
        elif self.type in ['cash', 'cashless']:
            # Продажа - уменьшаем остатки
            for item in self.items.all():
                item.product.quantity -= item.quantity
                item.product.save()


    def delete(self, *args, **kwargs):
        current_number = self.number
        doc_type = self.type

        with transaction.atomic():
            super().delete(*args, **kwargs)

            try:
                prefix = {
                    'cashless': 'БН',
                    'cash': 'ТЧ',
                    'return': 'ВР'
                }[doc_type]
                current_num = int(current_number.split('-')[-1])
            except (KeyError, ValueError, IndexError):
                return

            # Находим документы с номером больше текущего
            docs_to_update = SaleDocument.objects.filter(
                type=doc_type,
                number__startswith=prefix
            )

            # Фильтруем только документы с номером > current_num
            docs_to_update = [doc for doc in docs_to_update if int(doc.number.split('-')[1]) > current_num]

            if not docs_to_update:
                # Если документов с большим номером нет — ничего не меняем
                return

            for doc in docs_to_update:
                try:
                    prefix, num_str = doc.number.split('-')
                    num = int(num_str)
                    if num > current_num:
                        new_num = num - 1
                        doc.number = f"{prefix}-{new_num}"
                        doc.save(update_fields=['number'])
                except (ValueError, IndexError):
                    continue

    invoice = models.OneToOneField(
        Invoice,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='sale_document'
    )


class DocumentItem(models.Model):
    document = models.ForeignKey(
        SaleDocument,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name="Документ"
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        verbose_name="Товар"
    )
    quantity = models.IntegerField(
        validators=[MinValueValidator(1)],
        verbose_name="Количество"
    )
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name="Цена"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Дата создания"
    )

    class Meta:
        verbose_name = "Позиция документа"
        verbose_name_plural = "Позиции документов"
        constraints = [
            models.UniqueConstraint(
                fields=['document', 'product'],
                name='unique_product_per_document'
            )
        ]

    def __str__(self):
        return f"{self.product.name} - {self.quantity} шт. по {self.price} руб."

    def clean(self):
        # Для возвратов: проверка, что товар был в оригинальной продаже
        if self.document.type == 'return' and self.document.original_sale:
            if not self.document.original_sale.items.filter(product=self.product).exists():
                raise ValidationError("Этот товар отсутствует в оригинальной продаже")

            # Проверка максимального количества для возврата
            original_quantity = self.document.original_sale.items.get(
                product=self.product
            ).quantity

            if self.quantity > original_quantity:
                raise ValidationError(
                    f"Максимальное количество для возврата: {original_quantity}"
                )

    # product = models.ForeignKey(Product, on_delete=models.PROTECT)
    # quantity = models.PositiveIntegerField()
    # price = models.DecimalField(max_digits=10, decimal_places=2)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.document.update_total()

    def delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)
        self.document.update_total()

    @property
    def total(self):
        """Вычисляет сумму позиции (цена * количество)"""
        return self.price * self.quantity

    def __str__(self):
        return f"{self.product.name} - {self.quantity} шт. по {self.price} руб. (Итого: {self.total} руб.)"


class SalesReport(models.Model):
    """Модель для хранения параметров отчетов о продажах"""
    REPORT_TYPES = (
        ('all', 'Все продажи'),
        ('cashless', 'Безналичный расчет'),
        ('cash', 'Наличный расчет'),
        ('return', 'Возвраты'),
    )

    report_type = models.CharField(
        max_length=10,
        choices=REPORT_TYPES,
        default='all',
        verbose_name="Тип отчета"
    )
    start_date = models.DateField(verbose_name="Дата начала")
    end_date = models.DateField(verbose_name="Дата окончания")
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Дата создания отчета"
    )

    class Meta:
        verbose_name = "Отчет о продажах"
        verbose_name_plural = "Отчеты о продажах"
        ordering = ['-created_at']

    def __str__(self):
        return f"Отчет о продажах ({self.get_report_type_display()}) с {self.start_date} по {self.end_date}"

    def generate_report_data(self):
        """Генерирует данные для отчета в требуемом формате"""
        # Фильтруем документы по дате и типу
        print("✅ generate_report_data вызван")
        qs = SaleDocument.objects.filter(
            date__range=[self.start_date, self.end_date]
        ).select_related('customer').prefetch_related('items')

        if self.report_type != 'all':
            qs = qs.filter(type=self.report_type)

        # Подготовка структуры для отчета
        report_data = {
            'cashless': {
                'label': 'БЕЗНАЛИЧНЫЙ РАСЧЕТ',
                'total': Decimal('0.00'),
                'by_date': {}
            },
            'cash': {
                'label': 'НАЛИЧНЫЙ РАСЧЕТ',
                'total': Decimal('0.00'),
                'by_date': {}
            },
            'return': {
                'label': 'ВОЗВРАТЫ ТОВАРА',
                'total': Decimal('0.00'),
                'by_date': {}
            },
            'grand_total': Decimal('0.00'),
            'by_date_total': {}
        }

        # Обработка каждого документа
        for doc in qs.order_by('date', 'id'):
            # Определяем тип для группировки
            if doc.type == 'cashless':
                group = report_data['cashless']
                doc_label = f"Продажа за безналичный расчет №{doc.number}"
            elif doc.type == 'cash':
                group = report_data['cash']
                doc_label = f"Товарный чек №{doc.number}"
            else:  # return
                group = report_data['return']
                doc_label = f"Возврат товара №{doc.number}"

            date_str = doc.date.strftime("%d.%m.%y")

            # Инициализация данных по дате
            if date_str not in group['by_date']:
                group['by_date'][date_str] = {
                    'total': Decimal('0.00'),
                    'documents': []
                }

            if date_str not in report_data['by_date_total']:
                report_data['by_date_total'][date_str] = Decimal('0.00')

            # Добавление документа
            doc_data = {
                'label': doc_label,
                'date': date_str,
                'total': doc.total,
                'customer': str(doc.customer)
            }

            group['by_date'][date_str]['documents'].append(doc_data)
            group['by_date'][date_str]['total'] += doc.total
            group['total'] += doc.total
            report_data['by_date_total'][date_str] += doc.total
            report_data['grand_total'] += doc.total

        # Форматирование данных для вывода
        formatted_data = []

        # Добавляем заголовок отчета
        formatted_data.append({
            'label': f"Продажи за период с {self.start_date.strftime('%d.%m.%y')} по {self.end_date.strftime('%d.%m.%y')}",
            'is_header': True
        })

        # Обработка безналичных продаж
        if report_data['cashless']['total'] > 0:
            formatted_data.append({
                'label': report_data['cashless']['label'],
                'is_group_header': True
            })

            formatted_data.append({
                'label': "   Всего",
                'total': report_data['cashless']['total'],
                'is_group_total': True
            })

            for date_str, date_data in report_data['cashless']['by_date'].items():
                formatted_data.append({
                    'label': f"   За день",
                    'date': date_str,
                    'total': date_data['total'],
                    'is_date_header': True
                })

                for doc in date_data['documents']:
                    formatted_data.append({
                        'label': f"     {doc['label']}",
                        'date': doc['date'],
                        'total': doc['total'],
                        'is_document': True
                    })

        # Обработка наличных продаж
        if report_data['cash']['total'] > 0:
            formatted_data.append({
                'label': report_data['cash']['label'],
                'is_group_header': True
            })

            formatted_data.append({
                'label': "   Всего",
                'total': report_data['cash']['total'],
                'is_group_total': True
            })

            for date_str, date_data in report_data['cash']['by_date'].items():
                formatted_data.append({
                    'label': f"   За день",
                    'date': date_str,
                    'total': date_data['total'],
                    'is_date_header': True
                })

                for doc in date_data['documents']:
                    formatted_data.append({
                        'label': f"     {doc['label']}",
                        'date': doc['date'],
                        'total': doc['total'],
                        'is_document': True
                    })

        # Обработка возвратов
        if report_data['return']['total'] > 0:
            formatted_data.append({
                'label': report_data['return']['label'],
                'is_group_header': True
            })

            formatted_data.append({
                'label': "   Всего",
                'total': report_data['return']['total'],
                'is_group_total': True
            })

            for date_str, date_data in report_data['return']['by_date'].items():
                formatted_data.append({
                    'label': f"   За день",
                    'date': date_str,
                    'total': date_data['total'],
                    'is_date_header': True
                })

                for doc in date_data['documents']:
                    formatted_data.append({
                        'label': f"     {doc['label']}",
                        'date': doc['date'],
                        'total': doc['total'],
                        'is_document': True
                    })

        # Итоговая информация
        formatted_data.append({
            'label': "ИТОГО",
            'total': report_data['grand_total'],
            'is_grand_total': True
        })

        for date_str, total in report_data['by_date_total'].items():
            formatted_data.append({
                'label': f"   За день",
                'date': date_str,
                'total': total,
                'is_date_total': True
            })

        return formatted_data
