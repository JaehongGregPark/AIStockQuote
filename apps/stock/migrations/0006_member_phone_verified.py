from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("stock", "0005_dataqualitylog_marketevent_stocknewsitem_pricealert_and_more")]
    operations = [migrations.AddField(model_name="stockmember", name="is_phone_verified", field=models.BooleanField(default=False))]
