from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.books.models import Book, Chapter
from apps.common.images import image_response
from apps.common.scoping import COMMENT, EDIT, MANAGE, OWN, VIEW, WorldScopedMixin, has_role, parse_id, world_or_404, world_role
from apps.pages.models import Page
from apps.worlds.models import World

from .models import RANK, Comment, Role, WorldInvite, WorldMember, new_token
from .serializers import (
    CommentCreateSerializer,
    CommentSerializer,
    CommentUpdateSerializer,
    InviteCreateSerializer,
    InviteSerializer,
    PublicSettingsSerializer,
    RoleSerializer,
    TransferSerializer,
    person,
)

User = get_user_model()


# --- members ------------------------------------------------------------------------------

def members_payload(world, viewer):
    show_email = has_role(viewer, world, MANAGE)
    owner = world.owner
    rows = [{**person(owner, show_email or owner.pk == viewer.pk), "role": Role.OWNER.value, "joined_at": world.created_at}]
    for m in WorldMember.objects.filter(world=world).select_related("user__profile").order_by("joined_at", "id"):
        rows.append({**person(m.user, show_email or m.user_id == viewer.pk), "role": m.role, "joined_at": m.joined_at})
    return rows


def check_can_manage(user, world, target_role, new_role=None):
    """Admins manage editors, commenters and viewers; only the owner appoints or removes admins."""
    actor = world_role(user, world)
    if target_role == Role.OWNER:
        raise PermissionDenied("Роль власника змінюється лише передачею власності.")
    if Role.ADMIN in (target_role, new_role) and actor != Role.OWNER:
        raise PermissionDenied("Призначати й знімати адміністраторів може лише власник.")


class MembersView(APIView):
    @extend_schema(responses=None)
    def get(self, request, world_pk):
        world = world_or_404(request.user, world_pk, VIEW)
        return Response({"my_role": world_role(request.user, world), "members": members_payload(world, request.user)})


class MemberDetailView(APIView):
    @extend_schema(request=RoleSerializer, responses=None)
    def patch(self, request, world_pk, user_pk):
        world = world_or_404(request.user, world_pk, MANAGE)
        member = get_object_or_404(WorldMember, world=world, user_id=user_pk)
        serializer = RoleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        check_can_manage(request.user, world, member.role, serializer.validated_data["role"])
        member.role = serializer.validated_data["role"]
        member.save(update_fields=["role"])
        return Response({"my_role": world_role(request.user, world), "members": members_payload(world, request.user)})

    @extend_schema(responses={204: None})
    def delete(self, request, world_pk, user_pk):
        """Remove a member, or leave the project (``user_pk`` is your own id)."""
        world = world_or_404(request.user, world_pk, VIEW)
        if int(user_pk) == world.owner_id:
            raise ValidationError({"user": "Власник не може покинути проєкт. Спершу передайте власність."})
        member = get_object_or_404(WorldMember, world=world, user_id=user_pk)
        if member.user_id != request.user.pk:
            world_or_404(request.user, world_pk, MANAGE)
            check_can_manage(request.user, world, member.role)
        member.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MemberAvatarView(APIView):
    @extend_schema(responses={(200, "image/*"): bytes})
    def get(self, request, world_pk, user_pk):
        world = world_or_404(request.user, world_pk, VIEW)
        in_world = int(user_pk) == world.owner_id or WorldMember.objects.filter(world=world, user_id=user_pk).exists()
        user = get_object_or_404(User.objects.select_related("profile"), pk=user_pk) if in_world else None
        return image_response(getattr(getattr(user, "profile", None), "avatar", None), "Аватар не завантажено.")


class TransferView(APIView):
    @extend_schema(request=TransferSerializer, responses=None)
    def post(self, request, world_pk):
        """Hand the project to another member. The previous owner stays as an admin."""
        serializer = TransferSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            world = world_or_404(request.user, world_pk, OWN)
            world = World.objects.select_for_update().get(pk=world.pk)
            member = WorldMember.objects.filter(world=world, user_id=serializer.validated_data["user"]).first()
            if member is None:
                raise ValidationError({"user": "Власність можна передати лише учаснику проєкту."})
            previous = world.owner
            world.owner_id = member.user_id
            world.save(update_fields=["owner", "updated_at"])
            member.delete()
            WorldMember.objects.create(world=world, user=previous, role=Role.ADMIN, invited_by=member.user)
        return Response({"my_role": Role.ADMIN.value, "members": members_payload(world, request.user)})


# --- invitations --------------------------------------------------------------------------

class InvitesView(APIView):
    @extend_schema(responses=InviteSerializer(many=True))
    def get(self, request, world_pk):
        world = world_or_404(request.user, world_pk, MANAGE)
        invites = WorldInvite.objects.filter(world=world, revoked_at__isnull=True).select_related("created_by__profile")
        return Response(InviteSerializer(invites, many=True).data)

    @extend_schema(request=InviteCreateSerializer, responses=InviteSerializer)
    def post(self, request, world_pk):
        world = world_or_404(request.user, world_pk, MANAGE)
        serializer = InviteCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        check_can_manage(request.user, world, data["role"], data["role"])
        email = data["email"]
        if email:
            if email == (world.owner.email or "").lower() or WorldMember.objects.filter(world=world, user__email__iexact=email).exists():
                raise ValidationError({"email": "Ця людина вже є в проєкті."})
            # A new personal invite replaces an older pending one to the same address.
            WorldInvite.objects.filter(world=world, email=email, revoked_at__isnull=True, uses=0).update(revoked_at=timezone.now())
        invite = WorldInvite.objects.create(
            world=world, email=email, role=data["role"], created_by=request.user,
            expires_at=data["expires_at"], max_uses=data.get("max_uses"),
        )
        return Response(InviteSerializer(invite).data, status=status.HTTP_201_CREATED)


class InviteRevokeView(APIView):
    @extend_schema(responses={204: None})
    def delete(self, request, world_pk, invite_pk):
        world = world_or_404(request.user, world_pk, MANAGE)
        invite = get_object_or_404(WorldInvite, world=world, pk=invite_pk)
        check_can_manage(request.user, world, invite.role)
        invite.revoked_at = invite.revoked_at or timezone.now()
        invite.save(update_fields=["revoked_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)


def invite_preview(invite, user):
    world = invite.world
    return {
        "world": {"id": world.id, "name": world.name},
        "books": [{"id": b.id, "title": b.title} for b in Book.objects.filter(world=world).order_by("title")[:10]],
        "role": invite.role,
        "invited_by": person(invite.created_by),
        "email": invite.email,
        "problem": invite.problem(),
        "my_role": world_role(user, world),
    }


class InviteByTokenView(APIView):
    @extend_schema(responses=None)
    def get(self, request, token):
        invite = get_object_or_404(WorldInvite.objects.select_related("world", "created_by__profile"), token=token)
        return Response(invite_preview(invite, request.user))


class InviteAcceptView(APIView):
    @extend_schema(request=None, responses=None)
    def post(self, request, token):
        with transaction.atomic():
            invite = get_object_or_404(WorldInvite.objects.select_for_update().select_related("world"), token=token)
            problem = invite.problem()
            if problem:
                raise ValidationError({"token": problem})
            if invite.email and invite.email != (request.user.email or "").lower():
                raise PermissionDenied("Це запрошення надіслано на іншу електронну адресу.")
            world = invite.world
            if world.owner_id != request.user.pk:
                member, created = WorldMember.objects.get_or_create(
                    world=world, user=request.user, defaults={"role": invite.role, "invited_by": invite.created_by},
                )
                upgraded = not created and RANK[invite.role] > RANK[member.role]
                if upgraded:
                    member.role = invite.role
                    member.save(update_fields=["role"])
                if created or upgraded:
                    invite.uses += 1
                    invite.save(update_fields=["uses"])
        book = Book.objects.filter(world=world).order_by("-updated_at").values_list("id", flat=True).first()
        return Response({"world": world.id, "book": book, "role": world_role(request.user, world)})


class MyInvitesView(APIView):
    """Personal invitations waiting for the current user's email address."""

    @extend_schema(responses=None)
    def get(self, request):
        email = (request.user.email or "").lower()
        invites = WorldInvite.objects.filter(email=email, revoked_at__isnull=True, declined_at__isnull=True, uses=0).select_related(
            "world", "created_by__profile"
        ) if email else []
        return Response([{**invite_preview(i, request.user), "token": i.token} for i in invites if not i.problem()])


class InviteDeclineView(APIView):
    @extend_schema(request=None, responses={204: None})
    def post(self, request, token):
        invite = get_object_or_404(WorldInvite, token=token, email=(request.user.email or "").lower())
        invite.declined_at = invite.declined_at or timezone.now()
        invite.save(update_fields=["declined_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- comments -----------------------------------------------------------------------------

class CommentViewSet(WorldScopedMixin, viewsets.ModelViewSet):
    """Comments on chapters and pages: commenters and above read and write them."""

    queryset = Comment.objects.none()  # schema introspection only; real data comes from get_queryset()
    serializer_class = CommentSerializer
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def required_role(self):
        return COMMENT

    def get_queryset(self):
        qs = Comment.objects.filter(world=self.get_world()).select_related("author__profile", "resolved_by__profile")
        params = self.request.query_params
        if parse_id(params.get("chapter")):
            qs = qs.filter(chapter_id=parse_id(params["chapter"]))
        if parse_id(params.get("page")):
            qs = qs.filter(page_id=parse_id(params["page"]))
        if params.get("book") and parse_id(params["book"]):
            qs = qs.filter(chapter__book_id=parse_id(params["book"]))
        if params.get("resolved") in ("true", "false"):
            qs = qs.filter(Q(resolved=params["resolved"] == "true") | Q(parent__isnull=False))
        return qs

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.kwargs.get("world_pk") is not None:
            world = self.get_world()
            context["can_edit_content"] = has_role(self.request.user, world, EDIT)
            context["can_manage"] = has_role(self.request.user, world, MANAGE)
        return context

    @extend_schema(request=CommentCreateSerializer, responses=CommentSerializer)
    def create(self, request, *args, **kwargs):
        world = self.get_world()
        serializer = CommentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        chapter = page = parent = None
        if data.get("parent"):
            parent = get_object_or_404(Comment.objects.filter(world=world, parent__isnull=True), pk=data["parent"])
            chapter, page = parent.chapter, parent.page
        elif bool(data.get("chapter")) == bool(data.get("page")):
            raise ValidationError({"chapter": "Вкажіть розділ або сторінку (одне з двох)."})
        elif data.get("chapter"):
            chapter = get_object_or_404(Chapter.objects.filter(book__world=world), pk=data["chapter"])
        else:
            page = get_object_or_404(Page.objects.filter(world=world), pk=data["page"])
        comment = Comment.objects.create(
            world=world, chapter=chapter, page=page, parent=parent, author=request.user,
            body=data["body"], quote="" if parent else data.get("quote", "").strip(),
            quote_occurrence=0 if parent or not data.get("quote", "").strip() else data["quote_occurrence"],
        )
        return Response(self.get_serializer(comment).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=CommentUpdateSerializer, responses=CommentSerializer)
    def partial_update(self, request, *args, **kwargs):
        comment = self.get_object()
        serializer = CommentUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        mine = comment.author_id == request.user.pk
        if "body" in data:
            if not mine:
                raise PermissionDenied("Редагувати можна лише власні коментарі.")
            if not data["body"].strip():
                raise ValidationError({"body": "Коментар порожній."})
            comment.body = data["body"].strip()
        if "resolved" in data:
            if comment.parent_id or not (mine or has_role(request.user, comment.world, EDIT)):
                raise PermissionDenied("Закривати обговорення можуть автор і редактори.")
            comment.resolved = data["resolved"]
            comment.resolved_by = request.user if data["resolved"] else None
        comment.save()
        return Response(self.get_serializer(comment).data)

    def update(self, request, *args, **kwargs):
        return self.partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        comment = self.get_object()
        if comment.author_id != request.user.pk and not has_role(request.user, comment.world, MANAGE):
            raise PermissionDenied("Видаляти чужі коментарі можуть адміністратори та власник.")
        comment.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class CommentCountsView(APIView):
    """Open comment threads per chapter of a book (for badges in the chapter list)."""

    @extend_schema(parameters=[OpenApiParameter("book", int)], responses=None)
    def get(self, request, world_pk):
        world = world_or_404(request.user, world_pk, COMMENT)
        qs = Comment.objects.filter(world=world, parent__isnull=True, resolved=False)
        book = parse_id(request.query_params.get("book"))
        chapters = {}
        for chapter_id in qs.filter(chapter__book_id=book).values_list("chapter_id", flat=True) if book else []:
            chapters[chapter_id] = chapters.get(chapter_id, 0) + 1
        pages = {}
        for page_id in qs.filter(page__isnull=False).values_list("page_id", flat=True):
            pages[page_id] = pages.get(page_id, 0) + 1
        return Response({"chapters": chapters, "pages": pages})


# --- public site settings (owner) ---------------------------------------------------------

def public_settings_payload(world):
    books = []
    for book in Book.objects.filter(world=world).order_by("title"):
        books.append({
            "id": book.id, "title": book.title, "is_public": book.is_public,
            "chapters": list(book.chapters.order_by("order", "id").values("id", "title", "is_public", "status")),
        })
    pages = list(Page.objects.filter(world=world).order_by("sort_order", "id").values("id", "title", "icon", "parent", "is_public"))
    return {"enabled": world.public_enabled, "token": world.public_token if world.public_enabled else None, "books": books, "pages": pages}


class PublicSettingsView(APIView):
    @extend_schema(responses=None)
    def get(self, request, world_pk):
        return Response(public_settings_payload(world_or_404(request.user, world_pk, OWN)))

    @extend_schema(request=PublicSettingsSerializer, responses=None)
    def patch(self, request, world_pk):
        world = world_or_404(request.user, world_pk, OWN)
        serializer = PublicSettingsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        with transaction.atomic():
            for model, key, scope in ((Book, "books", {"world": world}), (Chapter, "chapters", {"book__world": world}), (Page, "pages", {"world": world})):
                flags = data.get(key) or {}
                for value in (True, False):
                    ids = [parse_id(k) for k, v in flags.items() if v is value and parse_id(k)]
                    if ids:
                        model.objects.filter(pk__in=ids, **scope).update(is_public=value)
            if "enabled" in data:
                world.public_enabled = data["enabled"]
            if data.get("regenerate") or (world.public_enabled and not world.public_token):
                world.public_token = new_token()  # the old link stops working at once
            world.save(update_fields=["public_enabled", "public_token", "updated_at"])
        return Response(public_settings_payload(world))
