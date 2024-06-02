from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from .models import Category, MenuItem, Cart, Order, OrderItem
from .serializers import CategorySerializer, MenuItemSerializer, CartSerializer, OrderSerializer, UserSerilializer
from rest_framework.response import Response

from rest_framework.permissions import IsAdminUser
from django.shortcuts import  get_object_or_404

from django.contrib.auth.models import Group, User

from rest_framework import viewsets
from rest_framework import status


class CategoriesView(generics.ListCreateAPIView):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer

    def get_permissions(self): #Admin status required for anything other than GET
        permission_classes = []
        if self.request.method != 'GET':
            permission_classes = [IsAdminUser]

        return [permission() for permission in permission_classes]

class MenuItemsView(generics.ListCreateAPIView):
    queryset = MenuItem.objects.all()
    serializer_class = MenuItemSerializer
    search_fields = ['category__title']
    ordering_fields = ['price', 'inventory']

    def get_permissions(self): #Admin status required for anything other than GET
        permission_classes = []
        if self.request.method != 'GET':
            permission_classes = [IsAdminUser]

        return [permission() for permission in permission_classes]


class SingleMenuItemView(generics.RetrieveUpdateDestroyAPIView):
    queryset = MenuItem.objects.all()
    serializer_class = MenuItemSerializer

    def get_permissions(self): #Admin status required for anything other than GET
        permission_classes = []
        if self.request.method != 'GET':
            permission_classes = [IsAdminUser]

        return [permission() for permission in permission_classes]

class CartView(generics.ListCreateAPIView):
    queryset = Cart.objects.all()
    serializer_class = CartSerializer
    permission_classes = [IsAuthenticated] #user must be logged in to add items to cart

    def get_queryset(self):
        return Cart.objects.all().filter(user=self.request.user)

    def delete(self, request, *args, **kwargs):
        Cart.objects.all().filter(user=self.request.user).delete()
        return Response("ok")


class OrderView(generics.ListCreateAPIView):
    queryset = Order.objects.all()
    serializer_class = OrderSerializer
    permission_classes = [IsAuthenticated] #user must be logged in to see or submit their order

    def get_queryset(self):
        if self.request.user.is_superuser:
            return Order.objects.all()
        elif self.request.user.groups.count()==0: # normal user (is not in staff or admin group)
            return Order.objects.all().filter(user=self.request.user)
        elif self.request.user.groups.filter(name='Delivery Crew').exists(): # delivery crew
            return Order.objects.all().filter(delivery_crew=self.request.user)  # only shows orders assigned to this crew member
        else: # "catch all" else clause
            return Order.objects.all()

    def create(self, request, *args, **kwargs):
        # Check if there are any items in the user's cart
        menuitem_count = Cart.objects.all().filter(user=self.request.user).count()
        if menuitem_count == 0:
            return Response({"message:": "no item in cart"})
        
        # Prepare order data
        data = request.data.copy()
        total = self.get_total_price(self.request.user)
        data['total'] = total
        data['user'] = self.request.user.id
        order_serializer = OrderSerializer(data=data)

         # Validate order data and save order in DB
        if (order_serializer.is_valid()):
            order = order_serializer.save()

            # Create order items from cart contents
            items = Cart.objects.all().filter(user=self.request.user).all()

            for item in items.values():
                orderitem = OrderItem(
                    order=order,
                    menuitem_id=item['menuitem_id'],
                    price=item['price'],
                    quantity=item['quantity'],
                )
                orderitem.save()

            # Empty cart once order has been submitted
            Cart.objects.all().filter(user=self.request.user).delete() 

            # Prepare response data
            result = order_serializer.data.copy()
            result['total'] = total
            return Response(order_serializer.data)

    def get_total_price(self, user):
        total = 0
        items = Cart.objects.all().filter(user=user).all()

        # Loop through items and accumulate their prices for the total
        for item in items.values():
            total += item['price']
        return total


class SingleOrderView(generics.RetrieveUpdateAPIView):
    serializer_class = OrderSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        order_id = self.kwargs.get('pk')  # Get the order ID from URL parameters
        order = get_object_or_404(Order, pk=order_id)  # Get the specific order object

        if self.request.user.is_superuser:
            # Superuser can see any order
            return order
        elif self.request.user.groups.filter(name='Delivery Crew').exists():
            # Delivery crew can see orders assigned to them
            if order.delivery_crew == self.request.user:
                return order
            else:
                raise PermissionDenied("You are not allowed to access this order.")
        else:
            # Authenticated customers can see only their own orders
            if order.user == self.request.user:
                return order
            else:
                raise PermissionDenied("You are not allowed to access this order.")

    def update(self, request, *args, **kwargs):
        if self.request.user.groups.count()==0:
            return Response('This user cannot update the order')
        else: 
            return super().update(request, *args, **kwargs)

#GOOD MORNING FUTURE SIMEON, NOW CHECK AND COMMENT ON EVERYTHING BELOW BEFORE PUSHING VIEWS AND URLS TO GH

class GroupViewSet(viewsets.ViewSet):

    permission_classes = [IsAdminUser]

    #View all managers
    def list(self, request):
        users = User.objects.all().filter(groups__name='Manager')
        items = UserSerilializer(users, many=True)
        return Response(items.data)

    #Add manager to group
    def create(self, request):
        user = get_object_or_404(User, username=request.data['username'])
        managers = Group.objects.get(name="Manager")
        managers.user_set.add(user)
        return Response({"message": "user added to the manager group"}, 200)

    #Remove manager from group
    def destroy(self, request):
        user = get_object_or_404(User, username=request.data['username'])
        managers = Group.objects.get(name="Manager")
        managers.user_set.remove(user)
        return Response({"message": "user removed from the manager group"}, 200)

class DeliveryCrewViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    #View all Delivery Crew
    def list(self, request):
        users = User.objects.all().filter(groups__name='Delivery Crew')
        items = UserSerilializer(users, many=True)
        return Response(items.data)

    #Add delivery person to group
    def create(self, request):
        #Only for admin and managers
        if self.request.user.is_superuser == False:
            if self.request.user.groups.filter(name='Manager').exists() == False:
                return Response({"message":"forbidden"}, status.HTTP_403_FORBIDDEN)
        
        user = get_object_or_404(User, username=request.data['username'])
        d_crew = Group.objects.get(name="Delivery Crew")
        d_crew.user_set.add(user)
        return Response({"message": "user added to the delivery crew group"}, 200)

    #Remove delivery person from group
    def destroy(self, request):
        #Only for admin and managers
        if self.request.user.is_superuser == False:
            if self.request.user.groups.filter(name='Manager').exists() == False:
                return Response({"message":"forbidden"}, status.HTTP_403_FORBIDDEN)
        user = get_object_or_404(User, username=request.data['username'])
        delivery_crew = Group.objects.get(name="Delivery Crew")
        delivery_crew.user_set.remove(user)
        return Response({"message": "user removed from the delivery crew group"}, 200)
