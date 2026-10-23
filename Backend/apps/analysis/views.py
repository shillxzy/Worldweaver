from django.db.models import Count
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from apps.ai.backends import AIError
from apps.ai.service import AIService
from apps.books.models import Chapter
from apps.common.exceptions import ServiceUnavailable
from apps.common.scoping import EDIT, VIEW, accessible_worlds, method_role, parse_id, require_role, world_or_404

from .engine.loader import load_snapshot
from .engine.rules import build_dependency_graph, chronological_order
from .models import AnalysisJob, Finding
from .serializers import AnalysisJobSerializer, FindingSerializer
from .services import mark_superseded, quick_check, run_consistency


class AnalysisJobViewSet(mixins.CreateModelMixin, mixins.RetrieveModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = AnalysisJob.objects.none()  # schema introspection only; real data comes from get_queryset()
    serializer_class = AnalysisJobSerializer
    filterset_fields = ["world", "book", "chapter", "kind", "status"]

    def get_queryset(self):
        # Own jobs only, and only while the user can still work on that world (access may be revoked).
        return AnalysisJob.objects.filter(user=self.request.user, world__in=accessible_worlds(self.request.user, EDIT)).annotate(findings_count=Count("findings")).order_by("-created_at", "-id")

    def perform_create(self, serializer):
        job = serializer.save(user=self.request.user, status=AnalysisJob.Status.PENDING)
        mark_superseded(job)

    def create(self, request, *args, **kwargs):
        response = super().create(request, *args, **kwargs)
        response.status_code = status.HTTP_202_ACCEPTED
        return response

    @extend_schema(responses=FindingSerializer(many=True))
    @action(detail=True, methods=["get"])
    def results(self, request, pk=None):
        job = self.get_object()
        qs = job.findings.select_related("chapter").prefetch_related("evidence")
        for field in ("category", "decision", "severity", "source"):
            value = request.query_params.get(field)
            if value:
                qs = qs.filter(**{field: value})
        page = self.paginate_queryset(qs)
        return self.get_paginated_response(FindingSerializer(page, many=True).data)

    @extend_schema(request=None, responses=AnalysisJobSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        job = self.get_object()
        if job.status == AnalysisJob.Status.PENDING:
            AnalysisJob.objects.filter(pk=job.pk, status=AnalysisJob.Status.PENDING).update(
                status=AnalysisJob.Status.CANCELLED, finished_at=timezone.now(), progress_message="Скасовано користувачем"
            )
        elif job.status == AnalysisJob.Status.RUNNING:
            AnalysisJob.objects.filter(pk=job.pk).update(cancel_requested=True, progress_message="Скасування…")
        else:
            return Response(
                {"error": {"code": "invalid_state", "message": "Завершене завдання не можна скасувати.", "details": None}},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(self.get_serializer(self.get_queryset().get(pk=job.pk)).data)


class FindingViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    """Author decisions on findings. Findings never modify the manuscript."""

    queryset = Finding.objects.none()  # schema introspection only; real data comes from get_queryset()
    serializer_class = FindingSerializer
    filterset_fields = ["world", "chapter", "category", "decision", "severity", "source", "job"]
    http_method_names = ["get", "patch", "post", "head", "options"]

    def get_queryset(self):
        return Finding.objects.filter(world__in=accessible_worlds(self.request.user)).select_related("world", "chapter").prefetch_related("evidence")

    def get_object(self):
        # Everyone in the world sees the findings; deciding on them (and AI explanations) needs the editor role.
        finding = super().get_object()
        require_role(self.request.user, finding.world, EDIT if self.action == "explain" else method_role(self.request))
        return finding

    @extend_schema(request=None, responses=inline_serializer("Explanation", {"explanation": serializers.CharField()}))
    @action(detail=True, methods=["post"], throttle_classes=[UserRateThrottle])
    def explain(self, request, pk=None):
        finding = self.get_object()
        try:
            service = AIService()
            text = service.explain_finding(finding.summary, finding.explanation, [e.quote for e in finding.evidence.all() if e.quote][:4])
        except AIError as exc:
            raise ServiceUnavailable(str(exc)) from exc
        return Response({"explanation": text, "model": service.model_name, "verified": False})


class WorldConsistencyView(APIView):
    @extend_schema(request=None, responses=AnalysisJobSerializer)
    def post(self, request, world_pk):
        world = world_or_404(request.user, world_pk, EDIT)
        book_id = parse_id(request.data.get("book")) if hasattr(request, "data") else None
        chapters = Chapter.objects.filter(book__world=world)
        if book_id:
            chapters = chapters.filter(book_id=book_id)
        job = run_consistency(world, request.user, chapters)
        job = AnalysisJob.objects.annotate(findings_count=Count("findings")).get(pk=job.pk)
        return Response(AnalysisJobSerializer(job, context={"request": request}).data, status=status.HTTP_201_CREATED)


class WorldChronologyView(APIView):
    """Events in a consistent temporal order (topological sort of the dependency DAG)."""

    @extend_schema(responses=None)
    def get(self, request, world_pk):
        world = world_or_404(request.user, world_pk, VIEW)
        snap = load_snapshot(world, Chapter.objects.none())
        graph = build_dependency_graph(snap)
        cycle = graph.find_cycle()
        order = chronological_order(snap)
        return Response({
            "order": order,
            "has_cycle": bool(cycle),
            "cycle": cycle or [],
            "edges": [{"before": s, "after": t} for s, t, _ in graph.edges()],
        })


class QuickCheckSerializer(serializers.Serializer):
    chapter = serializers.IntegerField(min_value=1)
    text = serializers.CharField(max_length=20_000, allow_blank=True)
    offset = serializers.IntegerField(min_value=0, default=0)


class QuickCheckView(APIView):
    """Mode A: cheap, LLM-free checks of the fragment being edited."""

    @extend_schema(request=QuickCheckSerializer, responses=None)
    def post(self, request):
        serializer = QuickCheckSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        chapter = get_object_or_404(
            Chapter.objects.select_related("book__world").filter(book__world__in=accessible_worlds(request.user, EDIT)),
            pk=parse_id(serializer.validated_data["chapter"]) or 0,
        )
        return Response(quick_check(chapter, serializer.validated_data["text"], serializer.validated_data["offset"]))


class AIStatusView(APIView):
    @extend_schema(responses=None)
    def get(self, request):
        try:
            service = AIService()
        except AIError as exc:
            return Response({"available": False, "server": False, "error": str(exc)})
        health = service.health()
        pending = AnalysisJob.objects.filter(status=AnalysisJob.Status.PENDING).count()
        running = AnalysisJob.objects.filter(status=AnalysisJob.Status.RUNNING).count()
        return Response({**health, "queue": {"pending": pending, "running": running}})
