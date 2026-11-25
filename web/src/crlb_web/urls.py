"""URLs of the validation interface."""

from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path

from crlb_web.validation import views

urlpatterns = [
    path("", views.entries, name="entries"),
    path("entry/<str:part>/<str:number>/", views.entry, name="entry"),
    path("page/<int:document_id>/<int:page_index>.png", views.page_image, name="page"),
    path("review/", views.review, name="review"),
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("admin/", admin.site.urls),
]
