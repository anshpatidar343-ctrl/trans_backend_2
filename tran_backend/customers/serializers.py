from django.contrib.auth.hashers import make_password
from rest_framework import serializers

from .models import Customer


class CustomerSignupSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = [
            "id",
            "full_name",
            "email",
            "phone_number",
            "password",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]
        extra_kwargs = {"password": {"write_only": True}}

    def validate_password(self, value: str) -> str:
        return make_password(value)


class CustomerLoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField()
