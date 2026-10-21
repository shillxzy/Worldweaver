"""Schemas for structured model output: JSON schema sent to Ollama + server-side validators."""
from rest_framework import serializers

FINDINGS_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string"},
                    "severity": {"type": "string", "enum": ["info", "warning", "error"]},
                    "confidence": {"type": "number"},
                    "summary": {"type": "string"},
                    "explanation": {"type": "string"},
                    "evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"source": {"type": "string"}, "quote": {"type": "string"}},
                            "required": ["source", "quote"],
                        },
                    },
                },
                "required": ["type", "severity", "summary", "evidence"],
            },
        }
    },
    "required": ["findings"],
}

ENTITY_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "type": {"type": "string"}, "quote": {"type": "string"}},
                "required": ["name", "type"],
            },
        }
    },
    "required": ["entities"],
}

TIMELINE_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "time_hint": {"type": "string"},
                    "participants": {"type": "array", "items": {"type": "string"}},
                    "quote": {"type": "string"},
                },
                "required": ["title", "quote"],
            },
        }
    },
    "required": ["events"],
}


class EvidenceItemSerializer(serializers.Serializer):
    source = serializers.CharField(max_length=20)
    quote = serializers.CharField(max_length=1500)


class FindingItemSerializer(serializers.Serializer):
    type = serializers.CharField(max_length=80)
    severity = serializers.ChoiceField(choices=["info", "warning", "error"])
    confidence = serializers.FloatField(min_value=0, max_value=1, required=False, allow_null=True)
    summary = serializers.CharField(max_length=500)
    explanation = serializers.CharField(max_length=5000, required=False, allow_blank=True, default="")
    evidence = EvidenceItemSerializer(many=True, max_length=10)


class FindingsSerializer(serializers.Serializer):
    findings = FindingItemSerializer(many=True, max_length=50)


class EntityItemSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    type = serializers.ChoiceField(choices=["character", "location", "faction", "item", "other"])
    quote = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")


class EntitiesSerializer(serializers.Serializer):
    entities = EntityItemSerializer(many=True, max_length=200)


class TimelineItemSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    description = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")
    time_hint = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    participants = serializers.ListField(child=serializers.CharField(max_length=200), required=False, default=list, max_length=30)
    quote = serializers.CharField(max_length=1000)


class TimelineSerializer(serializers.Serializer):
    events = TimelineItemSerializer(many=True, max_length=100)
