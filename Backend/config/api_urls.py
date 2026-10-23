from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.routers import SimpleRouter

from apps.accounts import views as accounts
from apps.analysis import views as analysis
from apps.boards import views as boards
from apps.collab import public
from apps.collab import views as collab
from apps.books import views as books
from apps.language import views as language
from apps.pages import views as pages
from apps.worlds import views as worlds

ID = r"(?P<{}>\d{{1,18}})"

router = SimpleRouter()
router.register("worlds", worlds.WorldViewSet, basename="world")
router.register(rf"worlds/{ID.format('world_pk')}/characters", worlds.CharacterViewSet, basename="character")
router.register(rf"worlds/{ID.format('world_pk')}/factions", worlds.FactionViewSet, basename="faction")
router.register(rf"worlds/{ID.format('world_pk')}/memberships", worlds.MembershipViewSet, basename="membership")
router.register(rf"worlds/{ID.format('world_pk')}/lore", worlds.LoreEntryViewSet, basename="lore")
router.register(rf"worlds/{ID.format('world_pk')}/timeline", worlds.TimelineEventViewSet, basename="event")
router.register(rf"worlds/{ID.format('world_pk')}/dependencies", worlds.DependencyViewSet, basename="dependency")
router.register(rf"worlds/{ID.format('world_pk')}/relationships", worlds.RelationshipViewSet, basename="relationship")
router.register(rf"worlds/{ID.format('world_pk')}/pages", pages.PageViewSet, basename="page")
router.register(rf"worlds/{ID.format('world_pk')}/pages/{ID.format('page_pk')}/properties", pages.PropertyViewSet, basename="page-property")
router.register(rf"worlds/{ID.format('world_pk')}/comments", collab.CommentViewSet, basename="comment")
router.register("books", books.BookViewSet, basename="book")
router.register(rf"books/{ID.format('book_pk')}/chapters", books.ChapterViewSet, basename="chapter")
router.register("boards", boards.BoardViewSet, basename="board")
router.register(rf"boards/{ID.format('board_pk')}/items", boards.BoardItemViewSet, basename="board-item")
router.register(rf"boards/{ID.format('board_pk')}/connections", boards.BoardConnectionViewSet, basename="board-connection")
router.register("analysis/findings", analysis.FindingViewSet, basename="finding")
router.register("analysis", analysis.AnalysisJobViewSet, basename="analysis")
router.register("language/dictionary", language.DictionaryViewSet, basename="dictionary")

auth_urls = [
    path("csrf/", accounts.CsrfView.as_view(), name="auth-csrf"),
    path("register/", accounts.RegisterView.as_view(), name="auth-register"),
    path("login/", accounts.LoginView.as_view(), name="auth-login"),
    path("logout/", accounts.LogoutView.as_view(), name="auth-logout"),
    path("me/", accounts.MeView.as_view(), name="auth-me"),
    path("me/avatar/", accounts.AvatarView.as_view(), name="auth-avatar"),
    path("password/", accounts.PasswordChangeView.as_view(), name="auth-password"),
]

urlpatterns = [
    path("auth/", include(auth_urls)),
    path("settings/", accounts.SettingsView.as_view(), name="settings"),
    path("search/", books.GlobalSearchView.as_view(), name="search"),
    path("page-templates/", pages.TemplateListView.as_view(), name="page-templates"),
    path("page-templates/<int:pk>/", pages.TemplateDeleteView.as_view(), name="page-template-delete"),
    path("books/<int:book_pk>/chapters/<int:chapter_pk>/relevant-pages/", pages.RelevantPagesView.as_view(), name="relevant-pages"),
    path("import/docx/", books.DocxImportView.as_view(), name="import-docx"),
    path("import/docx/preview/", books.DocxPreviewView.as_view(), name="import-docx-preview"),
    path("worlds/<int:world_pk>/search/", worlds.WorldSearchView.as_view(), name="world-search"),
    path("worlds/<int:world_pk>/consistency/", analysis.WorldConsistencyView.as_view(), name="world-consistency"),
    path("worlds/<int:world_pk>/graph-layout/<str:view>/", worlds.GraphLayoutView.as_view(), name="graph-layout"),
    path("worlds/<int:world_pk>/chronology/", analysis.WorldChronologyView.as_view(), name="world-chronology"),
    path("analysis/quick-check/", analysis.QuickCheckView.as_view(), name="quick-check"),
    path("ai/status/", analysis.AIStatusView.as_view(), name="ai-status"),
    path("language/spellcheck/", language.SpellcheckView.as_view(), name="spellcheck"),
    path("language/suggest/", language.SuggestView.as_view(), name="spell-suggest"),
    path("language/status/", language.LanguageStatusView.as_view(), name="language-status"),
    # co-writing: members, invitations, public site
    path("worlds/<int:world_pk>/members/", collab.MembersView.as_view(), name="world-members"),
    path("worlds/<int:world_pk>/members/<int:user_pk>/", collab.MemberDetailView.as_view(), name="world-member"),
    path("worlds/<int:world_pk>/members/<int:user_pk>/avatar/", collab.MemberAvatarView.as_view(), name="world-member-avatar"),
    path("worlds/<int:world_pk>/transfer/", collab.TransferView.as_view(), name="world-transfer"),
    path("worlds/<int:world_pk>/invites/", collab.InvitesView.as_view(), name="world-invites"),
    path("worlds/<int:world_pk>/invites/<int:invite_pk>/", collab.InviteRevokeView.as_view(), name="world-invite"),
    path("worlds/<int:world_pk>/comment-counts/", collab.CommentCountsView.as_view(), name="comment-counts"),
    path("worlds/<int:world_pk>/public/", collab.PublicSettingsView.as_view(), name="world-public"),
    path("invites/mine/", collab.MyInvitesView.as_view(), name="my-invites"),
    path("invites/<str:token>/", collab.InviteByTokenView.as_view(), name="invite"),
    path("invites/<str:token>/accept/", collab.InviteAcceptView.as_view(), name="invite-accept"),
    path("invites/<str:token>/decline/", collab.InviteDeclineView.as_view(), name="invite-decline"),
    path("public/<str:token>/", public.PublicWorldView.as_view(), name="public-world"),
    path("public/<str:token>/chapters/<int:chapter_pk>/", public.PublicChapterView.as_view(), name="public-chapter"),
    path("public/<str:token>/pages/<int:page_pk>/", public.PublicPageView.as_view(), name="public-page"),
    path("public/<str:token>/images/<str:kind>/<int:pk>/", public.PublicImageView.as_view(), name="public-image"),
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
    path("", include(router.urls)),
]
