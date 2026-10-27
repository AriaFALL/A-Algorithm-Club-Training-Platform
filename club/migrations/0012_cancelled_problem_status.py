from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [('club', '0011_submission_record_date')]
    operations = [migrations.AlterField(model_name='problem', name='status', field=models.CharField('解析状态', max_length=16, default='pending', choices=[('pending','待解析'),('running','解析中'),('success','成功'),('failed','待处理'),('manual','人工补填'),('cancelled','任务已移除')]))]
