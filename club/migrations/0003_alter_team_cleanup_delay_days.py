from django.db import migrations, models
from django.core.validators import MinValueValidator


class Migration(migrations.Migration):
    dependencies = [("club", "0002_arena")]
    operations = [migrations.AlterField(model_name="team", name="cleanup_delay_days", field=models.PositiveIntegerField(default=30, validators=[MinValueValidator(1)]) )]
