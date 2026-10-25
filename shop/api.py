"""A deliberately small authenticated API that reuses the same service layer."""
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Order, Product
from .services import StockError, change_status, place_order


class ProductSerializer(serializers.ModelSerializer):
    available = serializers.IntegerField(read_only=True)

    class Meta:
        model = Product
        fields = ['id', 'sku', 'name', 'price', 'on_hand', 'reserved', 'available', 'reorder_point']


class LineSerializer(serializers.Serializer):
    product_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1, max_value=10000)


class NewOrderSerializer(serializers.Serializer):
    customer = serializers.CharField(max_length=100)
    request_key = serializers.UUIDField()
    items = LineSerializer(many=True, min_length=1, max_length=50)


class ActionSerializer(serializers.Serializer):
    target = serializers.ChoiceField(choices=['completed', 'cancelled', 'returned'])


def order_json(order):
    return {'id': order.pk, 'customer': order.customer, 'status': order.status,
            'request_key': str(order.request_key), 'total': str(order.total),
            'items': [{'product_id': item.product_id, 'quantity': item.quantity,
                       'unit_price': str(item.unit_price)} for item in order.items.all()]}


class ProductsAPI(APIView):
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get(self, request):
        return Response(ProductSerializer(Product.objects.all(), many=True).data)


class OrdersAPI(APIView):
    def post(self, request):
        serializer = NewOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            order, created = place_order(data['customer'],
                [(item['product_id'], item['quantity']) for item in data['items']],
                data['request_key'], request.user.username)
        except StockError as error:
            return Response({'detail': str(error)}, status=409)
        return Response(order_json(order), status=201 if created else 200)


class OrderAPI(APIView):
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get(self, request, pk):
        return Response(order_json(get_object_or_404(Order, pk=pk)))

    def post(self, request, pk):
        get_object_or_404(Order, pk=pk)
        serializer = ActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            order, _ = change_status(pk, serializer.validated_data['target'], request.user.username)
        except StockError as error:
            return Response({'detail': str(error)}, status=409)
        return Response(order_json(order))
