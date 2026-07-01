from django.contrib.auth import authenticate
from django.db import transaction
from rest_framework import serializers
from rest_framework.authtoken.models import Token

from .models import EmployeeProfile, User


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "email", "first_name", "last_name", "role", "is_active"]


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        user = authenticate(username=attrs["username"], password=attrs["password"])
        if not user or not user.is_active:
            raise serializers.ValidationError("Неправильний логін або пароль.")
        attrs["user"] = user
        return attrs


class EmployeeSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source="user.id", read_only=True)
    username = serializers.CharField(source="user.username")
    email = serializers.EmailField(source="user.email")
    first_name = serializers.CharField(source="user.first_name")
    last_name = serializers.CharField(source="user.last_name")
    password = serializers.CharField(write_only=True, required=False, min_length=8, allow_blank=False)
    is_active = serializers.BooleanField(source="user.is_active", required=False)

    class Meta:
        model = EmployeeProfile
        fields = ["id", "user_id", "username", "email", "first_name", "last_name", "password", "is_active",
                  "middle_name", "phone", "photo", "position", "department", "work_phone", "start_date",
                  "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]

    def validate(self, attrs):
        user_data = attrs.get("user", {})
        username = user_data.get("username")
        email = user_data.get("email")
        current_user_id = self.instance.user_id if self.instance else None
        if username and User.objects.filter(username__iexact=username).exclude(pk=current_user_id).exists():
            raise serializers.ValidationError({"username": "Такий логін уже використовується."})
        if email and User.objects.filter(email__iexact=email).exclude(pk=current_user_id).exists():
            raise serializers.ValidationError({"email": "Такий email уже використовується."})
        if not self.instance and not attrs.get("password"):
            raise serializers.ValidationError({"password": "Вкажіть пароль."})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        user_data = validated_data.pop("user")
        password = validated_data.pop("password")
        user = User.objects.create_user(**user_data, password=password, role=User.Role.EMPLOYEE)
        return EmployeeProfile.objects.create(user=user, created_by=self.context["request"].user, **validated_data)

    @transaction.atomic
    def update(self, instance, validated_data):
        user_data = validated_data.pop("user", {})
        password = validated_data.pop("password", None)
        user = instance.user
        for field, value in user_data.items():
            setattr(user, field, value)
        if password:
            user.set_password(password)
        user.save()
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        return instance
