from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [('club', '0012_cancelled_problem_status')]
    operations = [migrations.AddField(model_name='parsersettings', name='api_protocol', field=models.CharField('调用协议', max_length=16, default='chat', choices=[('chat','Chat Completions'),('responses','Responses 联网')]))]
