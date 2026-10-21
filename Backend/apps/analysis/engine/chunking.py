"""Split long texts into logical, overlapping fragments for the local model."""
from dataclasses import dataclass


@dataclass
class Chunk:
    chapter_id: int
    index: int
    start: int
    end: int
    text: str


def split_text(text, chapter_id, max_chars=3500, overlap=300):
    """Paragraph-aware chunking.

    Paragraphs are packed until ``max_chars``; each next chunk starts ``overlap`` characters
    before the previous end (snapped to a paragraph or sentence boundary) so that an issue
    crossing a boundary is visible to the model. Overly long paragraphs are cut at sentence
    boundaries.
    """
    if not text:
        return []
    chunks, start, index, length = [], 0, 0, len(text)
    while start < length:
        end = min(length, start + max_chars)
        if end < length:
            cut = text.rfind("\n\n", start + max_chars // 2, end)
            if cut == -1:
                cut = max(text.rfind(". ", start + max_chars // 2, end), text.rfind("! ", start + max_chars // 2, end), text.rfind("? ", start + max_chars // 2, end))
                cut = cut + 1 if cut != -1 else end
            end = cut
        chunks.append(Chunk(chapter_id, index, start, end, text[start:end]))
        index += 1
        if end >= length:
            break
        next_start = max(start + 1, end - overlap)
        boundary = text.find(" ", next_start, end)
        start = boundary + 1 if boundary != -1 else end
    return chunks
