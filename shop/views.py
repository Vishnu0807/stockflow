import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection
from django.db.models import F, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import AdjustmentForm, ProductForm
from .models import Order, Product, StockEvent
from .reports import report_data
from .services import StockError, add_product, adjust_stock, change_status, place_order


def inventory(request):
    query = request.GET.get('q', '').strip()[:100]
    products = Product.objects.all()
    if query:
        products = products.filter(Q(name__icontains=query) | Q(sku__icontains=query))
    if request.GET.get('low'):
        products = products.filter(on_hand__lte=F('reserved') + F('reorder_point'))
    totals = Product.objects.aggregate(on_hand=Sum('on_hand'), reserved=Sum('reserved'))
    return render(request, 'inventory.html', {'products': products, 'query': query, 'totals': totals,
        'count': Product.objects.count(),
        'low_count': Product.objects.filter(on_hand__lte=F('reserved') + F('reorder_point')).count(),
        'sqlite': connection.vendor == 'sqlite'})


@login_required
def product_new(request):
    form = ProductForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            add_product(form.cleaned_data, request.user.username)
        except (ValidationError, IntegrityError):
            form.add_error(None, 'Could not save this product. Check the SKU and values.')
        else:
            messages.success(request, 'Product added.')
            return redirect('inventory')
    return render(request, 'form.html', {'form': form, 'title': 'Add product', 'back': '/'})


@login_required
def adjust(request, pk):
    product = get_object_or_404(Product, pk=pk)
    form = AdjustmentForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            adjust_stock(pk, actor=request.user.username, **form.cleaned_data)
        except StockError as error:
            form.add_error(None, str(error))
        else:
            messages.success(request, f'{product.sku}: stock adjusted.')
            return redirect('inventory')
    return render(request, 'form.html', {'form': form, 'title': f'Adjust {product.sku}',
        'subtitle': f'{product.name} · {product.available} available · {product.reserved} reserved', 'back': '/'})


def orders(request):
    status = request.GET.get('status', '')
    queryset = Order.objects.prefetch_related('items')
    if status in Order.Status.values:
        queryset = queryset.filter(status=status)
    return render(request, 'orders.html', {'orders': queryset[:100], 'statuses': Order.Status.choices, 'status': status})


@login_required
def order_new(request):
    products = list(Product.objects.all())
    key = request.POST.get('request_key') or str(uuid.uuid4())
    customer = request.POST.get('customer', '')
    error = ''
    if request.method == 'POST':
        try:
            lines = []
            for product in products:
                raw = request.POST.get(f'qty_{product.pk}', '0').strip() or '0'
                quantity = int(raw)
                if quantity:
                    lines.append((product.pk, quantity))
            order, created = place_order(customer, lines, key, request.user.username)
        except (StockError, ValueError) as exc:
            error = str(exc) if isinstance(exc, StockError) else 'Enter whole-number quantities.'
        else:
            messages.success(request, 'Order reserved.' if created else 'Request already processed; showing original order.')
            return redirect('order_detail', pk=order.pk)
    for product in products:
        product.entered_quantity = request.POST.get(f'qty_{product.pk}', '')
    return render(request, 'order_new.html', {'products': products, 'request_key': key,
        'customer': customer, 'error': error})


def order_detail(request, pk):
    order = get_object_or_404(Order.objects.prefetch_related('items__product'), pk=pk)
    return render(request, 'order_detail.html', {'order': order,
        'events': StockEvent.objects.filter(order=order).select_related('product')})


@login_required
@require_POST
def order_action(request, pk):
    get_object_or_404(Order, pk=pk)
    try:
        _, changed = change_status(pk, request.POST.get('target', ''), request.user.username)
    except StockError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, 'Order updated.' if changed else 'Already processed; stock unchanged.')
    return redirect('order_detail', pk=pk)


def reports(request):
    data = report_data()
    data['events'] = StockEvent.objects.select_related('product', 'order')[:30]
    return render(request, 'reports.html', data)
