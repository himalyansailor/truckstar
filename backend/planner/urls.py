from django.urls import path

from . import views

urlpatterns = [
    path("plan/", views.plan),
    path("heatmap/", views.heatmap),
    path("places/", views.places),
]
