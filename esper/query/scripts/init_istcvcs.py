from query.models import Category, Presence, LabelSource

existing_category_names = list(Category.objects.values_list('name', flat=True))
print(existing_category_names)
categories = ['person', 'car', 'truck', 'bus', 'train']
category_objects = [Category(name=class_str) for class_str in categories \
                        if class_str not in existing_category_names]
Category.objects.bulk_create(category_objects)

existing_presence_names = list(Presence.objects.values_list('name', flat=True))
print(existing_presence_names)
presences = ['PRESENT', 'PARTIAL', 'NOT_PRESENT']
presence_objects = [Presence(name=presence_str) for presence_str in presences \
                        if presence_str not in existing_presence_names]
Presence.objects.bulk_create(presence_objects)

existing_label_source_names = \
    list(LabelSource.objects.values_list('name', flat=True))
print(existing_label_source_names)
label_sources = ['NoScope YOLO', 'Viscloud Labeler', 'Viscloud YOLOv2 416']
label_sources_objects = \
    [LabelSource(name=label_source_str) for label_source_str in label_sources
         if label_source_str not in existing_label_source_names]
LabelSource.objects.bulk_create(label_sources_objects)
