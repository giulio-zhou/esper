from django.db import models
import base_models as base
import sys

with base.Dataset('tvnews'):

    class Video(base.Video):
        channel = base.CharField()
        show = base.CharField()
        time = models.DateTimeField()

    class Frame(base.Frame):
        talking_heads = models.BooleanField(default=False)

    class Labeler(base.Labeler):
        pass

    class Identity(base.Model):
        name = base.CharField()

    class Gender(base.Model):
        name = base.CharField()

    class Face(base.Concept):
        gender = models.ForeignKey(Gender, null=True, blank=True)
        identity = models.ForeignKey(Identity, null=True, blank=True)


with base.Dataset('krishna'):

    class Video(base.Video):
        pass

    class Frame(base.Frame):
        pass

    class Labeler(base.Labeler):
        pass

    class Face(base.Concept):
        pass

    class Person(base.Concept):
        pass

with base.Dataset('trains'):

    class Video(base.Video):
        pass

    class Frame(base.Frame):
        pass

    class Labeler(base.Labeler):
        pass

with base.Dataset('istcvcs'):

    class Category(models.Model):
        name = base.CharField()

    class Presence(models.Model):
        name = base.CharField()

    class Label(models.Model):
        category = models.ForeignKey(Category)
        presence = models.ForeignKey(Presence)

    class BoundingBox(models.Model):
        category = models.ForeignKey(Category)
        x_min = models.FloatField()
        y_min = models.FloatField()
        x_max = models.FloatField()
        y_max = models.FloatField()
        confidence = models.FloatField()

    class Video(base.Video):
        pass

    class Frame(base.Frame):
        labels = models.ManyToManyField(Label)
        bounding_boxes = models.ManyToManyField(BoundingBox)

    class Labeler(base.Labeler):
        pass
