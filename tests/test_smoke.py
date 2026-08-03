import pytest
from django.urls import reverse

@pytest.mark.django_db
def test_stock_home_loads(client):
    assert client.get("/stock/").status_code == 200

def test_root_redirects(client):
    response = client.get("/")
    assert response.status_code == 302
    assert response.url == "/stock/"

def test_core_routes_resolve():
    assert reverse("stock_home") == "/stock/"
    assert reverse("stock_market_quotes", args=["kospi"]) == "/stock/api/markets/kospi/quotes"

@pytest.mark.django_db
def test_admin_uses_standalone_staff(client, django_user_model):
    user = django_user_model.objects.create_user("admin", is_staff=True)
    client.force_login(user)
    assert client.get("/stock/stock-admin/").status_code == 200
