from django.conf.urls import url

from oioioi.workers import views


urlpatterns = [
    url(r'^workers/$', views.show_info_about_workers, name='show_workers'),
    url(r'^workers/load.json$', views.get_load_json, name='get_load_json'),
    url(r'^workers/queue.json$', views.get_queue_json, name='get_queue_json'),
]
