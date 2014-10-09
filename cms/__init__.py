from cms.utils import CmsRepo, CmsRepoException

from pyramid_beaker import set_cache_regions_from_settings
from pyramid.config import Configurator

import logging
log = logging.getLogger(__name__)


def main(global_config, **settings):
    """ This function returns a Pyramid WSGI application.
    """
    set_cache_regions_from_settings(settings)
    config = Configurator(settings=settings)
    config.include('cms')
    return config.make_wsgi_app()


def init_repository(config):
    settings = config.registry.settings

    if 'git.path' not in settings:
        raise KeyError(
            'Please specify the git repo path '
            'e.g [app:main] git.path = %(here)s/repo/')

    repo_path = settings['git.path'].strip()

    if 'git.content_repo_url' in settings \
            and settings['git.content_repo_url'] \
            and not CmsRepo.exists(repo_path):
        content_repo_url = settings['git.content_repo_url'].strip()
        log.info('Cloning repository: %s' % (content_repo_url,))
        repo = CmsRepo.clone(content_repo_url, repo_path)
        log.info('Cloned repository into: %s' % (repo_path,))

    try:
        repo = CmsRepo.read(repo_path)
        log.info('Using repository found in: %s' % (repo_path,))
    except CmsRepoException:
        repo = CmsRepo.init(
            repo_path, 'Unicore CMS', 'support@unicore.io')
        log.info('Initialising repository in: %s' % (repo_path,))

    repo.checkout_all_upstream()


def includeme(config):
    config.include('pyramid_chameleon')
    config.include('pyramid_beaker')
    config.include("cornice")
    config.include("pyramid_celery")
    config.add_static_view('static', 'cms:static', cache_max_age=3600)
    config.add_route('home', '/')
    config.add_route('categories', '/content/list/')
    config.add_route('category', '/content/list/{category}/')
    config.add_route('content', '/content/detail/{uuid}/')
    config.add_route('admin_home', '/admin/')
    config.add_route('configure', '/admin/configure/')
    config.add_route('configure_switch', '/admin/configure/switch/')
    config.add_route('check_updates', '/admin/configure/update/')
    config.add_route('configure_fast_forward', '/admin/configure/fastforward/')
    config.add_route('commit_log', '/admin/configure/log.json')
    config.add_route('get_updates', '/admin/configure/updates.json')
    config.add_route('locale', '/locale/')
    config.add_route('flatpage', '/{slug}/')
    config.scan()

    init_repository(config)
