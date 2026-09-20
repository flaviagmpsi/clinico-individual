from django.urls import path

from assinaturas import views

app_name = "assinaturas"

urlpatterns = [
    path("", views.Plano.as_view(), name="plano"),
    path("pagamento/", views.Pagamento.as_view(), name="pagamento"),
]
