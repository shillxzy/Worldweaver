import re

from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import ServiceUnavailable
from apps.common.scoping import owned_world_or_404

from .models import DictionaryWord
from .spell import WORD_RE, SpellService, SpellUnavailable, world_vocabulary


class SpellcheckRequest(serializers.Serializer):
    text = serializers.CharField(max_length=100_000, allow_blank=True, trim_whitespace=False)
    world = serializers.IntegerField(min_value=1, required=False)


class SpellcheckView(APIView):
    @extend_schema(request=SpellcheckRequest, responses=None)
    def post(self, request):
        serializer = SpellcheckRequest(data=request.data)
        serializer.is_valid(raise_exception=True)
        world = owned_world_or_404(request.user, serializer.validated_data["world"]) if serializer.validated_data.get("world") else None
        accepted = set(DictionaryWord.objects.filter(user=request.user).values_list("word", flat=True))
        vocabulary = world_vocabulary(world)
        try:
            result = SpellService.check(serializer.validated_data["text"], accepted | vocabulary)
        except SpellUnavailable as exc:
            raise ServiceUnavailable(str(exc)) from exc
        # Inflected forms of world names ("Ейри" for "Ейра") are accepted by stem prefix.
        stems = {w[: max(4, len(w) - 2)] for w in vocabulary if len(w) >= 4}
        result["spelling"] = [i for i in result["spelling"] if not any(i["word"].lower().startswith(s) for s in stems)]
        return Response(result)


class SuggestView(APIView):
    @extend_schema(responses=None)
    def get(self, request):
        word = request.query_params.get("word", "").strip()
        if not WORD_RE.fullmatch(word) or len(word) > 60:
            return Response({"error": {"code": "validation_error", "message": "Некоректне слово.", "details": None}}, status=400)
        try:
            return Response({"word": word, "suggestions": SpellService.suggest(word)})
        except SpellUnavailable as exc:
            raise ServiceUnavailable(str(exc)) from exc


class LanguageStatusView(APIView):
    @extend_schema(responses=None)
    def get(self, request):
        return Response(SpellService.status())


class DictionaryWordSerializer(serializers.ModelSerializer):
    class Meta:
        model = DictionaryWord
        fields = ["id", "word", "created_at"]
        read_only_fields = ["created_at"]

    def validate_word(self, value):
        value = value.strip()
        if not re.fullmatch(r"[^\W\d_]+(?:['’ʼ\-][^\W\d_]+)*", value):
            raise serializers.ValidationError("Слово має складатися з літер.")
        return value.lower()


class DictionaryViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    queryset = DictionaryWord.objects.none()  # schema introspection only; real data comes from get_queryset()
    serializer_class = DictionaryWordSerializer
    pagination_class = None

    def get_queryset(self):
        return DictionaryWord.objects.filter(user=self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        word, _ = DictionaryWord.objects.get_or_create(user=request.user, word=serializer.validated_data["word"])
        return Response(self.get_serializer(word).data, status=status.HTTP_201_CREATED)
