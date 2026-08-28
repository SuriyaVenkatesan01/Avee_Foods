"""Push the existing local media/ tree into Cloudinary.

One-time migration for a store whose images were uploaded while the site ran
on a host with a writable disk. The database stores relative paths
("products/oil.jpg"), and ImageField.url turns those into Cloudinary URLs, so
each file has to land under the public_id that its stored path implies --
otherwise every product page renders broken images against a bucket that does
in fact contain the file.

Run once, locally, with CLOUDINARY_URL set:

    python manage.py upload_media --dry-run     # see what would happen
    python manage.py upload_media
"""

import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from avee_foods.storage import resource_type_for


def _public_id(relative_path, resource_type):
    """The public_id that MediaStorage.url() will ask Cloudinary for.

    Cloudinary treats the extension as a delivery format for images and
    video, so their public_id carries no extension; raw files are served
    byte-for-byte and keep theirs.
    """
    name = settings.MEDIA_URL.lstrip('/') + relative_path.replace('\\', '/')
    if resource_type in ('image', 'video'):
        name = os.path.splitext(name)[0]
    return name


class Command(BaseCommand):
    help = "Upload everything under MEDIA_ROOT to Cloudinary, preserving paths."

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='List what would be uploaded without sending anything.',
        )
        parser.add_argument(
            '--max-mb', type=float, default=100.0,
            help='Skip files above this size (Cloudinary free tier caps at '
                 '100 MB; larger files need compressing first).',
        )

    def handle(self, *args, **options):
        if not settings.USE_CLOUDINARY:
            raise CommandError(
                "CLOUDINARY_URL is not set, so there is nowhere to upload to. "
                "Set it in .env or the shell environment and re-run."
            )

        import cloudinary.uploader

        root = str(settings.MEDIA_ROOT)
        if not os.path.isdir(root):
            raise CommandError(f"MEDIA_ROOT does not exist: {root}")

        dry_run = options['dry_run']
        max_bytes = options['max_mb'] * 1024 * 1024
        uploaded = skipped = failed = 0

        for dirpath, _dirnames, filenames in os.walk(root):
            for filename in sorted(filenames):
                full = os.path.join(dirpath, filename)
                rel = os.path.relpath(full, root).replace('\\', '/')
                size = os.path.getsize(full)
                rtype = resource_type_for(rel)
                pid = _public_id(rel, rtype)

                if size > max_bytes:
                    skipped += 1
                    self.stdout.write(self.style.WARNING(
                        f"SKIP  {rel}  ({size / 1024 / 1024:.1f} MB exceeds "
                        f"{options['max_mb']:.0f} MB -- compress it first)"
                    ))
                    continue

                if dry_run:
                    self.stdout.write(f"WOULD {rtype:5s} {rel} -> {pid}")
                    uploaded += 1
                    continue

                try:
                    cloudinary.uploader.upload(
                        full,
                        public_id=pid,
                        resource_type=rtype,
                        # The stored path is the identity; never let Cloudinary
                        # invent a suffix or the DB rows stop resolving.
                        use_filename=False,
                        unique_filename=False,
                        overwrite=True,
                        invalidate=True,
                    )
                except Exception as exc:                # noqa: BLE001
                    failed += 1
                    self.stdout.write(self.style.ERROR(f"FAIL  {rel}: {exc}"))
                else:
                    uploaded += 1
                    self.stdout.write(self.style.SUCCESS(f"OK    {rtype:5s} {rel}"))

        self.stdout.write("")
        self.stdout.write(
            f"{'would upload' if dry_run else 'uploaded'}: {uploaded}   "
            f"skipped (too large): {skipped}   failed: {failed}"
        )
        if skipped:
            self.stdout.write(self.style.WARNING(
                "Skipped files are still referenced by the database and will "
                "404 until they are compressed and re-run."
            ))
