from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ('learning', '0003_lesson_duration_seconds_videosession_videoevent_and_more'),
    ]
    operations = [
        migrations.AlterField(
            model_name='lesson',
            name='slug',
            field=models.SlugField(max_length=120),
        ),
    ]
