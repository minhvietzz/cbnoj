from django.db import migrations


def create_permission(apps, schema_editor):
    ContentType = apps.get_model('contenttypes', 'ContentType')
    Permission = apps.get_model('auth', 'Permission')
    ct, _ = ContentType.objects.get_or_create(app_label='judge', model='judge')
    Permission.objects.get_or_create(content_type=ct, codename='view_server_status',
                                     defaults={'name': 'Can view server status'})


def remove_permission(apps, schema_editor):
    Permission = apps.get_model('auth', 'Permission')
    Permission.objects.filter(codename='view_server_status', content_type__app_label='judge').delete()


class Migration(migrations.Migration):
    dependencies = [
        ('judge', '0246_question_bank'),
        ('contenttypes', '0002_remove_content_type_name'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [migrations.RunPython(create_permission, remove_permission)]
