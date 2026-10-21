from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.common.scoping import parse_id

from .models import Board, BoardConnection, BoardItem
from .serializers import BoardConnectionSerializer, BoardItemSerializer, BoardSerializer, LayoutSerializer


def owned_boards(user):
    return Board.objects.filter(Q(world__owner=user) | Q(book__world__owner=user))


class BoardViewSet(viewsets.ModelViewSet):
    queryset = Board.objects.none()  # schema introspection only; real data comes from get_queryset()
    serializer_class = BoardSerializer
    filterset_fields = ["book", "world"]

    def get_queryset(self):
        return owned_boards(self.request.user).prefetch_related("items", "connections")

    @extend_schema(request=LayoutSerializer, responses=BoardSerializer)
    @action(detail=True, methods=["post"])
    def layout(self, request, pk=None):
        """Persist positions / ordering / parents of many items in one transaction."""
        board = self.get_object()
        serializer = LayoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updates = serializer.validated_data["items"]
        with transaction.atomic():
            items = {i.id: i for i in BoardItem.objects.select_for_update().filter(board=board)}
            for entry in updates:
                item = items.get(entry["id"])
                if item is None:
                    return Response(
                        {"error": {"code": "validation_error", "message": f"Елемент {entry['id']} не належить дошці.", "details": None}},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                for key in ("x", "y", "order"):
                    if key in entry:
                        setattr(item, key, entry[key])
                if "parent" in entry:
                    parent_id = entry["parent"]
                    if parent_id is not None and (parent_id not in items or parent_id == item.id):
                        return Response(
                            {"error": {"code": "validation_error", "message": "Некоректний батьківський елемент.", "details": None}},
                            status=status.HTTP_400_BAD_REQUEST,
                        )
                    item.parent_id = parent_id
            BoardItem.objects.bulk_update(items.values(), ["x", "y", "order", "parent"])
            board.save(update_fields=["updated_at"])
        board = self.get_queryset().get(pk=board.pk)
        return Response(BoardSerializer(board, context=self.get_serializer_context()).data)


class BoardChildMixin:
    def get_board(self):
        if not hasattr(self, "_board"):
            self._board = get_object_or_404(owned_boards(self.request.user), pk=parse_id(self.kwargs["board_pk"]) or 0)
        return self._board

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["board"] = self.get_board()
        return context

    def perform_create(self, serializer):
        serializer.save(board=self.get_board())


class BoardItemViewSet(BoardChildMixin, viewsets.ModelViewSet):
    queryset = BoardItem.objects.none()  # schema introspection only; real data comes from get_queryset()
    serializer_class = BoardItemSerializer
    pagination_class = None

    def get_queryset(self):
        return BoardItem.objects.filter(board=self.get_board())


class BoardConnectionViewSet(BoardChildMixin, viewsets.ModelViewSet):
    queryset = BoardConnection.objects.none()  # schema introspection only; real data comes from get_queryset()
    serializer_class = BoardConnectionSerializer
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        return BoardConnection.objects.filter(board=self.get_board())
