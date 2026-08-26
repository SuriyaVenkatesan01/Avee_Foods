"""
URL configuration for avee_foods project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import path, include, re_path
from django.conf import settings
from django.views.generic import TemplateView
from django.views.static import serve

from website.sitemaps import SITEMAPS

urlpatterns = [
    path("admin/", admin.site.urls),
    path("dashboard/", include("dashboard.urls")),
    # Search engines
    path("sitemap.xml", sitemap, {"sitemaps": SITEMAPS},
         name="django.contrib.sitemaps.views.sitemap"),
    path("robots.txt", TemplateView.as_view(
        template_name="robots.txt", content_type="text/plain"), name="robots"),
    path("", include("website.urls")),
]

# Serve user uploads (product/gallery images) in every environment.
#
# WhiteNoise only handles STATIC_ROOT, and django.conf.urls.static.static() is
# a no-op once DEBUG is off -- so without this, every uploaded image 404s in
# production. Serving through Django is slower than a real file server, but
# this storefront's media volume is small and the files live on Render's
# persistent disk. Move to a CDN/object store if image traffic grows.
urlpatterns += [
    re_path(
        r"^%s(?P<path>.*)$" % settings.MEDIA_URL.lstrip("/"),
        serve,
        {"document_root": settings.MEDIA_ROOT},
    ),
]
