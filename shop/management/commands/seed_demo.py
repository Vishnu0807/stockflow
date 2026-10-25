"""Small deterministic fixture for a useful first screen; safe to rerun."""
from django.core.management.base import BaseCommand
from shop.models import Product
from shop.services import add_product


PRODUCTS = [
    ('NOTE-A5', 'A5 notebook', '89.00', 38, 8),
    ('PEN-BLK', 'Black gel pen', '35.00', 62, 12),
    ('DESK-LMP', 'Desk lamp', '1290.00', 14, 4),
    ('CABLE-C', 'USB-C cable', '249.00', 21, 6),
    ('BAG-CNV', 'Canvas tote bag', '420.00', 7, 8),
    ('MUG-GRN', 'Ceramic mug', '350.00', 18, 5),
]


class Command(BaseCommand):
    help = 'Add six sample products to an empty inventory; existing SKUs are left untouched.'

    def handle(self, *args, **options):
        created = 0
        for sku, name, price, on_hand, reorder_point in PRODUCTS:
            if not Product.objects.filter(sku=sku).exists():
                add_product(dict(sku=sku, name=name, price=price, on_hand=on_hand,
                                 reorder_point=reorder_point), 'demo-seed')
                created += 1
        self.stdout.write(self.style.SUCCESS(f'Added {created} sample products.'))
