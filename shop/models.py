from django.db import models
from django.db.models import F, Q


class Product(models.Model):
    sku = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=100)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    on_hand = models.PositiveIntegerField(default=0)
    reserved = models.PositiveIntegerField(default=0)
    reorder_point = models.PositiveIntegerField(default=5)

    class Meta:
        ordering = ['sku']
        constraints = [
            models.CheckConstraint(condition=Q(reserved__lte=F('on_hand')), name='reserved_within_stock'),
            models.CheckConstraint(condition=Q(price__gte=0), name='nonnegative_price'),
        ]

    @property
    def available(self):
        return self.on_hand - self.reserved

    def __str__(self):
        return f'{self.sku} · {self.name}'


class Order(models.Model):
    class Status(models.TextChoices):
        RESERVED = 'reserved', 'Reserved'
        COMPLETED = 'completed', 'Completed'
        CANCELLED = 'cancelled', 'Cancelled'
        RETURNED = 'returned', 'Returned'

    customer = models.CharField(max_length=100)
    request_key = models.UUIDField(unique=True)
    payload_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.RESERVED, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-id']

    @property
    def total(self):
        return sum((item.quantity * item.unit_price for item in self.items.all()), 0)


class OrderItem(models.Model):
    order = models.ForeignKey(Order, related_name='items', on_delete=models.PROTECT)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['order', 'product'], name='one_product_per_order'),
                       models.CheckConstraint(condition=Q(quantity__gt=0), name='positive_quantity')]

    @property
    def subtotal(self):
        return self.quantity * self.unit_price


class StockEvent(models.Model):
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    order = models.ForeignKey(Order, null=True, blank=True, on_delete=models.PROTECT)
    kind = models.CharField(max_length=20)
    on_hand_delta = models.IntegerField(default=0)
    reserved_delta = models.IntegerField(default=0)
    reason = models.CharField(max_length=200)
    actor = models.CharField(max_length=150)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-id']
