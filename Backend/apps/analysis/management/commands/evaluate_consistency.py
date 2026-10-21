import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.analysis.engine.evaluation import evaluate


class Command(BaseCommand):
    help = "Проганяє контрольний набір і обчислює precision / recall / F1 детермінованого аналізатора."

    def add_arguments(self, parser):
        parser.add_argument("--markdown", help="Записати звіт у Markdown-файл.")
        parser.add_argument("--json", action="store_true", help="Вивести сирий JSON.")

    def handle(self, *args, **options):
        result = evaluate()
        if options["json"]:
            self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
            return
        lines = [
            "# Оцінка детермінованого аналізатора узгодженості",
            "",
            "Згенеровано командою `python manage.py evaluate_consistency --markdown ../docs/EVALUATION.md`.",
            "Позитивом вважаються результати категорій «підтверджено» та «потенційно»; «недостатньо даних» рахується окремо.",
            "",
            "| Метрика | Значення |",
            "|---|---|",
            f"| Випадків | {len(result['cases'])} |",
            f"| TP / FP / FN | {result['tp']} / {result['fp']} / {result['fn']} |",
            f"| Precision | {result['precision']} |",
            f"| Recall | {result['recall']} |",
            f"| F1 | {result['f1']} |",
            f"| Час виконання (усі випадки) | {result['total_ms']} мс |",
            f"| Цитат з рукопису / перевірених | {result['quotes_total']} / {result['quotes_verified']} |",
            f"| Частка перевірених цитат | {result['quote_verified_share']} |",
            "",
            "| Випадок | Очікувано | Знайдено | TP | FP | FN | «Недостатньо даних» | мс |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for row in result["cases"]:
            lines.append(
                f"| `{row['case']}` — {row['description']} | {', '.join(row['expected']) or '—'} | "
                f"{', '.join(row['predicted']) or '—'} | {row['tp']} | {row['fp']} | {row['fn']} | "
                f"{row['insufficient']}{'' if row['insufficient_ok'] else ' ⚠'} | {row['ms']} |"
            )
        lines += [
            "",
            "**Застереження.** Набір невеликий і складався разом із правилами, тому високі значення на "
            "«звичайних» випадках не є оцінкою на реальних рукописах. Випадки `hard_*` навмисно описують "
            "відомі обмеження (перифраз смерті, імʼя-омонім) і мають справжні мітки — саме вони знижують метрики.",
            "",
        ]
        text = "\n".join(lines)
        if options["markdown"]:
            Path(options["markdown"]).write_text(text, encoding="utf-8")
            self.stdout.write(f"Звіт записано: {options['markdown']}")
        else:
            self.stdout.write(text)
