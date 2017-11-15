# -*- coding: utf-8 -*-
# Generated by Django 1.11 on 2017-11-15 20:06
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('query', '0009_trains_labeler'),
    ]

    operations = [
        migrations.CreateModel(
            name='BoundingBox',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('x_min', models.FloatField()),
                ('y_min', models.FloatField()),
                ('x_max', models.FloatField()),
                ('y_max', models.FloatField()),
                ('confidence', models.FloatField()),
            ],
        ),
        migrations.CreateModel(
            name='Category',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=256)),
            ],
        ),
        migrations.CreateModel(
            name='istcvcs_Frame',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('number', models.IntegerField(db_index=True)),
                ('bounding_boxes', models.ManyToManyField(to='query.BoundingBox')),
            ],
        ),
        migrations.CreateModel(
            name='istcvcs_Labeler',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(db_index=True, max_length=256)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='istcvcs_Video',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('path', models.CharField(db_index=True, max_length=256)),
                ('num_frames', models.IntegerField()),
                ('fps', models.FloatField()),
                ('width', models.IntegerField()),
                ('height', models.IntegerField()),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='Label',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('presence', models.CharField(choices=[(b'PRESENT', b'Present'), (b'PARTIAL', b'Partial'), (b'NOT_PRESENT', b'Not Present')], max_length=256)),
                ('category', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='query.Category')),
            ],
        ),
        migrations.AddField(
            model_name='istcvcs_frame',
            name='labels',
            field=models.ManyToManyField(to='query.Label'),
        ),
        migrations.AddField(
            model_name='istcvcs_frame',
            name='video',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_query_name='frame', to='query.istcvcs_Video'),
        ),
        migrations.AddField(
            model_name='boundingbox',
            name='category',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='query.Category'),
        ),
        migrations.AlterUniqueTogether(
            name='istcvcs_frame',
            unique_together=set([('video', 'number')]),
        ),
    ]
