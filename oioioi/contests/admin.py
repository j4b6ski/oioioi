from functools import partial
import urllib

from django.conf.urls import url
from django.contrib.admin import AllValuesFieldListFilter, SimpleListFilter
from django.contrib.admin.sites import NotRegistered
from django.contrib.admin.utils import unquote, quote
from django.core.urlresolvers import reverse
from django.forms.models import modelform_factory
from django.http import HttpResponseRedirect
from django.shortcuts import redirect, render
from django.utils.translation import ugettext_lazy as _, ungettext_lazy
from django.utils.html import conditional_escape
from django.utils.encoding import force_unicode
from django.db.models import Value
from django.db.models.functions import Coalesce

from oioioi.base import admin
from oioioi.base.utils import make_html_links, make_html_link
from oioioi.contests.forms import ProblemInstanceForm, SimpleContestForm, \
        TestsSelectionForm
from oioioi.contests.menu import contest_admin_menu_registry, \
        contest_observer_menu_registry
from oioioi.contests.models import Contest, Round, ProblemInstance, \
        Submission, ContestAttachment, RoundTimeExtension, ContestPermission, \
        submission_kinds, ContestLink, SubmissionReport
from oioioi.contests.utils import is_contest_admin, is_contest_observer
from oioioi.contests.current_contest import set_cc_id
from oioioi.programs.models import Test, TestReport
from oioioi.problems.models import ProblemSite, ProblemPackage
from staszic.pd.permissions import has_personal_data_pass

class ContestProxyAdminSite(admin.AdminSite):
    def __init__(self, orig):
        super(ContestProxyAdminSite, self).__init__(orig.name)
        self._orig = orig

    def register(self, model_or_iterable, admin_class=None, **options):
        self._orig.register(model_or_iterable, admin_class, **options)

    def unregister(self, model_or_iterable):
        self._orig.unregister(model_or_iterable)
        try:
            super(ContestProxyAdminSite, self).unregister(model_or_iterable)
        except NotRegistered:
            pass

    def contest_register(self, model_or_iterable, admin_class=None, **options):
        super(ContestProxyAdminSite, self).register(model_or_iterable,
                admin_class, **options)

    def contest_unregister(self, model_or_iterable):
        super(ContestProxyAdminSite, self).unregister(model_or_iterable)

    def get_urls(self):
        self._registry.update(self._orig._registry)
        return super(ContestProxyAdminSite, self).get_urls()

    def index(self, request, extra_context=None):
        if request.contest:
            return super(ContestProxyAdminSite, self).\
                    index(request, extra_context)
        return self._orig.index(request, extra_context)

    def app_index(self, request, app_label, extra_context=None):
        if request.contest:
            return super(ContestProxyAdminSite, self).\
                    app_index(request, app_label, extra_context)
        return self._orig.app_index(request, app_label, extra_context)


#: Every contest-dependent model admin should be registered in this site
#: using the ``contest_register`` method. You can also register non-dependent
#: model admins like you would normally do using the ``register`` method.
#: Model admins registered using the ``contest_register`` method "don't exist"
#: when there is no active contest, that is, they can only be accessed
#: by a contest-prefixed URL and they don't show up in ``/admin/`` (but they
#: do in ``/c/<contest_id>/admin/``).
contest_site = ContestProxyAdminSite(admin.site)


class RoundInline(admin.StackedInline):
    model = Round
    extra = 0
    inline_classes = ('collapse open',)

    def has_add_permission(self, request):
        return True

    def has_change_permission(self, request, obj=None):
        return True

    def has_delete_permission(self, request, obj=None):
        return True

    def get_fieldsets(self, request, obj=None):
        fields = ['name', 'start_date', 'end_date', 'results_date',
                'public_results_date', 'is_trial']
        fields_no_public_results = ['name', 'start_date', 'end_date',
            'results_date', 'is_trial', 'can_submit_after_end']

        if request.contest is not None and request.contest.controller\
                .separate_public_results():
            fdsets = [(None, {'fields': fields})]
        else:
            fdsets = [(None, {'fields': fields_no_public_results})]
        return fdsets


class AttachmentInline(admin.StackedInline):
    model = ContestAttachment
    extra = 0
    readonly_fields = ['content_link']

    def has_add_permission(self, request):
        return True

    def has_change_permission(self, request, obj=None):
        return True

    def has_delete_permission(self, request, obj=None):
        return True

    def content_link(self, instance):
        if instance.id is not None:
            href = reverse('oioioi.contests.views.contest_attachment_view',
                        kwargs={'contest_id': str(instance.contest.id),
                                'attachment_id': str(instance.id)})
            return make_html_link(href, instance.content.name)
        return None
    content_link.short_description = _("Content file")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'round':
            kwargs['queryset'] = Round.objects.filter(contest=request.contest)
        return super(AttachmentInline, self) \
            .formfield_for_foreignkey(db_field, request, **kwargs)


class ContestLinkInline(admin.TabularInline):
    model = ContestLink
    extra = 0


class ContestAdmin(admin.ModelAdmin):
    inlines = [RoundInline, AttachmentInline, ContestLinkInline]
    readonly_fields = ['creation_date']
    prepopulated_fields = {'id': ('name',)}
    list_display = ['name', 'id', 'creation_date']
    list_display_links = ['id', 'name']
    ordering = ['-creation_date']

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        if not obj:
            return request.user.is_superuser
        return request.user.has_perm('contests.contest_admin', obj)

    def has_delete_permission(self, request, obj=None):
        return self.has_change_permission(request, obj)

    def get_fields(self, request, obj=None):
        fields = ['name', 'id', 'controller_name', 'default_submissions_limit',
            'contact_email']
        if request.user.is_superuser:
            fields += ['judging_priority', 'judging_weight']
        return fields

    def get_fieldsets(self, request, obj=None):
        if obj and not request.GET.get('simple', False):
            return super(ContestAdmin, self).get_fieldsets(request, obj)
        fields = SimpleContestForm().base_fields.keys()
        return [(None, {'fields': fields})]

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return self.readonly_fields + ['id', 'controller_name']
        return []

    def get_prepopulated_fields(self, request, obj=None):
        if obj:
            return {}
        return self.prepopulated_fields

    def get_form(self, request, obj=None, **kwargs):
        if obj and not request.GET.get('simple', False):
            return super(ContestAdmin, self).get_form(request, obj, **kwargs)
        return modelform_factory(self.model,
                form=SimpleContestForm,
                formfield_callback=partial(self.formfield_for_dbfield,
                    request=request),
                exclude=self.get_readonly_fields(request, obj))

    def get_inline_instances(self, request, obj=None):
        if obj and not request.GET.get('simple', False):
            return super(ContestAdmin, self).get_inline_instances(request, obj)
        return []

    def get_formsets(self, request, obj=None):
        if obj and not request.GET.get('simple', False):
            return super(ContestAdmin, self).get_formsets(request, obj)
        return []

    def response_change(self, request, obj):
        # Never redirect to the list of contests. Just re-display the edit
        # view.
        if '_popup' not in request.POST:
            return HttpResponseRedirect(request.get_full_path())
        return super(ContestAdmin, self).response_change(request, obj)

    def response_add(self, request, obj, post_url_continue=None):
        default_redirection = super(ContestAdmin, self).response_add(request,
                obj, post_url_continue)
        if '_continue' in request.POST or '_addanother' in request.POST:
            return default_redirection
        else:
            return redirect('default_contest_view', contest_id=obj.id)

    def response_delete(self, request):
        set_cc_id(None)
        return super(ContestAdmin, self).response_delete(request)

    def change_view(self, request, object_id, form_url='', extra_context=None):
        # The contest's edit view uses request.contest, so editing a contest
        # when a different contest is active would produce weird results.
        contest_id = unquote(object_id)
        if not request.contest or request.contest.id != contest_id:
            return redirect('oioioiadmin:contests_contest_change',
                    object_id, contest_id=contest_id)
        return super(ContestAdmin, self).change_view(request,
                object_id, form_url, extra_context)


class BaseContestAdmin(admin.MixinsAdmin):
    default_model_admin = ContestAdmin

    def _mixins_for_instance(self, request, instance=None):
        if instance:
            controller = instance.controller
            return controller.mixins_for_admin() + \
                    controller.registration_controller().mixins_for_admin()

contest_site.register(Contest, BaseContestAdmin)

contest_admin_menu_registry.register('contest_change', _("Settings"),
        lambda request: reverse('oioioiadmin:contests_contest_change',
            args=(quote(request.contest.id),)), order=20)


class ProblemInstanceAdmin(admin.ModelAdmin):
    form = ProblemInstanceForm
    fields = ('contest', 'round', 'problem', 'short_name', 'submissions_limit', 'score_weight', 'solution')
    list_display = ('name_link', 'short_name_link', 'round', 'package',
            'actions_field')
    readonly_fields = ('contest', 'problem')
    ordering = ('-round__start_date', 'short_name')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.contest is not None and is_contest_admin(request)

    def has_delete_permission(self, request, obj=None):
        return self.has_change_permission(request, obj)

    def _problem_change_href(self, instance):
        came_from = reverse('oioioiadmin:contests_probleminstance_changelist')
        return reverse('oioioiadmin:problems_problem_change',
                args=(instance.problem_id,)) + '?' + \
                        urllib.urlencode({'came_from': came_from})

    def probleminstance_change_link_name(self):
        return _("Edit problem")

    def _rejudge_all_submissions_for_problem_href(self, instance):
        return reverse('rejudge_all_submissions_for_problem',
                       args=(instance.id,))

    def _model_solutions_href(self, instance):
        return reverse('model_solutions', args=(instance.id,))

    def _problem_site_href(self, instance):
        return reverse('problem_site',
                       args=(instance.problem.problemsite.url_key,))

    def _reset_limits_href(self, instance):
        return reverse('reset_tests_limits_for_probleminstance',
                       args=(instance.id,))

    def _reload_limits_from_config_href(self, instance):
        return reverse('reload_tests_limits_for_probleminstance',
                       kwargs=({'problem_instance_id': instance.id}))

    def _reattach_problem_href(self, instance):
        return reverse('reattach_problem_contest_list', args=(instance.id,))

    def _add_or_update_href(self, instance):
        return reverse('problemset_add_or_update') + '?' + \
            urllib.urlencode({'problem': instance.problem_id, 'key': 'upload'})

    def inline_actions(self, instance):
        move_href = reverse('oioioiadmin:contests_probleminstance_change',
                args=(instance.id,))
        models_href = self._model_solutions_href(instance)
        assert ProblemSite.objects.filter(problem=instance.problem).exists()
        site_href = self._problem_site_href(instance)
        limits_href = self._reset_limits_href(instance)
        #config_limits_href = self._reload_limits_from_config_href(instance)
        reattach_href = self._reattach_problem_href(instance)
        result = [
            (move_href, self.probleminstance_change_link_name()),
            (models_href, _("Model solutions")),
            (site_href, _("Problem site")),
            (limits_href, _("Reset tests limits")),
            #(config_limits_href, _("Reload limits from config")),
            (reattach_href, _("Attach to another contest"))
        ]
        problem_count = len(ProblemInstance.objects.filter(
            problem=instance.problem_id))
        # Problem package can only be reuploaded if the problem instance
        # is only in one contest and in the problem base
        if problem_count <= 2:
            add_or_update_href = self._add_or_update_href(instance)
            result.append((add_or_update_href, _("Reupload package")))
        if instance.needs_rejudge:
            rejudge_all_href = self \
                ._rejudge_all_submissions_for_problem_href(instance)
            result.append((rejudge_all_href,
                           _("Rejudge all submissions for problem")))
        return result

    def actions_field(self, instance):
        return make_html_links(self.inline_actions(instance))
    actions_field.allow_tags = True
    actions_field.short_description = _("Actions")

    def name_link(self, instance):
        href = self._problem_change_href(instance)
        return make_html_link(href, instance.problem.name)
    name_link.allow_tags = True
    name_link.short_description = _("Problem")
    name_link.admin_order_field = 'problem__name'

    def short_name_link(self, instance):
        href = self._problem_change_href(instance)
        return make_html_link(href, instance.short_name)
    short_name_link.allow_tags = True
    short_name_link.short_description = _("Symbol")
    short_name_link.admin_order_field = 'short_name'

    def package(self, instance):
        problem_package = ProblemPackage.objects \
                .filter(problem=instance.problem).first()
        if problem_package and problem_package.package_file:
            href = reverse(
                    'oioioi.problems.views.download_problem_package_view',
                    kwargs={'package_id': str(problem_package.id)})
            return make_html_link(href, problem_package.package_file)
        return None
    package.short_description = _("Package file")

    def get_actions(self, request):
        # Disable delete_selected.
        actions = super(ProblemInstanceAdmin, self).get_actions(request)
        if 'delete_selected' in actions:
            del actions['delete_selected']
        return actions

    def get_custom_list_select_related(self):
        return super(ProblemInstanceAdmin, self)\
                   .get_custom_list_select_related() \
                + ['contest', 'round', 'problem']

    def get_queryset(self, request):
        qs = super(ProblemInstanceAdmin, self).get_queryset(request)
        qs = qs.filter(contest=request.contest)
        return qs


contest_site.contest_register(ProblemInstance, ProblemInstanceAdmin)


contest_admin_menu_registry.register('problems_change',
        _("Problems"), lambda request:
        reverse('oioioiadmin:contests_probleminstance_changelist'),
        order=30)


class ProblemFilter(AllValuesFieldListFilter):
    title = _("problem")


class ProblemNameListFilter(SimpleListFilter):
    title = _("problem")
    parameter_name = 'pi'

    def lookups(self, request, model_admin):
        p_names = []
        # Unique problem names
        if request.contest:
            p_names = list(set(ProblemInstance.objects
                    .filter(contest=request.contest)
                    .values_list('problem__name', flat=True)))

        return [(x, x) for x in p_names]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(
                    problem_instance__problem__name=self.value())
        else:
            return queryset


class SubmissionKindListFilter(SimpleListFilter):
    title = _("kind")
    parameter_name = 'kind'

    def lookups(self, request, model_admin):
        return submission_kinds

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(kind=self.value())
        else:
            return queryset


class SubmissionRoundListFilter(SimpleListFilter):
    title = _("round")
    parameter_name = 'round'

    def lookups(self, request, model_admin):
        r = []
        if request.contest:
            r = Round.objects.filter(contest=request.contest)
        return [(x, x) for x in r]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(problem_instance__round__name=self.value())
        else:
            return queryset


class ContestListFilter(SimpleListFilter):
    title = _("contest")
    parameter_name = 'contest'

    def lookups(self, request, model_admin):
        contests = list(Contest.objects.all())
        return [(x, x) for x in contests]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(
                problem_instance__contest__name=self.value())
        else:
            return queryset


class SubmissionAdmin(admin.ModelAdmin):
    date_hierarchy = 'date'
    actions = ['rejudge_action']
    search_fields = ['user__username', 'user__last_name']

    # We're using functions instead of lists because we want to
    # have different columns and filters depending on whether
    # contest is in url or not.
    def get_list_display(self, request):
        list_display = ['id', 'user_login', 'user_full_name', 'date',
            'problem_instance_display', 'contest_display', 'status_display',
            'score_display']
        if request.contest and not request.GET.get('all', False):
            list_display.remove('contest_display')
        return list_display

    def get_list_display_links(self, request, list_display):
        return ['id', 'date']

    def get_list_filter(self, request):
        list_filter = [ProblemNameListFilter, ContestListFilter,
                       SubmissionKindListFilter, 'status',
                       SubmissionRoundListFilter]
        if request.contest:
            list_filter.remove(ContestListFilter)
        else:
            list_filter.remove(SubmissionRoundListFilter)
        return list_filter

    def get_urls(self):
        urls = [
            url(r'^rejudge/$', self.rejudge_view),
        ]
        return urls + super(SubmissionAdmin, self).get_urls()

    def rejudge_view(self, request):
        tests = request.POST.getlist('tests', [])
        subs_ids = [int(x) for x in request.POST.getlist('submissions', [])]
        rejudge_type = request.POST['rejudge_type']
        submissions = Submission.objects.in_bulk(subs_ids)
        all_reports_exist = True
        for sub in submissions.values():
            if not SubmissionReport.objects.filter(submission=sub,
                                                   status='ACTIVE') \
                                           .exists():
                all_reports_exist = False
                break

        if all_reports_exist or rejudge_type == 'FULL':
            for sub in submissions.values():
                sub.problem_instance.controller.judge(sub,
                                 is_rejudge=True,
                                 extra_args={'tests_to_judge': tests,
                                             'rejudge_type': rejudge_type})

            counter = len(submissions)
            self.message_user(
                request,
                ungettext_lazy("Queued one submission for rejudge.",
                               "Queued %(counter)d submissions for rejudge.",
                               counter) % {'counter': counter})
        else:
            self.message_user(
                request,
                _("Cannot rejudge submissions due to lack of active reports "
                  "for one or more submissions"))

        return redirect('oioioiadmin:contests_submission_changelist')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        if obj:
            return False
        # is_contest_observer() is required in here, because otherwise
        # observers get a 403 response. Any actions that modify submissions
        # will be blocked in get_actions()
        return is_contest_admin(request) or is_contest_observer(request)

    def has_delete_permission(self, request, obj=None):
        return is_contest_admin(request)

    def has_rejudge_permission(self, request):
        return is_contest_admin(request)

    def get_actions(self, request):
        actions = super(SubmissionAdmin, self).get_actions(request)
        if not request.user.is_superuser:
            if not self.has_delete_permission(request):
                del actions['delete_selected']
            if not self.has_rejudge_permission(request):
                del actions['rejudge_action']
        return actions

    def user_login(self, instance):
        if not instance.user:
            return ''
        return instance.user.username
    user_login.short_description = _("Login")
    user_login.admin_order_field = 'user__username'

    def user_full_name(self, instance):
        if not instance.user:
            return ''
        return instance.user.get_full_name()
    user_full_name.short_description = _("User name")
    user_full_name.admin_order_field = 'user__last_name'

    def problem_instance_display(self, instance):
        if instance.kind != 'NORMAL':
            return '%s (%s)' % (force_unicode(instance.problem_instance),
                    force_unicode(instance.get_kind_display()))
        else:
            return instance.problem_instance
    problem_instance_display.short_description = _("Problem")
    problem_instance_display.admin_order_field = 'problem_instance'

    def status_display(self, instance):
        controller = instance.problem_instance.controller
        status_class = controller.get_status_class(None, instance)
        status_display = controller.get_status_display(None, instance)
        return '<span class="submission-admin ' \
               'submission submission--%s">%s</span>' % \
                (status_class, conditional_escape(force_unicode(status_display)))
    status_display.allow_tags = True
    status_display.short_description = _("Status")
    status_display.admin_order_field = 'status'

    def score_display(self, instance):
        return instance.get_score_display() or ''
    score_display.short_description = _("Score")
    score_display.admin_order_field = 'score_with_nulls_smallest'

    def contest_display(self, instance):
        return instance.problem_instance.contest
    contest_display.short_description = _("Contest")
    contest_display.admin_order_field = 'problem_instance__contest'

    def rejudge_action(self, request, queryset):
        # Otherwise the submissions are rejudged in their default display
        # order which is "newest first"
        queryset = queryset.order_by('id')

        pis = {s.problem_instance for s in queryset}
        pis_count = len(pis)
        sub_count = len(queryset)
        self.message_user(
            request,
            _("You have selected %(sub_count)d submission(s) from "
              "%(pis_count)d problem(s)") % {'sub_count': sub_count,
                                                'pis_count': pis_count})
        uses_is_active = False
        for pi in pis:
            if Test.objects.filter(problem_instance=pi,
                                   is_active=False) \
                           .exists():
                uses_is_active = True
                break
        if not uses_is_active:
            for sub in queryset:
                if TestReport.objects.filter(
                        submission_report__submission=sub,
                        submission_report__status='ACTIVE',
                        test__is_active=False).exists():
                    uses_is_active = True
                    break

        return render(request, 'contests/tests_choice.html',
                      {'form': TestsSelectionForm(request,
                                                  queryset,
                                                  pis_count,
                                                  uses_is_active)})
    rejudge_action.short_description = _("Rejudge selected submissions")

    def get_custom_list_select_related(self):
        return super(SubmissionAdmin, self).get_custom_list_select_related() \
                + ['user', 'problem_instance', 'problem_instance__problem',
                   'problem_instance__contest']

    def get_queryset(self, request):
        queryset = super(SubmissionAdmin, self).get_queryset(request)
        if request.contest and not request.GET.get('all', False):
            queryset = queryset \
                       .filter(problem_instance__contest=request.contest)
        queryset = queryset.order_by('-id')

        # Because nulls are treated as highest by default,
        # this is a workaround to make them smaller than other values.
        queryset = queryset.annotate(
            score_with_nulls_smallest=Coalesce('score', Value(''))
        )
        return queryset

    def lookup_allowed(self, key, value):
        if key == 'user__username':
            return True
        return super(SubmissionAdmin, self).lookup_allowed(key, value)

    def change_view(self, request, object_id, form_url='', extra_context=None):
        _contest_id = None
        if request.contest:
            _contest_id = request.contest.id
        if _contest_id is None:
            contest = Submission.objects.get(pk=object_id) \
                        .problem_instance.contest
            if contest:
                _contest_id = contest.id
        return redirect('submission', contest_id=_contest_id,
                        submission_id=unquote(object_id))

contest_site.register(Submission, SubmissionAdmin)

contest_admin_menu_registry.register('submissions_admin', _("Submissions"),
        lambda request: reverse('oioioiadmin:contests_submission_changelist'),
        order=40)

contest_observer_menu_registry.register('submissions_admin', _("Submissions"),
        lambda request: reverse('oioioiadmin:contests_submission_changelist'),
        order=40)

admin.system_admin_menu_registry.register('managesubmissions_admin',
        _("All submissions"), lambda request:
        '%s?all=1' % reverse('oioioiadmin:contests_submission_changelist',
                kwargs={'contest_id': None}), order=50, condition=has_personal_data_pass)


class RoundTimeRoundListFilter(SimpleListFilter):
    title = _("round")
    parameter_name = 'round'

    def lookups(self, request, model_admin):
        qs = model_admin.get_queryset(request)
        return Round.objects.filter(id__in=qs.values_list('round')) \
                .values_list('id', 'name')

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(round=self.value())
        else:
            return queryset


class RoundTimeExtensionAdmin(admin.ModelAdmin):
    list_display = ['user_login', 'user_full_name', 'round', 'extra_time']
    list_display_links = ['extra_time']
    list_filter = [RoundTimeRoundListFilter]
    search_fields = ['user__username', 'user__last_name']

    def has_add_permission(self, request):
        return is_contest_admin(request)

    def has_change_permission(self, request, obj=None):
        return is_contest_admin(request)

    def has_delete_permission(self, request, obj=None):
        return self.has_change_permission(request, obj)

    def user_login(self, instance):
        if not instance.user:
            return ''
        return make_html_link(
                reverse('user_info', kwargs={
                        'contest_id': instance.round.contest.id,
                        'user_id': instance.user.id}),
                instance.user.username)
    user_login.short_description = _("Login")
    user_login.admin_order_field = 'user__username'
    user_login.allow_tags = True

    def user_full_name(self, instance):
        if not instance.user:
            return ''
        return instance.user.get_full_name()
    user_full_name.short_description = _("User name")
    user_full_name.admin_order_field = 'user__last_name'

    def get_queryset(self, request):
        qs = super(RoundTimeExtensionAdmin, self).get_queryset(request)
        return qs.filter(round__contest=request.contest)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'round':
            kwargs['queryset'] = Round.objects.filter(contest=request.contest)
        return super(RoundTimeExtensionAdmin, self) \
                .formfield_for_foreignkey(db_field, request, **kwargs)

    def get_custom_list_select_related(self):
        return super(RoundTimeExtensionAdmin, self)\
                   .get_custom_list_select_related() \
                + ['user', 'round__contest']

contest_site.contest_register(RoundTimeExtension, RoundTimeExtensionAdmin)
contest_admin_menu_registry.register('roundtimeextension_admin',
        _("Round extensions"), lambda request:
        reverse('oioioiadmin:contests_roundtimeextension_changelist'),
        order=50)


class ContestPermissionAdmin(admin.ModelAdmin):
    list_display = ['permission', 'user', 'user_full_name']
    list_display_links = ['user']
    ordering = ['permission', 'user']

    def user_full_name(self, instance):
        if not instance.user:
            return ''
        return instance.user.get_full_name()
    user_full_name.short_description = _("User name")
    user_full_name.admin_order_field = 'user__last_name'

    def get_queryset(self, request):
        qs = super(ContestPermissionAdmin, self).get_queryset(request)
        if request.contest:
            qs = qs.filter(contest=request.contest)
        return qs

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'contest':
            qs = Contest.objects
            if request.contest:
                qs = qs.filter(id=request.contest.id)
                kwargs['initial'] = request.contest
            kwargs['queryset'] = qs
        return super(ContestPermissionAdmin, self) \
                .formfield_for_foreignkey(db_field, request, **kwargs)

contest_site.register(ContestPermission, ContestPermissionAdmin)
admin.system_admin_menu_registry.register('contestspermission_admin',
        _("Contest rights"), lambda request:
        reverse('oioioiadmin:contests_contestpermission_changelist'),
        order=50)
