from datetime import datetime
from django.db import transaction
from django.db.models import Max
from operator import itemgetter
from query.models import Category, Presence
from query.models import Video, Frame, Label
from query.scripts.read_data import main
import sys
import time

MODE = 'new_presence_labels'

VIDEO_PATH = 'videos/jackson-town-square.mp4'
DATA_DIR = 'labeler/noscope-jackson'
CATEGORY = 'person'

NEW_VIDEO_ARGS = [VIDEO_PATH, 6426648, 30, 601, 400]
NEW_PRESENCE_LABELS_ARGS = [VIDEO_PATH, DATA_DIR, CATEGORY]
UPDATE_PRESENCE_LABELS_ARGS = [VIDEO_PATH, DATA_DIR, CATEGORY]

def make_video_object(path, num_frames, fps, width, height):
    video = Video()
    video.path = path
    video.num_frames = num_frames
    video.fps = fps
    video.width = width
    video.height = height
    date = 20210120
    time = 120000
    dt = datetime.strptime('{} {}'.format(date, time), '%Y%m%d %H%M%S')
    video.time = dt
    return video

def make_frames(video):
    return [Frame(number=i, video=video) for i in range(video.num_frames)]

def batch(iterable, n=1):
    l = len(iterable)
    for ndx in range(0, l, n):
        yield iterable[ndx:min(ndx + n, l)]

def batch_frame_creation(frames):
    batch_size = 1000
    for i, x in enumerate(batch(range(0, len(frames)), batch_size)):
        print "Batch: ", i
        frames_batch = itemgetter(*x)(frames)
        Frame.objects.bulk_create(frames_batch)

def make_presence_labels(video_path, full_labels, category_name):
    present = Presence.objects.filter(name='PRESENT').all()[0]
    not_present = Presence.objects.filter(name='NOT_PRESENT').all()[0]
    partial = Presence.objects.filter(name='PARTIAL').all()[0]
    category = Category.objects.filter(name=category_name).all()[0]
    ordered_frames = \
        Frame.objects.filter(video__path=video_path).order_by('number')
    num_labels = len(full_labels)
    num_frames = ordered_frames.count()
    assert(ordered_frames[0].number == 0)
    assert(ordered_frames.all().aggregate(Max('number'))['number__max'] == num_frames - 1)
    assert(min(full_labels) == 0)
    assert(max(full_labels) == num_labels - 1)
    assert(num_labels <= num_frames)
    new_labels, new_frames = [], []
    for frame_id, current_frame in enumerate(ordered_frames.iterator()):
        # Handle all Frames that I have explicit labels for.
        if frame_id < num_labels:
            our_label = full_labels[frame_id]
            if our_label == 'Event':
                label_object = Label(
                    category=category, presence=present, frame=current_frame)
            elif our_label == 'No Event':
                label_object = Label(
                    category=category, presence=not_present, frame=current_frame)
            elif our_label == 'Unknown':
                label_object = Label(
                    category=category, presence=partial, frame=current_frame)
            else:
                raise Exception()
        # Handle all Frames that I don't have explicit labels for.
        else:
            label_object = Label(
                category=category, presence=not_present, frame=current_frame)
        new_labels.append(label_object)
        new_frames.append(current_frame)
    return new_labels, new_frames

def batch_save_frames(new_frames):
    num_frames = len(new_frames)
    batch_size = 1000
    for i, x in enumerate(batch(range(0, num_frames), batch_size)):
        print "Batch:", i
        new_frames_batch = itemgetter(*x)(new_frames)
        Frame.objects.bulk_create(new_frames_batch)

def batch_save_presence_labels(new_labels, new_frames):
    num_frames = len(new_frames)
    batch_size = 1000
    for i, x in enumerate(batch(range(0, num_frames), batch_size)):
        print "Batch:", i
        new_labels_batch = itemgetter(*x)(new_labels)
        new_frames_batch = itemgetter(*x)(new_frames)
        Label.objects.bulk_create(new_labels_batch)

def batch_update_presence_labels(new_labels, new_frames, category_name):
    num_frames = len(new_frames)
    batch_size = 1000
    category = Category.objects.filter(name=category_name).all()[0]
    for i, x in enumerate(batch(range(0, num_frames), batch_size)):
        print "Batch:", i
        new_labels_batch = itemgetter(*x)(new_labels)
        new_frames_batch = itemgetter(*x)(new_frames)
        with transaction.atomic():
            for new_label, new_frame in zip(new_labels_batch, new_frames_batch):
                # NOTE: assume that each frame only has one category label to update.
                old_label = new_frame.label_set.filter(category=category)[0]
                old_label.presence = new_label.presence
                old_label.save()

mode = MODE
if mode == 'new_video':
    path, num_frames, fps, width, height = NEW_VIDEO_ARGS
    video = make_video_object(path, num_frames, fps, width, height)
    video.save()
    frames = make_frames(video)
    batch_save_frames(frames)
elif mode == 'new_presence_labels':
    video_path, data_dir, category_name = NEW_PRESENCE_LABELS_ARGS
    data_points, full_labels = main(data_dir)
    new_labels, new_frames = \
        make_presence_labels(video_path, full_labels, category_name)
    batch_save_presence_labels(new_labels, new_frames)
elif mode == 'update_presence_labels':
    video_path, data_dir, category_name = UPDATE_PRESENCE_LABELS_ARGS
    data_points, full_labels = main(data_dir)
    new_labels, new_frames = \
        make_presence_labels(video_path, full_labels, category_name)
    batch_update_presence_labels(new_labels, new_frames, category_name)
else:
    raise Exception("Cannot find matching mode for mode %s" % mode)
