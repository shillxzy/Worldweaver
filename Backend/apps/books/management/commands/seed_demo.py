"""Demo data for a local account (the former hard-coded frontend mock data).

    python manage.py seed_demo --email author@example.com

The user must already exist (register in the app first). Running twice does not duplicate
books: existing demo books with the same title are skipped.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.boards.models import Board, BoardItem
from apps.books.documents import document_stats, text_to_document
from apps.books.models import Book, Chapter
from apps.worlds.models import Character, EventParticipant, Faction, FactionMembership, LoreEntry, TimelineEvent, World

DEMO = [
    {
        "title": "Сяйво безодні", "genre": "Темне фентезі", "accent": "#3fb8c9", "time_unit": "рік",
        "desc": "Світ, де світло живе лише на дні океану.",
        "characters": [
            ("Ейра Вальмонт", ["Ейра"], "Картографка, що шукає шлях до безодні.", "Ордо Глибин", 318, None),
            ("Каель", [], "Колишній капітан варти.", "Береговий дозор", 305, None),
        ],
        "factions": [("Ордо Глибин", "Орден хранителів підводних архівів.", "#3fb8c9"), ("Береговий дозор", "Варта узбережжя.", "#e0b36a")],
        "lore": [
            ("Берег Тиші", "location", "Місто на краю світу."),
            ("Перлина Сяйва", "item", "Джерело світла з безодні."),
            ("Левіафан", "creature", "Прадавній мешканець глибин."),
        ],
        "board": [
            ("Сюжетні повороти", "#e879a8", ["Ейра зраджує орден", "Перлина — підробка"]),
            ("Ідеї для розділів", "#3fb8c9", ["Спуск у безодню", "Сон про Левіафана"]),
            ("Чернетки", "#e0b36a", ["Монолог Каеля"]),
        ],
        "events": [
            (1, "1 рік", "Затоплення Старого світу", "Океан поглинув усі континенти.", []),
            (212, "212 рік", "Заснування Ордо Глибин", "Перші архіви під водою.", []),
            (340, "340 рік", "Перше сяйво з безодні", "Початок подій книги.", ["Ейра Вальмонт", "Каель"]),
        ],
        "chapters": [
            ("Туман", 340, "Туман повільно сповзав із води, і Ейра вперше відчула, що світло знизу кличе її не вперед, а додому."),
            ("Берег Тиші", 340, "Берег Тиші не мав назви на жодній карті, але вона знала кожен його камінь. Перлина в її долоні тремтіла, наче жива."),
        ],
    },
    {
        "title": "Катарсис розуму", "genre": "Психологічна фантастика", "accent": "#c58bff", "time_unit": "рік",
        "desc": "Лікування пам’яті, яке змінює особистість.",
        "characters": [
            ("Доктор Лео Март", ["Март"], "Нейропсихіатр з темним минулим.", "Інститут Катарсису", 2005, None),
            ("Нова", [], "Пацієнтка, що не памʼятає себе.", "Пацієнти", None, None),
        ],
        "factions": [("Інститут Катарсису", "Клініка, що стирає травми.", "#c58bff"), ("Пацієнти", "Ті, хто довірив інституту памʼять.", "#7aa2ff")],
        "lore": [
            ("Палата №7", "location", "Закрите крило інституту."),
            ("Нейрозонд", "item", "Пристрій для доступу до спогадів."),
            ("Відлуння", "creature", "Свідомість, що живе в спогадах."),
        ],
        "board": [
            ("Сюжетні повороти", "#e879a8", ["Март — теж пацієнт", "Нова створює спогади"]),
            ("Ідеї для розділів", "#c58bff", ["Перший сеанс", "Втеча з палати"]),
            ("Чернетки", "#e0b36a", ["Діалог у коридорі"]),
        ],
        "events": [
            (2041, "2041", "Відкриття Інституту", "Перші пацієнти й перші обіцянки.", []),
            (2049, "2049", "Перший сеанс Нейрозонда", "Спогади вперше стали доступні.", ["Доктор Лео Март"]),
            (2052, "2052", "Інцидент у Палаті №7", "Початок подій книги.", ["Доктор Лео Март", "Нова"]),
        ],
        "chapters": [
            ("Коридор", 2052, "Коридор тягнувся нескінченно, і Нова вже вкотре рахувала двері, щоб переконатися, що все це відбувається насправді."),
            ("Погляд", 2052, "Доктор Март дивився на неї так, ніби знав, що вона скаже наперед. Це лякало більше, ніж забуті дні."),
        ],
    },
]


class Command(BaseCommand):
    help = "Створює демонстраційні світи й книги для вказаного користувача."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)

    @transaction.atomic
    def handle(self, *args, email, **options):
        user = get_user_model().objects.filter(username=email.strip().lower()).first()
        if user is None:
            raise CommandError("Користувача не знайдено. Спершу зареєструйтеся в застосунку.")
        for data in DEMO:
            if Book.objects.filter(world__owner=user, title=data["title"]).exists():
                self.stdout.write(f"Пропущено (вже існує): {data['title']}")
                continue
            world = World.objects.create(owner=user, name=data["title"], genre=data["genre"], description=data["desc"], time_unit_label=data["time_unit"])
            factions = {name: Faction.objects.create(world=world, name=name, description=desc, color=color) for name, desc, color in data["factions"]}
            characters = {}
            for name, aliases, summary, faction, birth, death in data["characters"]:
                c = Character.objects.create(
                    world=world, name=name, aliases=aliases, summary=summary, status="alive",
                    birth_key=birth, birth_precision="approximate" if birth else "unknown", death_key=death,
                )
                FactionMembership.objects.create(character=c, faction=factions[faction])
                characters[name] = c
            for title, category, content in data["lore"]:
                LoreEntry.objects.create(world=world, title=title, category=category, content=content)
            for key, label, title, text, participants in data["events"]:
                event = TimelineEvent.objects.create(world=world, title=title, description=text, start_key=key, start_label=label)
                for name in participants:
                    EventParticipant.objects.create(event=event, character=characters[name])
            book = Book.objects.create(world=world, title=data["title"], genre=data["genre"], description=data["desc"], accent=data["accent"])
            for order, (title, time_key, text) in enumerate(data["chapters"]):
                content = text_to_document(text)
                plain, words = document_stats(content)
                Chapter.objects.create(book=book, title=title, order=order, content=content, plain_text=plain, word_count=words, story_time_key=time_key)
            board = Board.objects.create(book=book, title="Щоденник")
            for i, (title, color, notes) in enumerate(data["board"]):
                column = BoardItem.objects.create(board=board, kind="column", text=title, color=color, order=i, x=i * 260)
                for j, note in enumerate(notes):
                    BoardItem.objects.create(board=board, parent=column, kind="note", text=note, order=j)
            self.stdout.write(self.style.SUCCESS(f"Створено: {data['title']}"))
