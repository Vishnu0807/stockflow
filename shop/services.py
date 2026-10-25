"""One place for every stock mutation. PostgreSQL locks rows until commit."""
import hashlib
import json
import uuid

from django.db import transaction

from .models import Order, OrderItem, Product, StockEvent


class StockError(ValueError):
    pass


def _event(product, kind, hand, reserved, reason, actor, order=None):
    StockEvent.objects.create(product=product, order=order, kind=kind,
                              on_hand_delta=hand, reserved_delta=reserved, reason=reason, actor=actor)


@transaction.atomic
def add_product(data, actor):
    product = Product(**data)
    product.full_clean()
    product.save()
    _event(product, 'opening', product.on_hand, 0, 'Opening balance', actor)
    return product


@transaction.atomic
def adjust_stock(product_id, delta, reason, actor):
    if type(delta) is not int or not -100000 <= delta <= 100000 or delta == 0:
        raise StockError('Adjustment must be a non-zero whole number, up to 100000 units.')
    reason = reason.strip()
    if not reason or len(reason) > 200:
        raise StockError('Give a reason up to 200 characters.')
    product = Product.objects.select_for_update().get(pk=product_id)
    if product.on_hand + delta < product.reserved:
        raise StockError('This would remove stock reserved for orders.')
    product.on_hand += delta
    product.save(update_fields=['on_hand'])
    _event(product, 'adjustment', delta, 0, reason, actor)
    return product


@transaction.atomic
def place_order(customer, lines, request_key, actor):
    customer = customer.strip()
    if not 1 <= len(customer) <= 100:
        raise StockError('Customer reference must contain 1–100 characters.')
    try:
        key = uuid.UUID(str(request_key))
    except (ValueError, TypeError, AttributeError):
        raise StockError('Invalid request key.')
    if not 1 <= len(lines) <= 50:
        raise StockError('Select 1–50 products.')
    quantities = {}
    for product_id, quantity in lines:
        if type(product_id) is not int or type(quantity) is not int or product_id < 1 or not 1 <= quantity <= 10000:
            raise StockError('Use valid products and quantities from 1 to 10000.')
        if product_id in quantities:
            raise StockError('Each product may appear once.')
        quantities[product_id] = quantity
    payload = json.dumps([customer, sorted(quantities.items())], separators=(',', ':'))
    fingerprint = hashlib.sha256(payload.encode()).hexdigest()
    # Unique key serializes simultaneous retries, even when they have different baskets.
    order, created = Order.objects.get_or_create(
        request_key=key, defaults={'customer': customer, 'payload_hash': fingerprint})
    if not created:
        if order.payload_hash != fingerprint:
            raise StockError('This request key belongs to a different order.')
        return order, False
    # Lock in consistent ID order to avoid deadlocks between overlapping baskets.
    products = list(Product.objects.select_for_update().filter(pk__in=quantities).order_by('pk'))
    if len(products) != len(quantities):
        raise StockError('A product is no longer available.')
    for product in products:
        quantity = quantities[product.pk]
        if quantity > product.available:
            raise StockError(f'{product.sku}: only {product.available} units available.')
        product.reserved += quantity
        product.save(update_fields=['reserved'])
        OrderItem.objects.create(order=order, product=product, quantity=quantity, unit_price=product.price)
        _event(product, 'reservation', 0, quantity, 'Order placed', actor, order)
    return order, True


@transaction.atomic
def change_status(order_id, target, actor):
    order = Order.objects.select_for_update().get(pk=order_id)
    if target == order.status:
        return order, False
    allowed = {'reserved': {'completed', 'cancelled'}, 'completed': {'returned'}}
    if target not in allowed.get(order.status, set()):
        raise StockError(f'Cannot change a {order.status} order to {target}.')
    items = {item.product_id: item for item in order.items.all()}
    products = Product.objects.select_for_update().filter(pk__in=items).order_by('pk')
    for product in products:
        quantity = items[product.pk].quantity
        hand = -quantity if target == 'completed' else quantity if target == 'returned' else 0
        reserved = -quantity if target in {'completed', 'cancelled'} else 0
        product.on_hand += hand
        product.reserved += reserved
        product.save(update_fields=['on_hand', 'reserved'])
        _event(product, target, hand, reserved, f'Order {target}', actor, order)
    order.status = target
    order.save(update_fields=['status', 'updated_at'])
    return order, True
