# Generated manually to match apps/stock/models.py (StockMember) -- mirrors the
# style Django's makemigrations would produce (see apps/aura_app/migrations/0002_auramember.py).
# This is the FIRST migration for the stock app (it previously had zero models).

import apps.stock.models
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='StockMember',
            fields=[
                ('id', models.CharField(default=apps.stock.models._new_member_id, editable=False, max_length=40, primary_key=True, serialize=False)),
                ('email', models.EmailField(max_length=254, unique=True)),
                ('name', models.CharField(max_length=80)),
                ('password_hash', models.CharField(max_length=255)),
                ('phone', models.CharField(blank=True, max_length=40)),
                ('postal_code', models.CharField(blank=True, max_length=10)),
                ('road_address', models.CharField(blank=True, max_length=200)),
                ('address_detail', models.CharField(blank=True, max_length=200)),
                ('is_email_verified', models.BooleanField(default=False)),
                ('email_verification_token', models.CharField(blank=True, max_length=64, null=True, unique=True)),
                ('email_verification_expires_at', models.DateTimeField(blank=True, null=True)),
                ('password_reset_token', models.CharField(blank=True, max_length=64, null=True, unique=True)),
                ('password_reset_expires_at', models.DateTimeField(blank=True, null=True)),
                ('privacy_consent_accepted', models.BooleanField(default=False)),
                ('privacy_consent_accepted_at', models.DateTimeField(blank=True, null=True)),
                ('role', models.CharField(default='member', max_length=20)),
                ('memo', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
