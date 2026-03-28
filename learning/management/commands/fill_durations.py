import re
import requests

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from learning.models import Lesson

YOUTUBE_API_URL = 'https://www.googleapis.com/youtube/v3/videos'
BATCH_SIZE = 50


def parse_iso8601_duration(duration_str):
    """Parse ISO 8601 duration (e.g. 'PT1H2M30S') to total seconds."""
    match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration_str)
    if not match:
        return None
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


class Command(BaseCommand):
    help = 'Fetch duration_seconds for lessons from the YouTube Data API v3.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--all',
            action='store_true',
            help='Refetch duration for ALL lessons, not just ones with null duration.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be updated without saving to the database.',
        )

    def handle(self, *args, **options):
        api_key = settings.YOUTUBE_API_KEY
        if not api_key:
            raise CommandError('YOUTUBE_API_KEY is not set in settings.')

        fetch_all = options['all']
        dry_run = options['dry_run']

        qs = Lesson.objects.exclude(youtube_video_id='')
        if not fetch_all:
            qs = qs.filter(duration_seconds__isnull=True)

        lessons = list(qs.only('id', 'youtube_video_id', 'duration_seconds'))
        total = len(lessons)

        if total == 0:
            self.stdout.write('No lessons need updating.')
            return

        self.stdout.write(f'Found {total} lessons without duration.')

        # Build a map from video_id → list of lesson objects (a video can appear
        # in multiple lessons, though uncommon).
        video_id_to_lessons: dict[str, list[Lesson]] = {}
        for lesson in lessons:
            video_id_to_lessons.setdefault(lesson.youtube_video_id, []).append(lesson)

        unique_ids = list(video_id_to_lessons.keys())
        batches = [unique_ids[i:i + BATCH_SIZE] for i in range(0, len(unique_ids), BATCH_SIZE)]
        total_batches = len(batches)

        updated = 0
        skipped = 0
        to_update: list[Lesson] = []

        for batch_num, batch in enumerate(batches, start=1):
            try:
                response = requests.get(
                    YOUTUBE_API_URL,
                    params={
                        'part': 'contentDetails',
                        'id': ','.join(batch),
                        'key': api_key,
                    },
                    timeout=15,
                )
                response.raise_for_status()
            except requests.RequestException as exc:
                self.stderr.write(f'Batch {batch_num}/{total_batches}: request failed — {exc}')
                skipped += sum(len(video_id_to_lessons[vid]) for vid in batch)
                continue

            data = response.json()
            found_ids = set()

            for item in data.get('items', []):
                video_id = item['id']
                duration_str = item.get('contentDetails', {}).get('duration', '')
                seconds = parse_iso8601_duration(duration_str)
                if seconds is None:
                    self.stderr.write(f'  Could not parse duration "{duration_str}" for {video_id}')
                    skipped += len(video_id_to_lessons.get(video_id, []))
                    continue

                found_ids.add(video_id)
                for lesson in video_id_to_lessons.get(video_id, []):
                    lesson.duration_seconds = seconds
                    to_update.append(lesson)
                    updated += 1

            missing = set(batch) - found_ids
            for vid in missing:
                count = len(video_id_to_lessons.get(vid, []))
                skipped += count

            fetched = len(found_ids)
            self.stdout.write(f'Batch {batch_num}/{total_batches}: fetched {fetched} durations')

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f'Dry run — no changes saved. '
                    f'Would update: {updated}, Skipped (not found on YouTube): {skipped}'
                )
            )
            return

        if to_update:
            Lesson.objects.bulk_update(to_update, ['duration_seconds'])

        self.stdout.write(
            self.style.SUCCESS(
                f'Done. Updated: {updated}, Skipped (not found on YouTube): {skipped}'
            )
        )
