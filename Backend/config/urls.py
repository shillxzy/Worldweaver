from django.contrib import admin
from django.urls import include, path

from apps.common.exceptions import json_404, json_500

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("config.api_urls")),
]

handler404 = json_404
handler500 = json_500
