"""Storage backends for a host with no writable, persistent filesystem.

Imported by settings via dotted path, so this module must not import Django
models or anything that touches the app registry.
"""

import os

from django.core.exceptions import ImproperlyConfigured
from whitenoise.storage import CompressedManifestStaticFilesStorage

try:
    from cloudinary_storage.storage import MediaCloudinaryStorage
except (ImportError, ImproperlyConfigured):
    # Cloudinary is optional. Note it raises ImproperlyConfigured at *import*
    # time when no credentials are present, so catching ImportError alone is
    # not enough -- and models.py imports this module purely for the
    # extension lists, which must keep working on a local sqlite run.
    MediaCloudinaryStorage = None


# Cloudinary files each have a resource type baked into their delivery URL,
# and it cannot be guessed at read time -- ``/image/upload/`` simply 404s for
# an asset stored as a video. HomeBanner.file accepts both kinds in a single
# FileField, so the type has to be derived from the extension on both upload
# and URL generation, or hero videos break while photos work.
#
# website.models.HomeBanner imports these, so the validator that decides what
# may be uploaded and the storage that decides where it lands cannot drift.
# What the banner picker offers a user. Deliberately narrow: these are the
# formats we are happy to publish, not everything that could be decoded.
IMAGE_EXTENSIONS = ['jpg', 'jpeg', 'png', 'webp', 'gif', 'avif']
VIDEO_EXTENSIONS = ['mp4', 'webm', 'ogg', 'mov', 'm4v']

# What Cloudinary should *treat* as an image, which is a different question --
# it has to cover every format already sitting in the database, including ones
# the picker above would reject today. .jfif is the case that matters here:
# it is ordinary JPEG, 25 product shots use it, and typing it as 'raw' would
# hand it back unoptimised with the wrong content type.
IMAGE_RESOURCE_EXTENSIONS = set(IMAGE_EXTENSIONS) | {
    'jfif', 'jpe', 'jif', 'bmp', 'tif', 'tiff', 'heic', 'heif', 'ico', 'svg',
}
VIDEO_RESOURCE_EXTENSIONS = set(VIDEO_EXTENSIONS) | {'avi', 'mkv', 'mpeg', '3gp'}

# Extensions Cloudinary stores happily but will not hand back under that name.
# Uploads are keyed by path-without-extension, so the extension in a delivery
# URL is a *format request* -- ask for .jfif and Cloudinary has no such output
# format and errors, even though the bytes are there. Mapping to the real
# format lets it transcode on the fly, and no database rows have to change.
DELIVERY_FORMAT_OVERRIDES = {
    'jfif': 'jpg', 'jpe': 'jpg', 'jif': 'jpg',
    'bmp': 'jpg', 'tif': 'jpg', 'tiff': 'jpg',
    'heic': 'jpg', 'heif': 'jpg',
}


def resource_type_for(name):
    """How Cloudinary must store and serve this file.

    Shared with the upload_media management command so a migrated file and
    the URL generated for it can never disagree about its resource type.
    """
    ext = os.path.splitext(name)[1].lstrip('.').lower()
    if ext in VIDEO_RESOURCE_EXTENSIONS:
        return 'video'
    if ext in IMAGE_RESOURCE_EXTENSIONS:
        return 'image'
    # PDFs, docs and anything else Cloudinary should hand back byte-for-byte
    # rather than try to transcode.
    return 'raw'


class ForgivingManifestStaticFilesStorage(CompressedManifestStaticFilesStorage):
    """Cache-busts when the manifest is present, degrades when it is not.

    ManifestStaticFilesStorage raises ValueError the moment a template
    references a file missing from staticfiles.json, so a host that skips
    collectstatic turns one absent asset into a 500 on every page.
    ``manifest_strict = False`` returns the unhashed path instead: the file
    loses cache-busting, the storefront stays up.
    """

    manifest_strict = False


if MediaCloudinaryStorage is not None:

    class MediaStorage(MediaCloudinaryStorage):
        """Routes each upload to the Cloudinary resource type that fits it.

        The base class hardcodes one type for the whole storage; the hook it
        provides exists so a single FileField can hold mixed media.
        """

        def _get_resource_type(self, name):
            return resource_type_for(name)

        def _get_url(self, name):
            root, ext = os.path.splitext(name)
            fmt = DELIVERY_FORMAT_OVERRIDES.get(ext.lstrip('.').lower())
            if fmt and resource_type_for(name) == 'image':
                name = f'{root}.{fmt}'
            return super()._get_url(name)
