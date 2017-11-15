from query.models import Category, Presence

categories = ['person', 'car', 'truck', 'bus', 'train']
category_objects = [Category(name=class_str) for class_str in categories]
Category.objects.bulk_create(category_objects)

presences = ['PRESENT', 'PARTIAL', 'NOT_PRESENT']
presence_objects = [Presence(name=presence_str) for presence_str in presences]
Presence.objects.bulk_create(presence_objects)
