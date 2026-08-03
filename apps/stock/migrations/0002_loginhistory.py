# Generated manually to match apps/stock/models.py (LoginHistory addition) --
# mirrors the style Django's makemigrations would produce (see
# apps/aura_app/migrations/0010_loginhistory.py, same pattern applied per app).

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stock', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='LoginHistory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('attempted_email', models.EmailField(max_length=254)),
                ('success', models.BooleanField()),
                ('failure_reason', models.CharField(blank=True, max_length=100)),
                ('ip_address', models.GenericIPAddressField(blank=True, null=True)),
                ('user_agent', models.CharField(blank=True, max_length=500)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('member', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='login_history', to='stock.stockmember')),
            ],
            options={
                'verbose_name': '로그인 기록',
                'verbose_name_plural': '로그인 기록',
                'ordering': ['-created_at'],
            },
        ),
    ]
