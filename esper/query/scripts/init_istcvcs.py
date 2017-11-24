from query.models import Category, Presence, LabelSource

categories = ['person', 'car', 'truck', 'bus', 'train']
category_objects = [Category(name=class_str) for class_str in categories]
Category.objects.bulk_create(category_objects)

presences = ['PRESENT', 'PARTIAL', 'NOT_PRESENT']
presence_objects = [Presence(name=presence_str) for presence_str in presences]
Presence.objects.bulk_create(presence_objects)

label_sources = ['NoScope YOLO', 'Viscloud Labeler']
label_sources_objects = \
    [LabelSource(name=label_source_str) for label_source_str in label_sources]
LabelSource.objects.bulk_create(label_sources_objects)
