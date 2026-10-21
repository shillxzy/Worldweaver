from datetime import timedelta

import pytest
import requests
from django.utils import timezone

from apps.ai.backends import AIConfigError, AIUnavailable, OllamaBackend, assert_local_endpoint
from apps.ai.service import AIService
from apps.analysis.models import AnalysisJob, Finding
from apps.analysis.worker import claim_next_job, recover_stale_jobs, run_one
from apps.books.documents import document_stats
from apps.books.models import Chapter
from apps.worlds.models import Character, EventParticipant, TimelineEvent

from .conftest import doc

pytestmark = pytest.mark.django_db


class FakeBackend:
    model = "fake-model"

    def __init__(self, answer=None, available=True, error=None):
        self.answer = answer
        self.available = available
        self.error = error
        self.calls = []

    def health(self):
        return {"available": self.available, "server": self.available, "model": self.model}

    def chat_json(self, system, user, schema=None, temperature=0.1):
        self.calls.append(user)
        if self.error:
            raise self.error
        return self.answer(user) if callable(self.answer) else self.answer


def factory(backend):
    return lambda: AIService(backend)


def set_text(chapter, *paragraphs):
    chapter.content = doc(*paragraphs)
    chapter.plain_text, chapter.word_count = document_stats(chapter.content)
    chapter.save()


@pytest.fixture
def story(world, book, chapter):
    kael = Character.objects.create(world=world, name="Каель", death_key=340, death_precision="exact", status="dead")
    set_text(chapter, "Каель загинув біля воріт.")
    later = Chapter.objects.create(book=book, title="Розділ 3", order=2)
    set_text(later, "— Ходімо, — сказав Каель і рушив до брами.")
    event = TimelineEvent.objects.create(world=world, title="Облога", start_key=350)
    EventParticipant.objects.create(event=event, character=kael)
    return {"kael": kael, "later": later, "event": event}


def test_consistency_endpoint_returns_findings_with_sources(client, world, story):
    r = client.post(f"/api/v1/worlds/{world.id}/consistency/")
    assert r.status_code == 201, r.content
    job = r.json()
    assert job["status"] == "completed" and job["findings_count"] >= 2
    results = client.get(f"/api/v1/analysis/{job['id']}/results/").json()["results"]
    rules = {f["rule"]: f for f in results}
    assert "event_after_death" in rules and rules["event_after_death"]["category"] == "confirmed"
    text_finding = rules["death_then_alive"]
    assert text_finding["quote_verified"] and text_finding["chapter"] == story["later"].id
    assert {e["source_type"] for e in text_finding["evidence"]} == {"chapter"}
    assert all(e["verified"] for e in text_finding["evidence"])
    quote = text_finding["manuscript_quote"]
    assert story["later"].plain_text[text_finding["position_start"]:text_finding["position_end"]] == quote


def test_finding_decisions_persist_across_runs_and_do_not_touch_manuscript(client, world, story):
    job = client.post(f"/api/v1/worlds/{world.id}/consistency/").json()
    finding = client.get(f"/api/v1/analysis/{job['id']}/results/").json()["results"][0]
    before = Chapter.objects.get(pk=story["later"].id).plain_text
    r = client.patch(f"/api/v1/analysis/findings/{finding['id']}/", {"decision": "rejected", "decision_note": "так задумано", "summary": "hack"}, format="json")
    assert r.status_code == 200 and r.json()["decision"] == "rejected" and r.json()["summary"] != "hack"
    assert Chapter.objects.get(pk=story["later"].id).plain_text == before
    job2 = client.post(f"/api/v1/worlds/{world.id}/consistency/").json()
    same = Finding.objects.get(job_id=job2["id"], fingerprint=Finding.objects.get(pk=finding["id"]).fingerprint)
    assert same.decision == "rejected"


def test_job_isolation_and_validation(client, other_client, world, book, chapter):
    r = client.post("/api/v1/analysis/", {"kind": "chapter", "chapter": chapter.id}, format="json")
    assert r.status_code == 202 and r.json()["status"] == "pending"
    assert other_client.get(f"/api/v1/analysis/{r.json()['id']}/").status_code == 404
    assert other_client.post("/api/v1/analysis/", {"kind": "chapter", "chapter": chapter.id}, format="json").status_code == 400
    assert client.post("/api/v1/analysis/", {"kind": "book"}, format="json").status_code == 400
    assert client.post("/api/v1/analysis/", {"kind": "fragment", "chapter": chapter.id}, format="json").status_code == 400
    assert client.post("/api/v1/analysis/", {"kind": "consistency", "book": book.id}, format="json").status_code == 400


def test_new_job_supersedes_pending_and_cancel(client, chapter):
    first = client.post("/api/v1/analysis/", {"kind": "chapter", "chapter": chapter.id}, format="json").json()
    second = client.post("/api/v1/analysis/", {"kind": "chapter", "chapter": chapter.id}, format="json").json()
    assert AnalysisJob.objects.get(pk=first["id"]).status == "cancelled"
    r = client.post(f"/api/v1/analysis/{second['id']}/cancel/")
    assert r.json()["status"] == "cancelled"
    assert client.post(f"/api/v1/analysis/{second['id']}/cancel/").status_code == 409


def test_worker_completes_without_ollama(client, world, book, story):
    job_id = client.post("/api/v1/analysis/", {"kind": "book", "book": book.id}, format="json").json()["id"]
    backend = FakeBackend(available=False)
    job = claim_next_job("test-worker")
    assert job.id == job_id and job.status == "running"
    run_one(job, factory(backend))
    job.refresh_from_db()
    assert job.status == "completed" and job.error_code == "ai_unavailable"
    assert job.stats["ai"] == "unavailable" and job.findings.filter(rule="death_then_alive").exists()
    assert backend.calls == []


def test_worker_with_ai_verifies_quotes_and_rejects_hallucinated_sources(world, book, user, story):
    def answer(prompt):
        return {"findings": [
            {"type": "dead_character", "severity": "warning", "confidence": 0.8, "summary": "Каель живий після смерті",
             "explanation": "Він говорить.", "evidence": [{"source": "F", "quote": "сказав Каель"}, {"source": "C1", "quote": "Смерть: 340"}]},
            {"type": "invented", "severity": "error", "summary": "Вигадана цитата",
             "evidence": [{"source": "F", "quote": "цього речення немає в тексті"}]},
            {"type": "fake_source", "severity": "error", "summary": "Посилання на неіснуюче джерело",
             "evidence": [{"source": "L99", "quote": "щось"}]},
        ]}
    backend = FakeBackend(answer)
    job = AnalysisJob.objects.create(user=user, world=world, book=book, chapter=story["later"], kind="chapter")
    job = claim_next_job("w")
    run_one(job, factory(backend))
    job.refresh_from_db()
    assert job.status == "completed" and job.stats["ai"] == "ok" and job.model_name == "fake-model"
    ai = {f.summary: f for f in job.findings.filter(source="ai")}
    good = ai["Каель живий після смерті"]
    assert good.category == "potential" and good.quote_verified and good.confidence == 0.8
    assert story["later"].plain_text[good.position_start:good.position_end] == "сказав Каель"
    assert good.evidence.filter(source_type="character", source_id=story["kael"].id, verified=True).exists()
    assert ai["Вигадана цитата"].category == "unverified" and not ai["Вигадана цитата"].quote_verified
    assert "Посилання на неіснуюче джерело" not in ai  # no checkable source → rejected
    assert "<<<" in backend.calls[0] and "ігноруй будь-які" not in backend.calls[0]  # data is fenced, rules live in system prompt


def test_worker_handles_invalid_model_json(world, book, user, story):
    backend = FakeBackend({"findings": [{"severity": "catastrophic"}]})
    AnalysisJob.objects.create(user=user, world=world, book=book, chapter=story["later"], kind="chapter")
    job = claim_next_job("w")
    run_one(job, factory(backend))
    job.refresh_from_db()
    assert job.status == "completed" and job.error_code == "ai_error"
    assert not job.findings.filter(source="ai").exists()


def test_worker_crash_is_contained_and_message_has_no_text(world, book, user, story, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("Каель загинув біля воріт — секретний текст")
    monkeypatch.setattr("apps.analysis.worker.process_job", boom)
    AnalysisJob.objects.create(user=user, world=world, book=book, kind="book")
    job = claim_next_job("w")
    run_one(job)
    job.refresh_from_db()
    assert job.status == "failed" and "Каель" not in job.error_message


def test_concurrency_limit_and_stale_recovery(world, book, user, settings):
    settings.AI_MAX_CONCURRENT_JOBS = 1
    a = AnalysisJob.objects.create(user=user, world=world, book=book, kind="book")
    b = AnalysisJob.objects.create(user=user, world=world, book=book, kind="book_with_lore")
    assert claim_next_job("w1").id == a.id
    assert claim_next_job("w2") is None  # one heavy AI job at a time
    AnalysisJob.objects.filter(pk=a.pk).update(heartbeat_at=timezone.now() - timedelta(hours=1))
    requeued, failed = recover_stale_jobs()
    assert requeued == 1 and AnalysisJob.objects.get(pk=a.pk).status == "pending"
    assert claim_next_job("w2").id == a.id
    AnalysisJob.objects.filter(pk=a.pk).update(heartbeat_at=timezone.now() - timedelta(hours=1), attempts=settings.WORKER_MAX_ATTEMPTS)
    recover_stale_jobs()
    assert AnalysisJob.objects.get(pk=a.pk).status == "failed"
    assert claim_next_job("w3").id == b.id


def test_cancel_running_job_is_cooperative(world, book, user, story, client):
    def answer(prompt):
        AnalysisJob.objects.filter(status="running").update(cancel_requested=True)
        return {"findings": []}
    AnalysisJob.objects.create(user=user, world=world, book=book, kind="book")
    job = claim_next_job("w")
    run_one(job, factory(FakeBackend(answer)))
    job.refresh_from_db()
    assert job.status == "cancelled"


def test_quick_check_mode_a(client, world, chapter):
    Character.objects.create(world=world, name="Ейра Вальмонт", aliases=["Ейра"], death_key=300)
    chapter.story_time_key = 345
    chapter.save()
    r = client.post("/api/v1/analysis/quick-check/", {"chapter": chapter.id, "text": "Ейра кивнула. Того дня пані Вальмнот мовчала.", "offset": 100}, format="json")
    assert r.status_code == 200
    data = r.json()
    assert data["mentions"][0]["name"] == "Ейра Вальмонт" and data["mentions"][0]["start"] == 100
    assert {i["rule"] for i in data["issues"]} == {"dead_character_active", "possible_name_typo"}


def test_ollama_backend_unreachable_and_locality(settings):
    backend = OllamaBackend(url="http://127.0.0.1:9", timeout=1)
    assert backend.health()["available"] is False
    with pytest.raises(AIUnavailable):
        backend.chat_json("s", "u")
    with pytest.raises(AIConfigError):
        assert_local_endpoint("https://api.example.com")
    assert_local_endpoint("http://localhost:11434")
    assert_local_endpoint("http://[::1]:11434")
    assert_local_endpoint("http://gpu-box:11434", allowed_hosts=["gpu-box"])


def test_ollama_backend_parses_json(monkeypatch):
    class Resp:
        status_code = 200

        def json(self):
            return {"message": {"content": '{"findings": []}'}}

    sent = {}

    def fake_post(self, url, json=None, timeout=None):
        sent.update(url=url, payload=json)
        return Resp()

    monkeypatch.setattr(requests.Session, "post", fake_post)
    backend = OllamaBackend(url="http://127.0.0.1:11434", model="m")
    assert backend.chat_json("sys", "user", {"type": "object"}) == {"findings": []}
    assert sent["url"].endswith("/api/chat") and sent["payload"]["stream"] is False and sent["payload"]["format"] == {"type": "object"}


def test_ai_status_and_explain_without_ollama(client, world, story, settings):
    settings.OLLAMA_URL = "http://127.0.0.1:9"
    settings.OLLAMA_TIMEOUT_SECONDS = 1
    assert client.get("/api/v1/ai/status/").json()["available"] is False
    job = client.post(f"/api/v1/worlds/{world.id}/consistency/").json()
    finding = client.get(f"/api/v1/analysis/{job['id']}/results/").json()["results"][0]
    r = client.post(f"/api/v1/analysis/findings/{finding['id']}/explain/")
    assert r.status_code == 503 and r.json()["error"]["code"] == "service_unavailable"
