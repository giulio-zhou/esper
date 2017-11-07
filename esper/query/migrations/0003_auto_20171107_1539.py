# -*- coding: utf-8 -*-
# Generated by Django 1.11 on 2017-11-07 23:39
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('query', '0002_auto_20171103_1035'),
    ]

    operations = [
        migrations.CreateModel(
            name='babycam_Face',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('bbox_x1', models.FloatField()),
                ('bbox_x2', models.FloatField()),
                ('bbox_y1', models.FloatField()),
                ('bbox_y2', models.FloatField()),
                ('bbox_score', models.FloatField()),
            ],
        ),
        migrations.CreateModel(
            name='babycam_FaceFeatures',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('features', models.BinaryField()),
                ('face', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_query_name='facefeatures', to='query.babycam_Face')),
            ],
        ),
        migrations.CreateModel(
            name='babycam_FaceTrack',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='babycam_Frame',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('number', models.IntegerField(db_index=True)),
            ],
        ),
        migrations.CreateModel(
            name='babycam_Labeler',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(db_index=True, max_length=256)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='babycam_Video',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('path', models.CharField(db_index=True, max_length=256)),
                ('num_frames', models.IntegerField()),
                ('fps', models.FloatField()),
                ('width', models.IntegerField()),
                ('height', models.IntegerField()),
                ('session_id', models.IntegerField()),
                ('session_name', models.CharField(max_length=256)),
                ('session_date', models.DateField()),
                ('participant_id', models.IntegerField()),
                ('participant_birthdate', models.DateField()),
                ('participant_gender', models.CharField(max_length=256)),
                ('context_setting', models.CharField(max_length=256)),
                ('context_country', models.CharField(max_length=256)),
                ('context_state', models.CharField(max_length=256)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.AddField(
            model_name='babycam_frame',
            name='video',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_query_name='frame', to='query.babycam_Video'),
        ),
        migrations.AddField(
            model_name='babycam_facefeatures',
            name='labeler',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_query_name='facefeatures', to='query.babycam_Labeler'),
        ),
        migrations.AddField(
            model_name='babycam_face',
            name='frame',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_query_name='face', to='query.babycam_Frame'),
        ),
        migrations.AddField(
            model_name='babycam_face',
            name='labeler',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_query_name='face', to='query.babycam_Labeler'),
        ),
        migrations.AddField(
            model_name='babycam_face',
            name='track',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_query_name='face', to='query.babycam_FaceTrack'),
        ),
        migrations.AlterUniqueTogether(
            name='babycam_frame',
            unique_together=set([('video', 'number')]),
        ),
        migrations.AlterUniqueTogether(
            name='babycam_facefeatures',
            unique_together=set([('labeler', 'face')]),
        ),
        migrations.AlterUniqueTogether(
            name='babycam_face',
            unique_together=set([('track', 'frame', 'labeler')]),
        ),
    ]
