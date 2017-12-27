from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.http import Http404
from django_tenants.utils import remove_www, get_public_schema_name, get_tenant_domain_model
import django

if django.VERSION >= (1, 10, 0):
    MIDDLEWARE_MIXIN = django.utils.deprecation.MiddlewareMixin
else:
    MIDDLEWARE_MIXIN = object


class TenantMainMiddleware(MIDDLEWARE_MIXIN):
    TENANT_NOT_FOUND_EXCEPTION = Http404
    DOMAIN_NOT_FOUND_EXCEPTION = Http404
    """
    This middleware should be placed at the very top of the middleware stack.
    Selects the proper database schema using the request host. Can fail in
    various ways which is better than corrupting or revealing data.
    """

    @staticmethod
    def hostname_from_request(request):
        """ Extracts hostname from request. Used for custom requests filtering.
            By default removes the request's port and common prefixes.
        """
        return remove_www(request.get_host().split(':')[0])

    def get_domain(self, domain_model, hostname):
        domain = domain_model.objects.select_related('tenant').get(domain=hostname)
        return domain

    def get_tenant(self, domain_model, hostname):
        domain = self.get_domain(domain_model, hostname)
        return domain.tenant

    def process_request(self, request):
        # Connection needs first to be at the public schema, as this is where
        # the tenant metadata is stored.
        connection.set_schema_to_public()
        hostname = self.hostname_from_request(request)

        domain_model = get_tenant_domain_model()
        try:
            domain = self.get_domain(domain_model, hostname)
            tenant = domain.tenant
            if not tenant:
                raise self.TENANT_NOT_FOUND_EXCEPTION('No tenant for hostname "%s"' % hostname)
        except domain_model.DoesNotExist:
            raise self.DOMAIN_NOT_FOUND_EXCEPTION('No domain for hostname "%s"' % hostname)

        # domain.tenant.domain_url = hostname
        # domain.tenant.current_domain = domain
        # request.tenant = domain.tenant
        # request.tenant_current_domain = domain

        # set 'current_domain' in 'tenant' to use across your application, e.g:
        # ...
        # from django.db import connection
        # if connection.tenant.current_domain.id == any_id:
        #    do ...
        # ...
        tenant.current_domain = domain
        tenant.domain_url = hostname
        request.tenant = tenant
        request.tenant_current_domain = domain

        connection.set_tenant(request.tenant)

        # Content type can no longer be cached as public and tenant schemas
        # have different models. If someone wants to change this, the cache
        # needs to be separated between public and shared schemas. If this
        # cache isn't cleared, this can cause permission problems. For example,
        # on public, a particular model has id 14, but on the tenants it has
        # the id 15. if 14 is cached instead of 15, the permissions for the
        # wrong model will be fetched.
        ContentType.objects.clear_cache()

        # Do we have a public-specific urlconf?
        if hasattr(settings, 'PUBLIC_SCHEMA_URLCONF') and request.tenant.schema_name == get_public_schema_name():
            request.urlconf = settings.PUBLIC_SCHEMA_URLCONF
