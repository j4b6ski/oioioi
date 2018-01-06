from django.conf import settings
from django.conf.urls import include, url
from importlib import import_module
from django.contrib import admin as django_admin
from django.views import i18n

from oioioi.base import registration_backend
from oioioi.base.utils import is_internal_app_name
from oioioi.filetracker.views import raw_file_view

django_admin.autodiscover()

handler403 = 'oioioi.base.views.handler403'
handler404 = 'oioioi.base.views.handler404'
handler500 = 'oioioi.base.views.handler500'

js_info_dict = {
    'packages': ('oioioi',),
}

urlpatterns = [
    url(r'^jsi18n/$', i18n.javascript_catalog, js_info_dict),
]

if settings.DEBUG:
    import debug_toolbar
    urlpatterns += [
        url(r'^__debug__/', include(debug_toolbar.urls)),
    ]

for app in settings.INSTALLED_APPS:
    if is_internal_app_name(app):
        try:
            # Django imports views lazily, and sice there are some decorators
            # that have to run, all views need to be imported at startup
            import_module(app + '.views')
            urls_module = import_module(app + '.urls')
            if hasattr(urls_module, 'urlpatterns'):
                urlpatterns += getattr(urls_module, 'urlpatterns')
        except ImportError:
            pass

urlpatterns.extend([
    url(r'^file/(?P<filename>.*)/$', raw_file_view),
])

urlpatterns += registration_backend.urlpatterns
