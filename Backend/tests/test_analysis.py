from datetime import timedelta

import pytest
import requests
from django.utils import timezone

from apps.ai.backends import AIResponseError, AIUnavailable, GeminiBackend
from apps.ai.service import AIService
from apps.analysis.models import AnalysisJob, ChapterScan, Finding
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

    def chat_json(self, system, user, schema=None, temperature=0.1, **options):
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


def test_worker_completes_without_ai(client, world, book, story):
    job_id = client.post("/api/v1/analysis/", {"kind": "book", "book": book.id}, format="json").json()["id"]
    backend = FakeBackend(available=False)
    job = claim_next_job("test-worker")
    assert job.id == job_id and job.status == "running"
    run_one(job, factory(backend))
    job.refresh_from_db()
    assert job.status == "completed" and job.error_code == "ai_unavailable"
    assert job.stats["ai"] == "unavailable" and job.findings.filter(rule="death_then_alive").exists()
    assert backend.calls == []


def test_worker_with_ai_verifies_quotes_and_rejects_hallucinated_sources(world, book, user, story, chapter):
    story["kael"].death_chapter = chapter  # the death is placed in the story: chapter 1
    story["kael"].save()
    status = "Статус у цьому розділі: загинув"

    def answer(prompt):
        if "Перевір одну підозру" in prompt:
            return {"verdict": "contradiction", "reason": "Каель загинув у розділі 1, а тут говорить."}
        return {"facts": [], "issues": [
            {"type": "dead_character", "severity": "warning", "confidence": 0.8, "summary": "Каель живий після смерті",
             "explanation": "Він говорить.", "evidence": [{"source": "F", "quote": "сказав Каель і рушив"}, {"source": "C1", "quote": status}]},
            {"type": "invented", "severity": "error", "summary": "Вигадана цитата",
             "evidence": [{"source": "F", "quote": "цього речення немає в тексті"}, {"source": "C1", "quote": status}]},
            {"type": "fake_source", "severity": "error", "summary": "Посилання на неіснуюче джерело",
             "evidence": [{"source": "F", "quote": "сказав Каель і рушив"}, {"source": "L99", "quote": "щось"}]},
            {"type": "name_only", "severity": "warning", "summary": "Доказ — лише імʼя",
             "evidence": [{"source": "F", "quote": "сказав Каель і рушив"}, {"source": "C1", "quote": "Імʼя: Каель"}]},
            {"type": "unsure", "severity": "warning", "confidence": 0.2, "summary": "Модель не впевнена",
             "evidence": [{"source": "F", "quote": "сказав Каель і рушив"}, {"source": "C1", "quote": status}]},
        ]}
    backend = FakeBackend(answer)
    AnalysisJob.objects.create(user=user, world=world, book=book, chapter=story["later"], kind="chapter")
    job = claim_next_job("w")
    run_one(job, factory(backend))
    job.refresh_from_db()
    assert job.status == "completed" and job.stats["ai"] == "ok" and job.model_name == "fake-model"
    ai = {f.summary: f for f in job.findings.filter(source="ai")}
    good = ai["Каель живий після смерті"]
    assert good.category == "potential" and good.quote_verified and good.confidence == 0.8
    assert story["later"].plain_text[good.position_start:good.position_end] == "сказав Каель і рушив"
    assert good.evidence.filter(source_type="character", source_id=story["kael"].id, verified=True).exists()
    # an invented quote, a made-up source, a name instead of a fact, low confidence: dropped
    assert set(ai) == {"Каель живий після смерті"}
    assert "Перевірка в контексті" in good.explanation and job.stats["judge"] == {"contradiction": 1}
    assert "<<<" in backend.calls[0] and "ігноруй будь-які" not in backend.calls[0]  # data is fenced, rules live in system prompt


def test_worker_handles_invalid_model_json(world, book, user, story):
    backend = FakeBackend({"issues": [{"severity": "catastrophic"}]})
    AnalysisJob.objects.create(user=user, world=world, book=book, chapter=story["later"], kind="chapter")
    job = claim_next_job("w")
    run_one(job, factory(backend))
    job.refresh_from_db()
    # the broken answer is retried once, then the piece is skipped and marked for the next run
    assert job.status == "completed" and job.stats["failed_pieces"] == 1 and len(backend.calls) == 2
    assert not job.findings.filter(source="ai").exists()
    assert ChapterScan.objects.get(chapter=story["later"]).failed_chunks == 1


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
        return {"issues": [], "facts": []}
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


class FakeResponse:
    def __init__(self, status, body):
        self.status_code, self.body = status, body

    def json(self):
        return self.body


def gemini(monkeypatch, *responses, get=None):
    """GeminiBackend whose HTTP calls return ``responses`` one after another (no network)."""
    sent = []

    def fake_post(self, url, headers=None, json=None, timeout=None):
        sent.append({"url": url, "headers": headers, "body": json})
        return responses[min(len(sent), len(responses)) - 1]

    monkeypatch.setattr(requests.Session, "post", fake_post)
    if get is not None:
        monkeypatch.setattr(requests.Session, "get", lambda self, url, headers=None, timeout=None: get)
    monkeypatch.setattr("apps.ai.backends.time.sleep", lambda s: None)
    return GeminiBackend(api_key="test-key", model="main", fallback_model="lite", min_interval=0, thinking="low"), sent


def answer_with(text, finish="STOP"):
    return FakeResponse(200, {"candidates": [{"finishReason": finish, "content": {"parts": [{"text": text}]}}]})


def test_gemini_backend_request_and_json(monkeypatch):
    backend, sent = gemini(monkeypatch, answer_with('{"findings": []}'))
    assert backend.chat_json("sys", "user", {"type": "object"}, max_tokens=100) == {"findings": []}
    body = sent[0]["body"]
    assert sent[0]["url"].endswith("/models/main:generateContent")
    assert sent[0]["headers"]["x-goog-api-key"] == "test-key" and "key=" not in sent[0]["url"]  # the key never goes in the URL
    assert body["systemInstruction"]["parts"][0]["text"] == "sys" and body["contents"][0]["parts"][0]["text"] == "user"
    config = body["generationConfig"]
    assert config["responseMimeType"] == "application/json" and config["responseJsonSchema"] == {"type": "object"}
    assert config["maxOutputTokens"] == 100 and config["thinkingConfig"] == {"thinkingLevel": "low"}
    assert all(s["threshold"] == "BLOCK_NONE" for s in body["safetySettings"])  # fiction: violence must not be filtered


def test_gemini_backend_retries_overload_and_falls_back(monkeypatch):
    busy = FakeResponse(503, {"error": {"message": "high demand"}})
    backend, sent = gemini(monkeypatch, busy, busy, answer_with('{"ok": true}'))
    assert backend.chat_json("s", "u") == {"ok": True}
    assert [c["url"].split("/models/")[1] for c in sent] == ["main:generateContent", "main:generateContent", "lite:generateContent"]


def test_gemini_backend_rate_limit_and_daily_quota(monkeypatch):
    limited = FakeResponse(429, {"error": {"message": "rate", "details": [{"retryDelay": "7s"}]}})
    backend, sent = gemini(monkeypatch, limited, answer_with('{"ok": true}'))
    assert backend.chat_json("s", "u") == {"ok": True} and len(sent) == 2
    daily = FakeResponse(429, {"error": {"message": "Quota exceeded for metric: requests per day"}})
    backend, _ = gemini(monkeypatch, daily)
    with pytest.raises(AIUnavailable, match="Денний"):
        backend.chat_json("s", "u")


def test_gemini_backend_errors_and_truncation(monkeypatch):
    backend, _ = gemini(monkeypatch, FakeResponse(403, {"error": {"message": "API key not valid"}}))
    with pytest.raises(AIUnavailable, match="ключ"):
        backend.chat_json("s", "u")
    backend, _ = gemini(monkeypatch, FakeResponse(200, {"promptFeedback": {"blockReason": "SAFETY"}}))
    with pytest.raises(AIResponseError):
        backend.chat_json("s", "u")
    backend, _ = gemini(monkeypatch, answer_with('{"facts": [{"who": "A"}, {"who": "B", "fa', finish="MAX_TOKENS"))
    assert backend.chat_json("s", "u") == {"facts": [{"who": "A"}]}
    with pytest.raises(AIUnavailable, match="GEMINI_API_KEY"):
        GeminiBackend(api_key="").chat_json("s", "u")


def test_gemini_health(monkeypatch):
    backend, _ = gemini(monkeypatch, get=FakeResponse(200, {"name": "models/main"}))
    assert backend.health()["available"] is True
    backend, _ = gemini(monkeypatch, get=FakeResponse(403, {}))
    assert backend.health()["available"] is False
    assert "GEMINI_API_KEY" in GeminiBackend(api_key="").health()["error"]


def test_ai_status_and_explain_without_ai(client, world, story, settings):
    settings.GEMINI_API_KEY = ""
    assert client.get("/api/v1/ai/status/").json()["available"] is False
    job = client.post(f"/api/v1/worlds/{world.id}/consistency/").json()
    finding = client.get(f"/api/v1/analysis/{job['id']}/results/").json()["results"][0]
    r = client.post(f"/api/v1/analysis/findings/{finding['id']}/explain/")
    assert r.status_code == 503 and r.json()["error"]["code"] == "service_unavailable"


# --- whole-book story scan -------------------------------------------------------------

@pytest.fixture
def saga(world, book, chapter):
    """Chapter 1: Каель loses his left arm. Chapter 2: unrelated. Chapter 3: he claps with both hands."""
    Character.objects.create(world=world, name="Каель", status="alive")
    set_text(chapter, "У битві біля мосту Каель втратив ліву руку.")
    middle = Chapter.objects.create(book=book, title="Розділ 2", order=1)
    set_text(middle, "Дощ ішов над містом цілу ніч.")
    later = Chapter.objects.create(book=book, title="Розділ 3", order=2)
    set_text(later, "Каель радісно заплескав обома долонями.")
    return {"first": chapter, "middle": middle, "later": later}


def story_answer(prompt):
    """A fake model: remembers the lost arm and spots the contradiction when the memory shows it."""
    if "Перевір одну підозру" in prompt:
        return {"verdict": "contradiction", "reason": "Без лівої руки не плескають обома долонями."}
    if "втратив ліву руку" in prompt and "заплескав" not in prompt:
        return {"issues": [], "facts": [{"who": "Каель", "kind": "injury", "fact": "Каель лишився без лівої руки", "quote": "Каель втратив ліву руку"}]}
    if "заплескав" in prompt and "[P1]" in prompt:
        return {"facts": [], "issues": [{
            "type": "lost_limb", "severity": "warning", "confidence": 0.9, "summary": "Каель плеще обома долонями, хоча втратив руку",
            "explanation": "У розділі 1 Каель втратив ліву руку.",
            "evidence": [{"source": "F", "quote": "заплескав обома долонями"}, {"source": "P1", "quote": "Каель втратив ліву руку"}],
        }]}
    return {"issues": [], "facts": []}


def run_book_scan(world, book, user, backend, **params):
    AnalysisJob.objects.create(user=user, world=world, book=book, kind="book", params=params)
    job = claim_next_job("w")
    run_one(job, factory(backend))
    job.refresh_from_db()
    return job


def test_story_scan_remembers_earlier_chapters(world, book, user, saga):
    backend = FakeBackend(story_answer)
    job = run_book_scan(world, book, user, backend)
    assert job.status == "completed" and job.stats["ai"] == "ok" and job.stats["scanned"] == 3
    finding = job.findings.get(source="ai")
    assert finding.chapter_id == saga["later"].id and finding.quote_verified
    assert saga["later"].plain_text[finding.position_start:finding.position_end] == "заплескав обома долонями"
    earlier = finding.evidence.get(source_id=saga["first"].id)  # cites chapter 1 with its own quote and position
    assert earlier.source_type == "chapter" and earlier.source_label.startswith("Раніше")
    assert saga["first"].plain_text[earlier.position_start:earlier.position_end] == "Каель втратив ліву руку"
    # the unrelated chapter got no memory about Каель (only facts about people it mentions are recalled)
    middle_prompt = next(c for c in backend.calls if "Дощ ішов" in c)
    assert "[P1]" not in middle_prompt
    facts = ChapterScan.objects.get(chapter=saga["first"]).facts
    assert facts[0]["quote"] == "Каель втратив ліву руку" and facts[0]["refs"] and facts[0]["kind"] == "injury"


def test_story_scan_resumes_and_rescans_only_changed_chapters(world, book, user, saga):
    first = run_book_scan(world, book, user, FakeBackend(story_answer))
    again = FakeBackend(story_answer)
    second = run_book_scan(world, book, user, again)
    assert again.calls == [] and second.stats["skipped"] == 3  # nothing changed: no model calls
    assert second.findings.filter(source="ai").count() == 1  # earlier findings carried into the new results
    assert not first.findings.filter(source="ai").exists()
    set_text(saga["later"], "Каель радісно заплескав обома долонями. Потім сів.")
    edited = FakeBackend(story_answer)
    run_book_scan(world, book, user, edited)
    # only the edited chapter (scan + the judge of its one candidate), still with the memory
    assert len(edited.calls) == 2 and "[P1]" in edited.calls[0]
    assert Finding.objects.filter(world=world, source="ai").count() == 1  # replaced, not duplicated
    full = FakeBackend(story_answer)
    run_book_scan(world, book, user, full, full=True)
    assert len(full.calls) == 4  # one request per chapter + one judge request for the candidate


def test_story_scan_stops_when_model_disappears_and_continues_later(world, book, user, saga):
    calls = {"n": 0}

    def flaky(prompt):
        calls["n"] += 1
        if calls["n"] == 2:
            raise AIUnavailable("Gemini недоступний")
        return story_answer(prompt)

    backend = FakeBackend(flaky)
    job = run_book_scan(world, book, user, backend)
    assert job.status == "completed" and job.error_code == "ai_unavailable" and "продовжиться" in job.progress_message
    assert ChapterScan.objects.filter(chapter=saga["first"]).exists() and not ChapterScan.objects.filter(chapter=saga["middle"]).exists()
    resumed = FakeBackend(story_answer)
    job = run_book_scan(world, book, user, resumed)
    assert len(resumed.calls) == 3 and job.stats["skipped"] == 1
    assert job.findings.filter(source="ai", chapter=saga["later"]).exists()  # memory from chapter 1 survived the stop


def test_decided_findings_are_not_recreated_on_rescan(world, book, user, saga):
    job = run_book_scan(world, book, user, FakeBackend(story_answer))
    finding = job.findings.get(source="ai")
    finding.decision = "rejected"
    finding.save()
    run_book_scan(world, book, user, FakeBackend(story_answer), full=True)
    assert list(Finding.objects.filter(world=world, source="ai").values_list("decision", flat=True)) == ["rejected"]


def test_story_scan_reads_pieces_of_a_chapter_in_parallel(world, book, user, saga, settings):
    settings.AI_SCAN_CHUNK_CHARS = 60
    settings.AI_CHUNK_OVERLAP = 0
    set_text(saga["later"], "Минуло два тижні, і над містом знову зійшло холодне сонце.",
             "Каель радісно заплескав обома долонями, коли побачив друзів.", "Потім усі разом рушили до старого порту.")
    backend = FakeBackend(story_answer)
    job = run_book_scan(world, book, user, backend)
    scan = ChapterScan.objects.get(chapter=saga["later"])
    assert scan.chunks >= 3 and scan.failed_chunks == 0 and job.stats["pieces"] >= 5
    finding = job.findings.get(source="ai")  # found in the middle piece, with the memory of chapter 1
    assert saga["later"].plain_text[finding.position_start:finding.position_end] == "заплескав обома долонями"


def test_truncated_model_answer_keeps_complete_items():
    from apps.ai.backends import close_truncated_json

    cut = '{"facts": [{"who": "Каель", "fact": "втратив руку } у бою", "quote": "\\"рука\\""}, {"who": "Ейра", "fa'
    assert close_truncated_json(cut) == {"facts": [{"who": "Каель", "fact": "втратив руку } у бою", "quote": '"рука"'}]}
    assert close_truncated_json('{"fac') is None



# --- research fixes: time of a status, judge in context, rules -----------------------------------

def test_dead_status_without_time_is_not_used_against_chapters(world, book, chapter):
    from apps.analysis.engine.loader import load_snapshot
    from apps.analysis.engine.story import status_line

    later = Chapter.objects.create(book=book, title="Розділ 9", order=8)
    jon = Character.objects.create(world=world, name="Джонатан", status="dead", death_key=2027, death_label="2027")
    snap = load_snapshot(world)
    c = snap.character(jon.id)
    first, ninth = (next(x for x in snap.chapters if x.id == ch.id) for ch in (chapter, later))
    assert c.dead_in(ninth) is None and status_line(c, ninth) is None  # no death chapter, no chapter time: unknown
    jon.death_chapter = chapter
    jon.save()
    c = load_snapshot(world).character(jon.id)
    assert c.dead_in(first) is False and c.dead_in(ninth) is True
    assert status_line(c, ninth).startswith("Статус у цьому розділі: загинув") and "Розділ 1" in status_line(c, ninth)
    assert "живий" in status_line(c, first) and "пізніше" in status_line(c, first)


def test_dead_character_active_uses_the_death_chapter(world, book, chapter):
    from apps.analysis.engine.loader import load_snapshot
    from apps.analysis.engine.manuscript import ManuscriptAnalyzer

    later = Chapter.objects.create(book=book, title="Розділ 3", order=2)
    set_text(later, "— Ходімо, — сказав Каель і рушив до брами.")
    kael = Character.objects.create(world=world, name="Каель", status="dead")
    assert not ManuscriptAnalyzer(load_snapshot(world)).dead_character_active()  # status without time: silent
    kael.death_chapter = chapter
    kael.save()
    found = ManuscriptAnalyzer(load_snapshot(world)).dead_character_active()
    assert [f.chapter_id for f in found] == [later.id] and "Розділ 1" in found[0].explanation


def test_an_attempt_is_not_a_death(world, book, chapter):
    from apps.analysis.engine.loader import load_snapshot
    from apps.analysis.engine.manuscript import ManuscriptAnalyzer

    Character.objects.create(world=world, name="Андерсон")
    set_text(chapter, "Надлюдина влила смертельну дозу отрути в тіло Андерсона.")
    later = Chapter.objects.create(book=book, title="Розділ 2", order=1)
    set_text(later, "— Ходімо, — сказав Андерсон і рушив до виходу.")
    assert not ManuscriptAnalyzer(load_snapshot(world)).death_then_alive()
    set_text(chapter, "Андерсон помер від отрути біля воріт.")
    assert ManuscriptAnalyzer(load_snapshot(world)).death_then_alive()


def test_rule_findings_are_replaced_not_copied(client, world, story):
    for _ in range(3):
        client.post(f"/api/v1/worlds/{world.id}/consistency/")
    rules = Finding.objects.filter(world=world).exclude(source="ai")
    assert rules.count() == rules.values("fingerprint").distinct().count() > 0


def test_judge_sees_whole_paragraphs_and_drops_a_mere_mention(world, book, user, saga):
    seen = []

    def answer(prompt):
        if "Перевір одну підозру" in prompt:
            seen.append(prompt)
            return {"verdict": "mention_only", "reason": "Про Каеля лише говорять."}
        return story_answer(prompt)

    job = run_book_scan(world, book, user, FakeBackend(answer))
    assert not job.findings.filter(source="ai").exists() and job.stats["judge"] == {"mention_only": 1}
    # the judge got the paragraph around each quote, with the quote marked, not just the short quotes
    assert "⟦заплескав обома долонями⟧" in seen[0] and "радісно" in seen[0]
    assert "⟦Каель втратив ліву руку⟧" in seen[0] and "У битві біля мосту" in seen[0]
