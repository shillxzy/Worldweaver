from django.contrib.auth import get_user_model, password_validation
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import Profile, get_profile

User = get_user_model()


class UserSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(max_length=150, allow_blank=False)
    email = serializers.EmailField()
    bio = serializers.CharField(max_length=2000, allow_blank=True, required=False)
    date_joined = serializers.DateTimeField(read_only=True)

    @staticmethod
    def represent(user):
        profile = get_profile(user)
        return {
            "id": user.id,
            "name": profile.display_name or user.get_username(),
            "email": user.email,
            "bio": profile.bio,
            "has_avatar": bool(profile.avatar),
            "avatar_version": int(profile.updated_at.timestamp()) if profile.updated_at else 0,
            "date_joined": user.date_joined,
        }

    def validate_email(self, value):
        value = value.strip().lower()
        qs = User.objects.filter(username=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("Користувач з таким email уже існує.")
        return value

    def update(self, user, validated):
        profile = get_profile(user)
        if "email" in validated:
            user.email = validated["email"]
            user.username = validated["email"]
            user.save(update_fields=["email", "username"])
        if "name" in validated:
            profile.display_name = validated["name"].strip()
        if "bio" in validated:
            profile.bio = validated["bio"]
        profile.save()
        return user


class RegisterSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, max_length=128, style={"input_type": "password"})

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("Користувач з таким email уже існує.")
        return value

    def validate(self, attrs):
        candidate = User(username=attrs["email"], email=attrs["email"], first_name=attrs["name"])
        try:
            password_validation.validate_password(attrs["password"], user=candidate)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": exc.messages}) from exc
        return attrs

    def create(self, validated):
        user = User.objects.create_user(
            username=validated["email"], email=validated["email"], password=validated["password"]
        )
        Profile.objects.create(user=user, display_name=validated["name"].strip())
        return user


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, max_length=128)


class PasswordChangeSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True, max_length=128)
    new_password = serializers.CharField(write_only=True, max_length=128)

    def validate(self, attrs):
        user = self.context["request"].user
        if not user.check_password(attrs["old_password"]):
            raise serializers.ValidationError({"old_password": "Невірний поточний пароль."})
        try:
            password_validation.validate_password(attrs["new_password"], user=user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"new_password": exc.messages}) from exc
        return attrs


class DeleteAccountSerializer(serializers.Serializer):
    password = serializers.CharField(write_only=True, max_length=128)


class SettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Profile
        fields = ["theme", "language", "quick_checks_enabled", "spellcheck_enabled", "updated_at"]
        read_only_fields = ["updated_at"]
