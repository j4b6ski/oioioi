from django import forms
from django.contrib.admin import widgets
from django.core.urlresolvers import reverse
from django.forms import ValidationError
from django.utils import timezone
from django.utils.module_loading import import_string
from django.utils.translation import ugettext_lazy as _
from oioioi.base.utils.user_selection import UserSelectionField
from oioioi.base.utils.inputs import narrow_input_field
from oioioi.contests.models import Contest, ProblemInstance, Round, ContestAttachment
from oioioi.contests.utils import submittable_problem_instances
from oioioi.programs.models import Test


class SimpleContestForm(forms.ModelForm):
    class Meta(object):
        model = Contest
        # Order of fields is important - focus after sending incomplete
        # form should not be on the 'name' field, otherwise the 'id' field,
        # as prepopulated with 'name' in ContestAdmin model, is cleared by
        # javascript with prepopulated fields functionality.
        fields = ['controller_name', 'name', 'id']

    start_date = forms.SplitDateTimeField(
        label=_("Start date"), widget=widgets.AdminSplitDateTime())
    end_date = forms.SplitDateTimeField(
        required=False, label=_("End date"),
        widget=widgets.AdminSplitDateTime())
    results_date = forms.SplitDateTimeField(
        required=False, label=_("Results date"),
        widget=widgets.AdminSplitDateTime())

    def _generate_default_dates(self):
        now = timezone.now()
        self.initial['start_date'] = now
        self.initial['end_date'] = None
        self.initial['results_date'] = None

    def _set_dates(self, round):
        for date in ['start_date', 'end_date', 'results_date']:
            setattr(round, date, self.cleaned_data.get(date))

    def __init__(self, *args, **kwargs):
        super(SimpleContestForm, self).__init__(*args, **kwargs)
        instance = kwargs.get('instance', None)
        if instance is not None:
            rounds = instance.round_set.all()
            if len(rounds) > 1:
                raise ValueError("SimpleContestForm does not support contests "
                        "with more than one round.")
            if len(rounds) == 1:
                round = rounds[0]
                self.initial['start_date'] = round.start_date
                self.initial['end_date'] = round.end_date
                self.initial['results_date'] = round.results_date
            else:
                self._generate_default_dates()
        else:
            self._generate_default_dates()

        #old_choices = self.fields['controller_name'].choices
        #new_choices = old_choices[:1] + [(x, y) for (x, y) in old_choices[1:] if
        #        getattr(import_string(x), 'visible', False)]
        #self.fields['controller_name'].choices = new_choices

    def clean(self):
        cleaned_data = super(SimpleContestForm, self).clean()
        round = Round()
        self._set_dates(round)
        round.clean()
        return cleaned_data

    def save(self, commit=True):
        instance = super(SimpleContestForm, self).save(commit=False)
        rounds = instance.round_set.all()
        if len(rounds) > 1:
            raise ValueError("SimpleContestForm does not support contests "
                    "with more than one round.")
        if len(rounds) == 1:
            round = rounds[0]
        else:
            instance.save()
            round = Round(contest=instance, name=_("Round 1"))
        self._set_dates(round)
        round.save()

        if commit:
            instance.save()

        return instance


class ProblemInstanceForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        instance = kwargs.get('instance')
        super(ProblemInstanceForm, self).__init__(*args, **kwargs)
        if instance:
            self.fields['round'].queryset = instance.contest.round_set
            self.fields['round'].required = True
            self.fields['solution'].queryset = ContestAttachment.objects.filter(contest=instance.contest)


class SubmissionForm(forms.Form):
    """Represents base submission form containing task selector.

       Recognized optional ``**kwargs`` fields:
         * ``problem_filter`` Function filtering submittable tasks.
         * ``kind`` Kind of submission accessible with ``kind`` property.
         * ``problem_instance`` - when SubmissionForm is used only for one
             problem_instance. Otherwise ``problem_instance`` is None.
    """
    problem_instance_id = forms.ChoiceField(label=_("Problem"))

    def __init__(self, request, *args, **kwargs):
        problem_instance = kwargs.pop('problem_instance', None)
        if problem_instance is None:
            # if problem_instance does not exist any from the current
            # contest is chosen. To change in future.
            # ALSO in mailsubmit.forms
            contest = request.contest
            assert contest is not None
            problem_instance = ProblemInstance.objects \
                    .filter(contest=contest)[0]

        controller = problem_instance.controller
        self.kind = kwargs.pop('kind',
                controller.get_default_submission_kind(request,
                                       problem_instance=problem_instance))
        problem_filter = kwargs.pop('problem_filter', None)
        self.request = request

        # taking the available problems
        pis = self.get_problem_instances()
        if problem_filter:
            pis = problem_filter(pis)
        pi_choices = [(pi.id, unicode(pi)) for pi in pis]

        # pylint: disable=non-parent-init-called
        # init form with previously sent data
        forms.Form.__init__(self, *args, **kwargs)

        # set available problems in form
        pi_field = self.fields['problem_instance_id']
        pi_field.widget.attrs['class'] = 'input-xlarge'

        if len(pi_choices) > 1:
            pi_field.choices = [('', '')] + pi_choices
        else:
            pi_field.choices = pi_choices

        narrow_input_field(pi_field)

        # adding additional fields, etc
        controller.adjust_submission_form(request, self, problem_instance)

    def get_problem_instances(self):
        return submittable_problem_instances(self.request)

    def is_valid(self):
        return forms.Form.is_valid(self)

    def clean(self, check_submission_limit=True, check_round_times=True):
        cleaned_data = forms.Form.clean(self)

        if 'kind' not in cleaned_data:
            cleaned_data['kind'] = self.kind

        if 'problem_instance_id' not in cleaned_data:
            return cleaned_data

        try:
            pi = ProblemInstance.objects \
                    .get(id=cleaned_data['problem_instance_id'])
            cleaned_data['problem_instance'] = pi
        except ProblemInstance.DoesNotExist:
            self._errors['problem_instance_id'] = \
                    self.error_class([_("Invalid problem")])
            del cleaned_data['problem_instance_id']
            return cleaned_data

        pcontroller = pi.problem.controller
        kind = cleaned_data['kind']
        if check_submission_limit and pcontroller \
                .is_submissions_limit_exceeded(self.request, pi, kind):
            raise ValidationError(_("Submission limit for the problem '%s' "
                                    "exceeded.") % pi.problem.name)

        decision = pi.controller.can_submit(self.request, pi,
                                            check_round_times)
        if not decision:
            raise ValidationError(str(getattr(decision, 'exc',
                                              _("Permission denied"))))

        if cleaned_data['prog_lang'] and \
                cleaned_data['prog_lang'] not in \
                pi.controller.get_allowed_languages():
            self._errors['prog_lang'] = \
                    self.error_class([_("Disallowed language")])
            del cleaned_data['prog_lang']
            return cleaned_data

        return pi.controller.validate_submission_form(self.request, pi, self,
                                                    cleaned_data)


class SubmissionFormForProblemInstance(SubmissionForm):
    def __init__(self, request, problem_instance, *args, **kwargs):
        self.problem_instance = problem_instance
        kwargs['problem_instance'] = problem_instance
        super(SubmissionFormForProblemInstance, self).__init__(request, *args,
                **kwargs)
        self.fields['problem_instance_id'].widget.attrs['readonly'] = 'True'

    def get_problem_instances(self):
        return [self.problem_instance]


class GetUserInfoForm(forms.Form):
    user = UserSelectionField(label=_("Username"))

    def __init__(self, request, *args, **kwargs):
        super(GetUserInfoForm, self).__init__(*args, **kwargs)
        self.fields['user'].hints_url = reverse('contest_user_hints',
                kwargs={'contest_id': request.contest.id})


class TestsSelectionForm(forms.Form):
    def __init__(self, request, queryset, pis_count, uses_is_active, *args,
                 **kwargs):
        super(TestsSelectionForm, self).__init__(*args, **kwargs)
        problem_instance = queryset[0].problem_instance
        tests = Test.objects.filter(problem_instance=problem_instance,
                is_active=True)

        widget = forms.RadioSelect(
            attrs={'onChange': 'rejudgeTypeOnChange(this)'})
        self.fields['rejudge_type'] = forms.ChoiceField(widget=widget)
        if uses_is_active:
            self.fields['rejudge_type'].choices = \
                    [('FULL', _("Rejudge submissions on all current active "
                                "tests")),
                     ('NEW', _("Rejudge submissions on active tests which "
                               "haven't been judged yet"))]
        else:
            self.fields['rejudge_type'].choices = \
                    [('FULL', _("Rejudge submissions on all tests"))]

        self.initial['rejudge_type'] = 'FULL'

        if pis_count == 1:
            self.fields['rejudge_type'].choices.append(
                ('JUDGED', _("Rejudge submissions on judged tests only")))

            self.fields['tests'] = forms.MultipleChoiceField(
                widget=forms.CheckboxSelectMultiple(
                    attrs={'disabled': 'disabled'}),
                choices=[(test.name, test.name) for test in tests])

        self.fields['submissions'] = forms.ModelMultipleChoiceField(
            widget=forms.CheckboxSelectMultiple,
            queryset=queryset,
            initial=queryset)
