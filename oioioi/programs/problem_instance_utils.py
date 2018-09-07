from django.conf import settings


def get_allowed_languages_dict(problem_instance):
    lang_dict = problem_instance.controller.get_allowed_languages_dict(problem_instance)
    return {lang: lang_dict[lang] for lang
            in problem_instance.controller.get_allowed_languages()}


def get_allowed_languages_extensions(problem_instance):
    lang_exts = get_allowed_languages_dict(problem_instance).values()
    return [ext for lang in lang_exts for ext in lang]


def get_language_by_extension(problem_instance, ext):
    for lang, extension_list in get_allowed_languages_dict(
            problem_instance).items():
        if ext in extension_list:
            return lang
    return None
