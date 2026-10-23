/** Types mirroring the Worldweaver REST API (see Backend/apps/<app>/serializers.py). */

export type Precision = 'exact' | 'approximate' | 'unknown'
/** Decimals arrive from DRF as strings ("212.0000"). */
export type TimeKey = string | null

export type User = { id: number; name: string; email: string; bio: string; has_avatar: boolean; avatar_version: number; date_joined: string }

export type UserSettings = {
  theme: 'dark' | 'light'
  language: 'uk' | 'en'
  quick_checks_enabled: boolean
  spellcheck_enabled: boolean
  updated_at?: string
}

export type World = {
  id: number
  name: string
  description: string
  genre: string
  rules: string
  tech_level: string
  magic_system: string
  time_unit_label: string
  calendar_notes: string
  created_at: string
  updated_at: string
  characters_count: number
  factions_count: number
  lore_count: number
  events_count: number
  books_count: number
  my_role: Role
}

export type CharacterStatus = 'alive' | 'dead' | 'missing' | 'unknown' | 'other'

export type MembershipBrief = {
  id: number; faction: number; faction_name: string; faction_color: string; role: string
  start_label: string; end_label: string; start_key: TimeKey; end_key: TimeKey
}

export type Character = {
  id: number
  name: string
  aliases: string[]
  summary: string
  biography: string
  personality: string
  appearance: string
  goals: string
  abilities: string
  age_text: string
  birth_key: TimeKey
  birth_label: string
  birth_precision: Precision
  death_key: TimeKey
  death_label: string
  death_precision: Precision
  status: CharacterStatus
  facts: { label: string; value: string }[]
  notes: string
  has_portrait: boolean
  has_banner: boolean
  banner_color: string
  page_id: number | null
  memberships: MembershipBrief[]
  created_at: string
  updated_at: string
}

export type Faction = {
  id: number; name: string; description: string; goals: string; ideology: string
  color: string; emblem: string; members_count: number; page_id: number | null; created_at: string; updated_at: string
}

export type Membership = {
  id: number; character: number; character_name: string; faction: number; faction_name: string; role: string
  start_key: TimeKey; start_label: string; end_key: TimeKey; end_label: string; notes: string
}

export type LoreCategory =
  | 'history' | 'geography' | 'location' | 'magic' | 'culture' | 'technology'
  | 'religion' | 'rules' | 'item' | 'creature' | 'custom'

export type LoreEntry = {
  id: number; title: string; content: string; category: LoreCategory; custom_category: string
  tags: string[]; related_characters: number[]; related_factions: number[]; created_at: string; updated_at: string
}

export type ParticipantRole = 'participant' | 'mentioned' | 'posthumous'
export type Participant = { character: number; character_name?: string; role: ParticipantRole; note?: string }

export type TimelineEvent = {
  id: number; title: string; description: string
  start_key: TimeKey; start_label: string; end_key: TimeKey; end_label: string
  precision: Precision; uncertainty: string; sort_order: number
  participants: Participant[]; factions: number[]; lore_entries: number[]; chapters: number[]
  created_at: string; updated_at: string
}

export type Dependency = {
  id: number; before: number; before_title: string; after: number; after_title: string
  kind: 'before' | 'causes'; min_gap: TimeKey; description: string; created_at: string
}

export type Chronology = { order: number[]; has_cycle: boolean; cycle: number[]; edges: { before: number; after: number }[] }

export type EntityType = 'character' | 'faction' | 'event' | 'lore'
export type RelationshipKind =
  | 'alliance' | 'enmity' | 'family' | 'subordination' | 'membership' | 'acquaintance' | 'mentorship' | 'other'

export type Relationship = {
  id: number; kind: RelationshipKind
  source: { type: EntityType; id: number; label: string }
  target: { type: EntityType; id: number; label: string }
  description: string; directed: boolean
  start_key: TimeKey; start_label: string; end_key: TimeKey; end_label: string; created_at: string
}

export type BookStatus = 'idea' | 'drafting' | 'revising' | 'finished'
export type ManuscriptFormat = 'novel' | 'novella' | 'short_story' | 'screenplay' | 'other'

/** Role in a shared world; each role includes everything the roles after it may do. */
export type Role = 'owner' | 'admin' | 'editor' | 'commenter' | 'viewer'

export type Book = {
  id: number; world: number; world_name: string; title: string; description: string; genre: string
  status: BookStatus; manuscript_format: ManuscriptFormat; accent: string; has_cover: boolean
  chapters_count: number; done_chapters: number; word_count: number | null; progress: number
  my_role: Role; owner_name: string; is_public: boolean
  created_at: string; updated_at: string
}

export type ChapterStatus = 'draft' | 'revision' | 'done'

export type ChapterSummary = {
  id: number; book: number; title: string; order: number; word_count: number; status: ChapterStatus
  revision: number; story_time_key: TimeKey; story_time_label: string; is_flashback: boolean
  narrator_unreliable: boolean; is_public: boolean; updated_by_name: string; created_at: string; updated_at: string
}

/** Tiptap / ProseMirror JSON. */
export type DocNode = {
  type: string
  text?: string
  attrs?: Record<string, unknown>
  marks?: { type: string; attrs?: Record<string, unknown> }[]
  content?: DocNode[]
}

export type Chapter = ChapterSummary & { content: DocNode; plain_text: string }

export type ChapterVersion = {
  id: number; chapter: number; revision: number; title: string; word_count: number
  reason: 'autosave' | 'manual' | 'restore' | 'import'; author_name: string; created_at: string
}
export type ChapterVersionDetail = ChapterVersion & { content: DocNode; plain_text: string }

export type BoardItemKind = 'column' | 'note' | 'idea' | 'draft' | 'reference'
export type BoardItem = {
  id: number; board: number; parent: number | null; kind: BoardItemKind; text: string; color: string
  x: number; y: number; width: number; height: number; order: number; metadata: Record<string, unknown>
  created_at: string; updated_at: string
}
export type BoardConnection = { id: number; board: number; source: number; target: number; label: string; created_at: string }
export type Board = {
  id: number; title: string; book: number | null; world: number | null
  items: BoardItem[]; connections: BoardConnection[]; created_at: string; updated_at: string
}

export type JobKind = 'consistency' | 'fragment' | 'chapter' | 'book' | 'book_with_lore'
export type JobStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'

export type AnalysisJob = {
  id: number; world: number; book: number | null; chapter: number | null; kind: JobKind; status: JobStatus
  use_ai: boolean; params: Record<string, unknown>; progress: number; progress_message: string
  cancel_requested: boolean; error_code: string; error_message: string; model_name: string; attempts: number
  created_at: string; started_at: string | null; finished_at: string | null
  stats: {
    findings?: number; by_category?: Record<string, number>; quotes_total?: number; quotes_verified?: number
    seconds?: number; ai?: 'ok' | 'unavailable' | 'error' | 'not_used'; chapters?: number
  }
  findings_count: number
}

export type FindingCategory = 'confirmed' | 'potential' | 'insufficient_data' | 'unverified'
export type Severity = 'info' | 'warning' | 'error'
export type Decision = 'new' | 'accepted' | 'rejected' | 'ignored'

export type Evidence = {
  id: number; source_type: 'chapter' | 'lore' | 'page' | 'character' | 'faction' | 'event' | 'relationship' | 'dependency' | 'membership'
  source_id: number; source_label: string; quote: string
  position_start: number | null; position_end: number | null; verified: boolean
}

export type Finding = {
  id: number; job: number | null; world: number; chapter: number | null; chapter_title: string | null; book: number | null
  rule: string; category: FindingCategory; severity: Severity; source: 'rules' | 'text' | 'ai'
  confidence: number | null; summary: string; explanation: string; manuscript_quote: string
  position_start: number | null; position_end: number | null; quote_verified: boolean
  decision: Decision; decision_note: string; evidence: Evidence[]; created_at: string
}

export type QuickIssue = {
  rule: string; category: FindingCategory; severity: Severity; summary: string; explanation: string
  quote: string; start: number | null; end: number | null
}
export type QuickCheckResult = { mentions: { character: number; name: string; start: number; end: number }[]; issues: QuickIssue[] }

export type AIStatus = {
  available: boolean; server: boolean; model?: string; model_installed?: boolean; models?: string[]
  error?: string; queue?: { pending: number; running: number }
}

export type SpellIssue = { kind: 'spelling'; word: string; start: number; end: number; message: string }
export type StyleIssue = { kind: 'style'; rule: string; start: number; end: number; text: string; message: string }
export type SpellResult = { spelling: SpellIssue[]; style: StyleIssue[] }

export type SearchResult = {
  type: 'book' | 'page' | 'character' | 'faction' | 'lore' | 'event' | 'chapter'
  id: number; title: string; snippet: string; world?: number; book?: number; category?: string
}

export type PageEntityType = 'character' | 'faction' | 'lore'

export type PageSummary = {
  id: number; title: string; icon: string; page_type: string; parent: number | null; sort_order: number
  aliases: string[]; has_children: boolean; has_cover: boolean
  entity_type: PageEntityType | null; entity_id: number | null; is_public: boolean; updated_at: string
}

export type PropertyKind = 'text' | 'number' | 'date' | 'checkbox' | 'tags' | 'page' | 'pages'
export type DateValue = { label: string; key: number | null }
export type PageProperty = { id: number; label: string; kind: PropertyKind; value: unknown; order: number }

export type PageDetail = PageSummary & {
  content: DocNode; plain_text: string; revision: number; properties: PageProperty[]; updated_by_name: string; created_at: string
  breadcrumbs: { id: number; title: string; icon: string }[]
  children: PageSummary[]
  backlinks: { id: number; title: string; icon: string; page_type: string; origins: ('content' | 'property')[] }[]
  links: { target_ref: number; origin: 'content' | 'property'; broken: boolean; title: string | null }[]
}

export type PageTemplateInfo = {
  key: string; builtin: boolean; id: number | null; name: string; icon: string; page_type: string
  properties: { label: string; kind: PropertyKind }[]; world: number | null
}

/* ---------- co-writing ---------- */

export type Person = { id: number; name: string; has_avatar: boolean; email?: string }
export type Member = Person & { role: Role; joined_at: string }
export type MembersInfo = { my_role: Role; members: Member[] }

export type Invite = {
  id: number; kind: 'email' | 'link'; email: string; role: Role; token: string; created_by_name: string
  created_at: string; expires_at: string | null; max_uses: number | null; uses: number; status: string
}

export type InvitePreview = {
  world: { id: number; name: string }; books: { id: number; title: string }[]; role: Role
  invited_by: Person | null; email: string; problem: string | null; my_role: Role | null; token?: string
}

export type Comment = {
  id: number; chapter: number | null; page: number | null; parent: number | null; author: Person | null
  body: string; quote: string; resolved: boolean; resolved_by_name: string
  can_edit: boolean; can_resolve: boolean; can_delete: boolean; created_at: string; updated_at: string
}

export type PublicSettings = {
  enabled: boolean; token: string | null
  books: { id: number; title: string; is_public: boolean; chapters: { id: number; title: string; is_public: boolean; status: ChapterStatus }[] }[]
  pages: { id: number; title: string; icon: string; parent: number | null; is_public: boolean }[]
}

export type PublicSite = {
  world: { name: string; description: string; genre: string }
  books: { id: number; title: string; description: string; genre: string; accent: string; has_cover: boolean; updated_at: string
    chapters: { id: number; title: string; word_count: number }[] }[]
  pages: { id: number; title: string; icon: string; page_type: string; parent: number | null }[]
}

export type PublicChapter = {
  id: number; title: string; book: { id: number; title: string }; content: DocNode; word_count: number
  prev: number | null; next: number | null
}

export type PublicPage = {
  id: number; title: string; icon: string; page_type: string; aliases: string[]; has_cover: boolean; updated_at: string
  content: DocNode; properties: { label: string; kind: PropertyKind; value: unknown }[]
  children: { id: number; title: string; icon: string }[]
  character: { status: CharacterStatus; birth_label: string; death_label: string; has_portrait: boolean } | null
}
