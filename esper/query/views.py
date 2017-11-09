from __future__ import print_function
from django.shortcuts import render
from django.http import JsonResponse, HttpResponse
from django.forms.models import model_to_dict
from django.db.models.query import QuerySet
import django.db.models as models
from base_models import ModelDelegator
from timeit import default_timer as now
import sys
from google.protobuf.json_format import MessageToJson
import json
from collections import defaultdict
from scannerpy import Config, Database, Job, DeviceType
from django.db import connection
import logging
import time
from django.db.models import Min, Max, Q, F, Count, OuterRef, Subquery
from django.db.models.functions import Cast
import os
from concurrent.futures import ThreadPoolExecutor
from django.views.decorators.csrf import csrf_exempt
from sets import Set
import tempfile
import subprocess as sp
import shlex
import math
import itertools
import numpy as np
from operator import itemgetter
import traceback

ESPER_ENV = os.environ.get('ESPER_ENV')
BUCKET = os.environ.get('BUCKET')
DATASET = os.environ.get('DATASET')  # TODO(wcrichto): move from config to runtime
DATA_PATH = os.environ.get('DATA_PATH')
FALLBACK_ENABLED = False
logger = logging.getLogger(__name__)

from query.base_models import ModelDelegator
model_delegator = ModelDelegator(DATASET)
Video, Frame = model_delegator.Video, model_delegator.Frame

# TODO(wcrichto): find a better way to do this
Config()
from scanner.types_pb2 import BoundingBox

DIFF_BBOX_THRESHOLD = 0.35
# 24 frames/sec - so this requires more than a sec overlap
FRAME_OVERLAP_THRESHOLD = 25


def _print(*args):
    print(*args)
    sys.stdout.flush()


def index(request):
    schemas = []
    for name, ds in ModelDelegator().datasets().iteritems():
        schema = []

        def get_fields(cls):
            fields = cls._meta.get_fields()
            return [f.name for f in fields if isinstance(f, models.Field)]

        #for cls in ['Video', 'Frame', 'Labeler'] + sum([[c, c + 'Instance', c + 'Features']
        for cls in ['Video', 'Frame'] + sum([[c, c + 'Instance', c + 'Features']
                                                        for c in ds.concepts], []) + ds.other:
            schema.append([cls, get_fields(getattr(ds, cls))])
        schemas.append([name, schema])

    return render(request, 'index.html', {'schemas': json.dumps(schemas)})


def extract(frames):
    with Database() as db:
        frame = db.table(frames[0].video.path).as_op().gather(
            [frame.number for frame in frames], task_size=1000)
        resized = db.ops.Resize(frame=frame, width=640, preserve_aspect=True, device=DeviceType.GPU)
        compressed = db.ops.ImageEncoder(frame=resized)
        job = Job(columns=[compressed], name='_ignore')

        start = now()
        output = db.run(job, force=True)
        _print('Extract: {:.3f}'.format(now() - start))

        start = now()
        jpgs = [(jpg[0], frame) for (_, jpg), frame in zip(output.load(['img']), frames)]
        _print('Loaded: {:.3f}'.format(now() - start))

        if ESPER_ENV == 'google':
            temp_dir = tempfile.mkdtemp()

            def write_jpg((jpg, frame)):
                with open('{}/frame_{}.jpg'.format(temp_dir, frame.id), 'w') as f:
                    f.write(jpg)

            start = now()
            with ThreadPoolExecutor(max_workers=64) as executor:
                list(executor.map(write_jpg, jpgs))
            sp.check_call(
                shlex.split('gsutil -m mv "{}/*" gs://{}/{}/thumbnails/{}'.format(
                    temp_dir, BUCKET, DATA_PATH, DATASET)))
            _print('Write: {:.3f}'.format(now() - start))

        elif ESPER_ENV == 'local':

            def write_jpg((jpg, frame)):
                with open('assets/thumbnails/{}/frame_{}.jpg'.format(DATASET, frame.id), 'w') as f:
                    f.write(jpg)

            start = now()
            with ThreadPoolExecutor(max_workers=64) as executor:
                list(executor.map(write_jpg, jpgs))
            _print('Write: {:.3f}'.format(now() - start))
        return jpg


@csrf_exempt
def batch_fallback(request):
    frames = [int(s) for s in request.POST.get('frames').split(',')]
    frames = Frame.objects.filter(id__in=frames)
    extract(frames)
    return JsonResponse({'success': True})


def fallback(request):
    if not FALLBACK_ENABLED:
        return HttpResponse(status=501)

    request_path = request.get_full_path().split('/')[3:]
    filename, _ = os.path.splitext(request_path[-1])
    [ty, id] = filename.split('_')
    assert ty == 'frame'

    frame = Frame.objects.get(id=id)
    jpg = extract([frame])

    return HttpResponse(jpg, content_type="image/jpeg")


def videos(request):
    id = request.GET.get('id', None)
    if id is None:
        videos = Video.objects.all()
    else:
        videos = [Video.objects.filter(id=id).get()]
    return JsonResponse({
        'videos':
        [dict(model_to_dict(v).items() + {'stride': v.get_stride()}.items()) for v in videos]
    })


def frames(request):
    video_id = request.GET.get('video_id', None)
    handlabeled = request.GET.get('video_id', False)
    video = Video.objects.filter(id=video_id).get()
    labelset = video.handlabeled_labelset() if handlabeled else video.detected_labelset()
    resp = JsonResponse({
        'frames':[dict(model_to_dict(f, exclude='labels').items() + {'labels' : f.label_ids()}.items()) \
                for f in Frame.objects.filter(labelset=labelset).prefetch_related('labels').all()] ,
        'labels':[model_to_dict(s) for s in FrameLabel.objects.all()]
    })
    return resp


def frame_and_faces(request):
    video_id = request.GET.get('video_id', None)
    video = Video.objects.filter(id=video_id).prefetch_related('labelset_set').get()
    labelsets = video.labelset_set.all()
    frame_and_face_dict = {}
    ret_dict = {}
    for ls in labelsets:
        frames = Frame.objects.filter(labelset=ls).prefetch_related(
            'faces', 'labels').order_by('number').all()
        ls_dict = {}
        for frame in frames:
            frame_dict = {}
            frame_dict['labels'] = frame.label_ids()
            faces = frame.faces.all()
            face_list = []
            for face in faces:
                bbox = _inst_to_bbox_dict('', face)
                face_json = model_to_dict(face)
                del face_json['features']
                face_json['bbox'] = bbox
                face_list.append(face_json)
            frame_dict['faces'] = face_list
            ls_dict[frame.number] = frame_dict
        frame_and_face_dict[2 if ls.name == 'handlabeled' else 1] = ls_dict
    ret_dict['frames'] = frame_and_face_dict
    frame_labels = FrameLabel.objects.all()
    label_dict = {}
    for label in frame_labels:
        label_dict[label.id] = label.name
    ret_dict['labels'] = label_dict
    return JsonResponse(ret_dict)


def faces(request):
    video_id = request.GET.get('video_id', None)
    if video_id is None:
        return JsonResponse({})  # TODO
    video = Video.objects.filter(id=video_id).get()
    labelsets = LabelSet.objects.filter(video=video)
    all_bboxes = {}
    for labelset in labelsets:
        bboxes = defaultdict(list)
        faces = Face.objects.filter(frame__labelset=labelset).select_related('frame').all()
        for face in faces:
            bbox = _inst_to_bbox('', face)
            face_json = model_to_dict(face)
            del face_json['features']
            face_json['bbox'] = bbox
            bboxes[face.frame.number].append(face_json)
        # 1 is Autolabeled 2 is handlabled ugly but works until
        # we use something more than a string in the model
        set_id = 1 if labelset.name == 'detected' else 2
        all_bboxes[set_id] = bboxes
    return JsonResponse({'faces': all_bboxes})


def identities(request):
    # FIXME: Should we be sending faces for each identity too?
    # FIXME: How do I see output of this when calling from js?
    identities = Identity.objects.all()
    return JsonResponse({'ids': [model_to_dict(id) for id in identities]})


def handlabeled(request):
    params = json.loads(request.body)
    video = Video.objects.filter(id=params['video']).get()
    labelset = video.handlabeled_labelset()
    frame_nums = map(int, params['frames'].keys())

    min_frame = min(frame_nums)
    max_frame = max(frame_nums)
    #old frames, create new_frames
    old_frames = Frame.objects.filter(
        labelset=labelset, number__lte=max_frame, number__gte=min_frame).all()
    labelsModel = Frame.labels.through
    if len(old_frames) > 0:
        Face.objects.filter(frame__in=old_frames).delete()
        labelsModel.objects.filter(frame__in=old_frames).delete()

    old_frame_nums = [old_frame.number for old_frame in old_frames]
    missing_frame_nums = [num for num in frame_nums if num not in old_frame_nums]
    new_frames = [Frame(labelset=labelset, number=num) for num in missing_frame_nums]
    Frame.objects.bulk_create(new_frames)
    tracks = defaultdict(list)
    for frame_num, frames in params['frames'].iteritems():
        for face_params in frames['faces']:
            track_id = face_params['track']
            if track_id is not None:
                tracks[track_id].append(frame_num)

    id_to_track = {}
    all_frames = Frame.objects.filter(
        labelset=labelset, number__lte=max_frame, number__gte=min_frame).all()
    curr_video_tracks = Track.objects.filter(video=video).all()
    for track in curr_video_tracks:
        id_to_track[track.id] = track
    for track_id, frames in tracks.iteritems():
        if track_id < 0:
            track = Track(video=video)
            track.save()
            id_to_track[track_id] = track

    new_faces = []
    new_labels = []
    for frame in all_frames:
        for face_params in params['frames'][str(frame.number)]['faces']:
            face_params['bbox_x1'] = face_params['bbox']['x1']
            face_params['bbox_y1'] = face_params['bbox']['y1']
            face_params['bbox_x2'] = face_params['bbox']['x2']
            face_params['bbox_y2'] = face_params['bbox']['y2']
            track_id = face_params['track']
            if track_id is not None:
                face_params['track'] = id_to_track[track_id]
            face = Face(**face_params)
            face.frame = frame
            new_faces.append(face)
        for label_id in params['frames'][str(frame.number)]['labels']:
            new_labels.append(labelsModel(frame=frame, framelabel_id=int(label_id)))

    Face.objects.bulk_create(new_faces)
    labelsModel.objects.bulk_create(new_labels)

    return JsonResponse({'success': True})


def _inst_to_bbox_dict(prefix, inst):
    if prefix != '':
        prefix = prefix + "__"
    return {
        'x1': inst[prefix + 'bbox_x1'],
        'x2': inst[prefix + 'bbox_x2'],
        'y1': inst[prefix + 'bbox_y1'],
        'y2': inst[prefix + 'bbox_y2'],
        'score': inst[prefix + 'bbox_score']
    }


def _get_bbox_vals(prefix):
    if prefix != '':
        prefix = prefix + "__"
    return [
        prefix + 'bbox_x1', prefix + 'bbox_x2', prefix + 'bbox_y1', prefix + 'bbox_y2',
        prefix + 'bbox_score'
    ]


def _overlap(a, b):
    '''
    @a, b: are ranges with start/end as a[0], a[1]
    '''
    return max(0, min(a[1], b[1]) - max(a[0], b[0]))


def _get_face_min_frames(labeler='tinyfaces'):
    '''
    @labeler: str, name of labeler.
    There can be multiple Face concepts refering to the same face track - so select the ones from a
    particular labeler.
    @ret: dict, with keys id, min_frame, max_frame.
    '''
    # TODO: labeler seems to be a wasted db call (?) -> could get rid of it by
    # converting return value to dict and just adding labeler manually.
    return Face.objects.filter(labeler__name=labeler) \
    .values('id').annotate(min_frame=models.Min('faceinstance__frame__number'),
        max_frame=models.Max('faceinstance__frame__number'))


def _get_face_query(min_frame_numbers):
    '''
    @min_frame_numebers:
    '''
    # TODO: can generalize this more by taking in args for each of the values, and labeler etc. But
    # for now, don't have a use case for that. Maybe we can also use str formating to construct
    # these queries / and then eval them?
    return [
        Face.objects.filter(id=f['id'], faceinstance__frame__number=f['min_frame']).values(
            *(['id', 'faceinstance__frame__id', 'faceinstance__frame__video__id', 'labeler__name'] +
              _get_bbox_vals('faceinstance'))).get() for f in min_frame_numbers
        if f['min_frame'] is not None
    ]


def _get_face_clips(results):
    '''
    @results: zipped value having results, min_frame_numbers (as returned from
    _get_face_query, and _get_face_min_frames).
    @ret: dict, with keys:
        -
        - color: What color the bounding box around it should be. Essentially mapping each labeler
          to a color.
    '''
    # FIXME(pari): can probably save some sql calls - like for getting frame__video__id, or
    # labeler_name, if we process it one video at a time? Not sure if its worth saving them though.
    clips = defaultdict(list)
    for result, f in results:
        clips[result['faceinstance__frame__video__id']].append({
            'concept':
            result['id'],
            'frame':
            result['faceinstance__frame__id'],
            'start':
            f['min_frame'],
            'end':
            f['max_frame'],
            'bboxes': [_inst_to_bbox_dict('faceinstance')],
            'color':
            COLORS[hash(result['labeler__name']) % len(COLORS)]
        })

    # sort these from frame numbers. This is especially useful when diffing the output.
    for k in clips:
        clips[k].sort(key=lambda x: x['start'])

    return dict(clips)


def _find_frame_overlaps(cur_labeler, frame, labelers):
    '''
    '''
    overlaps = []
    for k, v in labelers.iteritems():
        if k == cur_labeler:
            continue
        for (qs, cur_frame) in v:
            # FIXME: if assuming v is sorted according to min_frames, then we can do this.
            # if cur_frame['min_frame'] > frame['max_frame']:
            # # skip the rest of this key.
            # break
            a = (frame['min_frame'], frame['max_frame'])
            b = (cur_frame['min_frame'], cur_frame['max_frame'])
            if _overlap(a, b) > FRAME_OVERLAP_THRESHOLD:
                overlaps.append((qs, cur_frame))

    return overlaps


def _get_face_label_mismatches(labelers):
    '''
    @labelers: dict, with keys as name of labels, and values as zip(qs, min_frame_numbers)
    TODO: can definitely optimize these loops further.
    '''
    # TODO: can keep track of overlaps to skip over some of the faces - especially in 2nd/3rd loop.
    mistakes = []
    for k, v in labelers.iteritems():
        # loop over each track in v.
        for (qs, min_frames) in v:
            bbox = _inst_to_bbox_dict('faceinstance', qs)
            # find all possible frame overlaps between this face and others.
            overlaps = _find_frame_overlaps(k, min_frames, labelers)
            # check if any of these overlaps have bbox's within an acceptable threshold. If they
            # don't then it is a mistake.
            mistake = True
            for (o, _) in overlaps:
                if _bbox_dist(bbox, _inst_to_bbox_dict('faceinstance', o)) < DIFF_BBOX_THRESHOLD:
                    # within a threshold - so the labelers agree on this.
                    mistake = False
                    break

            # TODO: When we find a mistake, not sure if we should also add frames from overlaps
            # For now, just ignore them as there could be too many of those etc - and as long as we
            # loop over each labeler keys, then eventually those would get added.
            if mistake:
                mistakes.append((qs, min_frames))

    return mistakes


def _overlap(a, b):
    '''
    @a, b: are ranges with start/end as a[0], a[1]
    '''
    return max(0, min(a[1], b[1]) - max(a[0], b[0]))


def _bbox_dist(bbox1, bbox2):
    return math.sqrt((bbox2['x1'] - bbox1['x1'])**2 + (bbox2['x2'] - bbox1['x2'])**2 + (bbox2['y1'] - bbox1['y1'])**2 \
                     + (bbox2['y2'] - bbox1['y2'])**2)


def _get_face_min_frames(labeler='tinyfaces'):
    '''
    @labeler: str, name of labeler.
    There can be multiple Face concepts refering to the same face track - so select the ones from a
    particular labeler.
    @ret: dict, with keys id, min_frame, max_frame.
    '''
    # TODO: labeler seems to be a wasted db call (?) -> could get rid of it by
    # converting return value to dict and just adding labeler manually.
    return Face.objects.filter(faceinstance__labeler__name=labeler) \
                       .values('id').annotate(min_frame=Min('faceinstance__frame__number'),
                                              max_frame=Max('faceinstance__frame__number'))


def _get_face_query(min_frame_numbers):
    '''
    @min_frame_numebers:
    '''
    # TODO: can generalize this more by taking in args for each of the values, and labeler etc. But
    # for now, don't have a use case for that. Maybe we can also use str formating to construct
    # these queries / and then eval them?
    return [
        Face.objects.filter(id=f['id'], faceinstance__frame__number=f['min_frame']).values(
            *([
                'id', 'faceinstance__frame__id', 'faceinstance__frame__video__id',
                'faceinstance__labeler__name'
            ] + _get_bbox_vals('faceinstance'))).get() for f in min_frame_numbers
        if f['min_frame'] is not None
    ]


def get_color(s):
    return COLORS[hash(s) % len(COLORS)]


def _get_face_clips(results):
    '''
    @results: zipped value having results, min_frame_numbers (as returned from
    _get_face_query, and _get_face_min_frames).
    @ret: dict, with keys:
        -
        - color: What color the bounding box around it should be. Essentially mapping each labeler
          to a color.
    '''
    # FIXME(pari): can probably save some sql calls - like for getting frame__video__id, or
    # labeler_name, if we process it one video at a time? Not sure if its worth saving them though.
    clips = defaultdict(list)
    for result, f in results:
        clips[result['faceinstance__frame__video__id']].append({
            'video_id': result['faceinstance__frame__video__id'],
            'concept': result['id'],
            'frame': result['faceinstance__frame__id'],
            'start': f['min_frame'],
            'end': f['max_frame'],
            'bboxes': [_inst_to_bbox_dict('faceinstance', result)],
            'color': get_color(result['faceinstance__labeler__name']),
        })  # yapf: disable

    # sort these from frame numbers. This is especially useful when diffing the output.
    for k in clips:
        clips[k].sort(key=lambda x: x['start'])

    return dict(clips)


def _find_frame_overlaps(cur_labeler, frame, labelers):
    '''
    '''
    overlaps = []
    for k, v in labelers.iteritems():
        if k == cur_labeler:
            continue
        for (qs, cur_frame) in v:
            # FIXME: if assuming v is sorted according to min_frames, then we can do this.
            # if cur_frame['min_frame'] > frame['max_frame']:
            # # skip the rest of this key.
            # break
            a = (frame['min_frame'], frame['max_frame'])
            b = (cur_frame['min_frame'], cur_frame['max_frame'])
            if _overlap(a, b) > FRAME_OVERLAP_THRESHOLD:
                overlaps.append((qs, cur_frame))

    return overlaps


def _get_face_label_mismatches(labelers):
    '''
    @labelers: dict, with keys as name of labels, and values as zip(qs, min_frame_numbers)
    TODO: can definitely optimize these loops further.
    '''
    # TODO: can keep track of overlaps to skip over some of the faces - especially in 2nd/3rd loop.
    mistakes = []
    for k, v in labelers.iteritems():
        # loop over each track in v.
        for (qs, min_frames) in v:
            bbox = _inst_to_bbox_dict('faceinstance', qs)
            # find all possible frame overlaps between this face and others.
            overlaps = _find_frame_overlaps(k, min_frames, labelers)
            # check if any of these overlaps have bbox's within an acceptable threshold. If they
            # don't then it is a mistake.
            mistake = True
            for (o, _) in overlaps:
                if _bbox_dist(bbox, _inst_to_bbox_dict('faceinstance', o)) < DIFF_BBOX_THRESHOLD:
                    # within a threshold - so the labelers agree on this.
                    mistake = False
                    break

            # TODO: When we find a mistake, not sure if we should also add frames from overlaps
            # For now, just ignore them as there could be too many of those etc - and as long as we
            # loop over each labeler keys, then eventually those would get added.
            if mistake:
                mistakes.append((qs, min_frames))

    return mistakes


def bboxes_to_json(l):
    r = []
    for b in l:
        obj = _inst_to_bbox_dict('', b)
        obj['labeler'] = b['labeler']
        obj['id'] = b['id']
        r.append(obj)
    return r


def search(request):
    concept = request.GET.get('concept')
    # TODO(wcrichto): Unify video and face cases?
    # TODO(wcrichto): figure out stupid fucking groupwise aggregation issue. Right now we're
    # an individual query for every concept, which is a Bad Idea.

    if concept == 'video':
        min_frame_numbers = list(
            Video.objects.values('id').annotate(
                min_frame=Min('frame__number'), max_frame=Max('frame__number')).order_by('id')[:10])
        qs = [
            Video.objects.filter(id=f['id']).filter(frame__number=f['min_frame']).distinct().values(
                'id', 'path', 'frame__id').get() for f in min_frame_numbers
        ]
        video_keys = [res['id'] for res in qs]
        clips = defaultdict(list)
        for result, f in zip(qs, min_frame_numbers):
            clips[result['path']].append({
                'video_id': result['id'],
                'frame': result['frame__id'],
                'bboxes': [],
                'start': f['min_frame'],
                'end': f['max_frame'],
                'colors': ['red']
            })
        clips = dict(clips)

    elif concept == 'face':

        # min_frame_numbers = _get_face_min_frames(labeler='mtcnn')[:100:5]
        # qs = _get_face_query(min_frame_numbers)

        # clips = defaultdict(list)
        # for face, numbers in zip(qs, min_frame_numbers):
        #     frames = FaceInstance.objects.filter(
        #         concept__id=face['id']).values('frame__number').order_by('frame__number')
        #     frames = [t['frame__number'] for t in frames]
        #     dists = [frames[i + 1] - frames[i] for i in range(len(frames) - 1)]
        #     if np.count_nonzero(dists - np.median(dists)) > 0:
        #         clips[face['faceinstance__frame__video__id']].append({
        #             'video_id': face['faceinstance__frame__video__id'],
        #             'concept': face['id'],
        #             'frame': face['faceinstance__frame__id'],
        #             'start': numbers['min_frame'],
        #             'end': numbers['max_frame'],
        #             'bboxes': bboxes_to_json([{'bbox': face['faceinstance__bbox'],
        #                                        'labeler__name': face['faceinstance__labeler__name']}])
        #         })  # yapf: disable

        # # sort these from frame numbers. This is especially useful when diffing the output.
        # for k in clips:
        #     clips[k].sort(key=lambda x: x['start'])
        # video_keys = set(clips.keys())

        # need to specify labeler, otherwise this list would also include Faces from other labelers.
        min_frame_numbers = _get_face_min_frames(labeler='mtcnn')[:100:5]
        qs = _get_face_query(min_frame_numbers)
        clips = _get_face_clips(zip(qs, min_frame_numbers))
        video_keys = set(clips.keys())

        # insts = FaceInstance.objects.all().order_by('frame__video__id', 'frame__number').values(
        #     'id', 'frame__id', 'frame__video__id', 'frame__video__path', 'bbox', 'labeler__name')
        # videos = defaultdict(lambda: defaultdict(list))
        # video_keys = Set()
        # for inst in insts[:100]:
        #     videos[inst['frame__video__path']][inst['frame__id']].append(inst)
        #     #'bbox': inst['bbox'], inst['labeler__name'], inst['frame__video__id']))
        #     video_keys.add(inst['frame__video__id'])
        # clips = defaultdict(list)
        # for video, frames in videos.iteritems():
        #     frame_keys = sorted(frames.keys())
        #     for frame in frame_keys:
        #         clips[video].append({
        #             'video_id': frames[frame][0]['frame__video__id'],
        #             'frame': frame,
        #             'bboxes': bboxes_to_json(frames[frame])
        #         })

    # Mismatched labels.
    elif concept == 'query':
        filters = json.loads(request.GET.get('filters'))
        orderby = json.loads(request.GET.get('orderby'))
        querytype = request.GET.get('querytype')
        annotate_dict = {}
        queryset = None
        values = []
        distto_fields = Set()
        fieldstrings = [filt[0] for filt in filters] + orderby

        for field in fieldstrings:
            idx = field.find('distto_')
            if idx > 0:
                distto_fields.add(int(field[idx+7:]))
        if len(distto_fields) > 0:
            FaceFeatures.dropTempFeatureModel()
            FaceFeatures.getTempFeatureModel(distto_fields)
        if querytype == 'faceinstance':
            queryset = FaceInstance
            annotate_dict['bbox_width'] = F('bbox_x2')-F('bbox_x1')
            annotate_dict['bbox_height'] = F('bbox_y2')-F('bbox_y1')
            values = ['id', 'frame__id', 'frame__number', 'frame__video__id', 'labeler__name', 'facefeatures__features', 'frame__video__path']+_get_bbox_vals('')
        elif querytype == 'face':
            queryset = Face
            values = ['id', 'faceinstance__frame__video__id', 'faceinstance__min_frame', 'faceinstance__max_frame']
            annotate_dict['faceinstance__min_frame'] = Min('faceinstance__frame__number')
            annotate_dict['faceinstance__max_frame'] = Max('faceinstance__frame__number')
            # annotate_dict['faceinstance__bbox_width'] = F('faceinstance__bbox_x2')-F('faceinstance__bbox_x1')
            # annotate_dict['faceinstance__bbox_height'] = F('faceinstance__bbox_y2')-F('faceinstance__bbox_y1')
        elif querytype == 'video':
            queryset = Video
        elif querytype == 'frame':
            queryset = Frame
            annotate_dict['faceinstance__bbox_width'] = F('faceinstance__bbox_x2')-F('faceinstance__bbox_x1')
            annotate_dict['faceinstance__bbox_height'] = F('faceinstance__bbox_y2')-F('faceinstance__bbox_y1')
            annotate_dict['faceinstance_count'] = Count('faceinstance')
            values = ['video__path', 'video__id', 'id', 'faceinstance__labeler__name', 'faceinstance__id', 'number']+_get_bbox_vals('faceinstance')

        Qargs = Q()
        aggQargs = {}
        feature_filters = []
        other_filters = []
        count_fields = []
        for filt in filters:
            aggregate_field = False
            field = filt[0]
            orig_field = field
            if field[:6] == 'count(':
                aggregate_field = True
                count_field_name = field[6:field.rfind(')')]
                orig_field = count_field_name
                count_fields.append(count_field_name)
                field = count_field_name+'_count'
            op = filt[1]
            negate = False
            if op == 'eq':
                pass
            elif op == 'neq':
                negate = True
            elif op == 'gt':
                field = field + '__gt'
            elif op == 'gte':
                field = field + '__gte'
            elif op == 'lt':
                field = field+'__lt'
            elif op == 'lte':
                field = field + '__lte'
            elif op == 'like':
                field = field + '__contains'
            elif op == 'nlike':
                field = field + '__contains'
                negate = True
            else:
                continue
            currQ = Q(**{field: filt[2]})
            if negate:
                currQ = ~currQ
            if aggregate_field:
                aggQargs[orig_field] =currQ
            else:
                Qargs = Qargs & currQ

        orderby_with_minus = [t for t in orderby]
        orderby = [t.strip('-') for t in orderby]
        for val in orderby:
            if val not in values:
                values.append(val.strip('-'))
        annotate_vals_map = {}

        filteredby = queryset.objects.annotate()

        if querytype == 'frame':
            filteredby = queryset.objects.annotate(numbermod=F("number")%240).filter(numbermod=0)

        _print(Qargs, aggQargs)
        for field in count_fields:
            filteredby = queryset.objects.filter(faceinstance__labeler__name='mtcnn').annotate(**{field+"_count": Count(field)}).filter(aggQargs[field] & Q(**{'id__in':filteredby}))

        insts = queryset.objects.annotate(**annotate_dict).filter(Qargs & Q(**{'id__in':filteredby})).order_by(*orderby_with_minus).values(*values)
        _print(insts.query)

        video_keys = Set()

        clips = defaultdict(list)
        if querytype == 'faceinstance':
            for inst in insts[:200]:
                video_keys.add(inst['frame__video__id'])
                bbox = _inst_to_bbox_dict('', inst)
                bbox['labeler'] = inst['labeler__name']
                bbox['id'] = inst['id']
                bboxes = [bbox]
                clips[inst[orderby[0]] if len(orderby)> 0 and type(inst[orderby[0]]) in [str, unicode] else ''].append({
                    'frame': inst['frame__id'],
                    'video_id': inst['frame__video__id'],
                    'bboxes': bboxes,
                    'start': inst['frame__number']
                })
        elif querytype == 'face':
            for inst in insts[:200]:
                if inst['faceinstance__frame__video__id'] is None:
                    continue
                video_keys.add(inst['faceinstance__frame__video__id'])
                #bbox = _inst_to_bbox_dict('faceinstance', inst)
                faceinst = FaceInstance.objects.filter(face_id=inst['id'], frame__number=inst['faceinstance__min_frame'])[0]
                bbox = _inst_to_bbox_dict('', model_to_dict(faceinst))
                bbox['id'] = faceinst.id
                clips[inst[orderby[0]] if len(orderby) > 0 and type(inst[orderby[0]]) in [str, unicode] else ''].append({
                    'frame': Frame.objects.get(
                        video__id=inst['faceinstance__frame__video__id'],
                        number=inst['faceinstance__min_frame']).id,
                    'video_id': inst['faceinstance__frame__video__id'],

                    'bboxes': [bbox],
                    'start': inst['faceinstance__min_frame'],
                    'end': inst['faceinstance__max_frame'],
                })
        elif querytype == 'frame':
            frameset = Set()
            bboxes = defaultdict(list)
            for inst in insts:
                if inst['faceinstance__bbox_x1'] is None:
                    continue
                bbox = _inst_to_bbox_dict('faceinstance', inst)
                bbox['labeler'] = inst['faceinstance__labeler__name']
                bbox['id'] = inst['faceinstance__id']
                bboxes[inst['id']].append(bbox)

            for inst in insts[:200]:
                video_keys.add(inst['video__id'])
                if inst['id'] in frameset:
                    continue
                frameset.add(inst['id'])
                clips[inst[orderby[0]] if len(orderby)> 0 and type(inst[orderby[0]]) in [str, unicode] else ''].append({
                    'frame': inst['id'],
                    'video_id': inst['video__id'],
                    'bboxes': bboxes[inst['id']],
                    'start': inst['number']
                })
        if len(distto_fields) > 0:
            FaceFeatures.dropTempFeatureModel()



    elif concept == 'faceinstance_diffs':
        # figure out the different labelers used
        labeler_names = FaceInstance.objects.values('labeler__name').distinct()
        labeler_names = [l['labeler__name'] for l in labeler_names]

        t = now()
        videos = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
        for labeler_name in labeler_names:
            labeler = Labeler.objects.get(name=labeler_name)
            faces = FaceInstance.objects.filter(labeler=labeler).values(*([
                'id', 'frame__id', 'frame__number', 'frame__video__id', 'labeler__name']+_get_bbox_vals('')))
            for face in faces:
                videos[face['frame__video__id']][face['frame__id']][labeler_name].append(face)
        _print('A: {:.3f}'.format(now() - t))

        t = now()
        mistakes = defaultdict(lambda: defaultdict(tuple))
        for video, frames in videos.iteritems():
            for frame, labelers in frames.iteritems():
                for labeler, bboxes in labelers.iteritems():
                    if labeler != 'handlabeled': continue
                    for bbox in bboxes:
                        bb = bbox
                        if (bb['bbox_x2'] - bb['bbox_x1']) * (bb['bbox_y2'] - bb['bbox_y1']) < 0.05:
                            continue

                        mistake = True
                        for other_labeler in labeler_names:
                            if labeler == other_labeler: continue
                            other_bboxes = labelers[
                                other_labeler] if other_labeler in labelers else []
                            for other_bbox in other_bboxes:
                                if _bbox_dist(_inst_to_bbox_dict('', bbox), _inst_to_bbox_dict('', other_bbox)) < DIFF_BBOX_THRESHOLD:
                                    mistake = False
                                    break

                            if mistake and len(other_bboxes) > 0:
                                mistakes[video][frame] = (bboxes, other_bboxes, other_labeler)
                                break
                        else:
                            continue
                        break
        _print('B: {:.3f}'.format(now() - t))

        t = now()
        video_keys = set()
        clips = defaultdict(list)
        for video, frames in list(mistakes.iteritems())[:20]:
            video_keys.add(video)
            path = Video.objects.get(id=video).path
            for frame, (bboxes, other_bboxes, other_labeler) in list(frames.iteritems())[::2]:
                clips[path].append({
                    'concept': bboxes[0]['id'],
                    'video_id': video,
                    'frame': frame,
                    'start': bboxes[0]['frame__number'],
                    'end': bboxes[0]['frame__number'],
                    'bboxes': bboxes_to_json(bboxes),
                    'other_bboxes': bboxes_to_json(other_bboxes),
                })  # yapf: disable
        _print('C: {:.3f}'.format(now() - t))

    videos = {v.id: model_to_dict(v) for v in Video.objects.filter(pk__in=video_keys)}
    colors = {
        l['labeler__name']: get_color(l['labeler__name'])
        for l in FaceInstance.objects.values('labeler__name').distinct()
    }
    return JsonResponse({'clips': clips, 'videos': videos, 'colors': colors})


LIMIT = 100
STRIDE = 1
def search2(request):
    params = json.loads(request.body)

    m = ModelDelegator(params['dataset'])
    Video, Frame, Face, FaceInstance, FaceFeatures, Labeler = m.Video, m.Frame, m.Face, m.FaceInstance, m.FaceFeatures, m.Labeler

    def make_error(err):
        return JsonResponse({'error': err})

    #### UTILITIES ####
    # TODO(wcrichto): move this into a separate, user-modifiable file

    def at_fps(qs, n=1):
        return qs.annotate(_tmp=F('number') % (Cast('video__fps', models.IntegerField()) / n)).filter(_tmp=0)

    def bbox_to_dict(f):
        return {
            'id': f.id,
            'bbox_x1': f.bbox_x1,
            'bbox_x2': f.bbox_x2,
            'bbox_y1': f.bbox_y1,
            'bbox_y2': f.bbox_y2,
            'bbox_score': f.bbox_score,
            'labeler': f.labeler.id
        }

    def bbox_area(f):
        return (f.bbox_x2 - f.bbox_x1) * (f.bbox_y2 - f.bbox_y1)

    def bbox_midpoint(f):
        return np.array([(f.bbox_x1 + f.bbox_x2) / 2, (f.bbox_y1 + f.bbox_y2) / 2])

    def bbox_dist(f1, f2):
        return np.linalg.norm(bbox_midpoint(f1) - bbox_midpoint(f2))


    ############### WARNING: DANGER -- REMOTE CODE EXECUTION ###############
    try:
        exec(params['code']) in globals(), locals()
    except Exception as e:
        return make_error(traceback.format_exc())
    ############### WARNING: DANGER -- REMOTE CODE EXECUTION ###############

    try:
        result
    except NameError:
        return make_error('Variable "result" must be set')

    materialized_result = []
    if isinstance(result, QuerySet):
        try:
            sample = result[0]
        except IndexError:
            return make_error('No results.')

        cls_name = '_'.join(sample.__class__.__name__.split('_')[1:])
        if cls_name == 'Frame':
            for frame in result[:LIMIT*STRIDE:STRIDE]:
                materialized_result.append({
                    'video': frame.video.id,
                    'start_frame': frame.id,
                    'bboxes': []
                })

        elif cls_name == 'FaceInstance':
            for inst in result[:LIMIT*STRIDE:STRIDE]:
                materialized_result.append({
                    'video': inst.frame.video.id,
                    'start_frame': inst.frame.id,
                    'bboxes': [bbox_to_dict(inst)]
                })

        elif cls_name == 'Face':
            faces = list(result[:LIMIT*STRIDE:STRIDE])

            # TODO: move to django 1.11, enable subquery

            # face_ids = [f.id for f in faces]
            # sq = FaceInstance.objects.filter(face_id=OuterRef('pk')).annotate(min_frame=Min('frame__number'))
            # tracks = Face \
            #     .filter(id__in=face_ids) \
            #     .annotate(min_frame=Subquery(sq.values('min_frame'))) \
            #     .values()

            for f in faces:
                bounds = FaceInstance.objects.filter(face=f).aggregate(min_frame=Min('frame__number'), max_frame=Max('frame__number'))
                min_face = FaceInstance.objects.get(frame__number=bounds['min_frame'], face=f)
                video = min_face.frame.video.id
                materialized_result.append({
                    'video': video,
                    'start_frame': Frame.objects.get(video_id=video, number=bounds['min_frame']).id,
                    'end_frame': Frame.objects.get(video_id=video, number=bounds['max_frame']).id,
                    'bboxes': [bbox_to_dict(min_face)]
                })
        else:
            return make_error('QuerySet for invalid object type {}'.format(cls_name))

    else:
        if not isinstance(result, list):
            return make_error('Result must be a QuerySet (for now) or frame list')
        else:
            materialized_result = result

    video_ids = set()
    frame_ids = set()
    labeler_ids = set()
    for obj in materialized_result:
        video_ids.add(obj['video'])
        frame_ids.add(obj['start_frame'])
        if 'end_frame' in obj:
            frame_ids.add(obj['end_frame'])

        for bbox in obj['bboxes']:
            labeler_ids.add(bbox['labeler'])

        obj['bboxes'] = bboxes_to_json(obj['bboxes'])

    def to_dict(qs):
        return {t.id: model_to_dict(t) for t in qs}

    videos = to_dict(Video.objects.filter(id__in=video_ids))
    frames = to_dict(Frame.objects.filter(id__in=frame_ids))
    labelers = to_dict(Labeler.objects.filter(id__in=labeler_ids))

    for r in materialized_result:
        path = Video.objects.get(id=r['video']).path
        frame = r['start_frame']
        number = Frame.objects.get(id=frame).number


    return JsonResponse({'success': {
        'result': materialized_result,
        'videos': videos,
        'frames': frames,
        'labelers': labelers,
    }})


def schema(request):
    params = json.loads(request.body)
    m = ModelDelegator(params['dataset'])

    cls = getattr(m, params['cls_name'])
    result = [r[params['field']] for r in cls.objects.values(params['field']).distinct().order_by(params['field'])[:LIMIT]]
    try:
        json.dumps(result)
    except TypeError as e:
        return JsonResponse({'error': str(e)})

    return JsonResponse({'result': result})


def build_index(request):
    id = request.GET.get('id', 4457280)
    m = ModelDelegator('tvnews')
    m.FaceFeatures.dropTempFeatureModel()
    m.FaceFeatures.getTempFeatureModel([id])
    return JsonResponse({})
